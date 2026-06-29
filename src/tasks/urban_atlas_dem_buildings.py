"""
A task for processing UrbanAtlas files
"""
import os
from .base import BaseTask
from src.logger import debug, progress, verbose, error, sql_debug, sql_verbose
from src.utils.linux_cmds import ShapefileImporter
from src.utils.spatial import compute_envelope


class UrbanAtlasDemBuildings(BaseTask):
    """
    Handles the initial setup: creating PostGIS extensions,
    verifying directories, and importing vector data.
    """

    def run(self):
        if not self.cfg._settings.get('envelope'):
            compute_envelope(
                self.cfg, self.db,
                schema=self.cfg.domain.case_schema,
                table=self.cfg.tables.im_landcover_or,
                srid=self.cfg.srid,
            )
        self.run_dem()
        self.run_buildings()

    def run_dem(self):
        progress('Processing DEM')

        # 1. Update Raster SRID
        debug('Updating DEM raster with SRID')
        sqltext = f"SELECT UpdateRasterSRID(%s, %s, %s, %s)"
        params = (
            self.cfg.domain.case_schema,
            self.cfg.tables.dem_or,
            'rast',
            self.cfg.dem_srid
        )
        self.execute(sqltext, params)

        # 2. Clip entries outside the envelope
        debug('Delete all entries from DEM imported table that are outside envelope')
        sqltext = f"""
            DELETE FROM "{self.cfg.domain.case_schema}"."{self.cfg.tables.dem_or}" 
            WHERE NOT ST_Intersects(ST_Transform(%s::geometry, %s), rast)
        """
        self.execute(sqltext, (self.cfg.envelope, self.cfg.dem_srid))

        # 3. Transform coordinates and create new DEM table
        debug('Create new table with transformed coordinates')
        # We use f-strings for the structural parts and %s for the values
        sqltext = f"""
            DROP TABLE IF EXISTS "{self.cfg.domain.case_schema}"."{self.cfg.tables.dem}"; 

            CREATE TABLE "{self.cfg.domain.case_schema}"."{self.cfg.tables.dem}" AS 
            SELECT ROW_NUMBER() OVER(ORDER BY t.rast::geometry) AS rid, 
                   ST_Union(ST_Clip( ST_Transform( r.rast, t.rast), t.rast::geometry ), 'MAX') AS rast 
            FROM (
                SELECT ST_Transform(ST_SetSRID(ST_Extent(rast::geometry), %s), %s) AS geom 
                FROM "{self.cfg.domain.case_schema}"."{self.cfg.tables.dem_or}"
            ) AS g, 
            ST_MakeEmptyCoverage(
                tilewidth => (SELECT (ST_MetaData(rast)).width FROM "{self.cfg.domain.case_schema}"."{self.cfg.tables.dem_or}" LIMIT 1), 
                tileheight => (SELECT (ST_MetaData(rast)).height FROM "{self.cfg.domain.case_schema}"."{self.cfg.tables.dem_or}" LIMIT 1), 
                width => (ST_XMax(g.geom) - ST_XMin(g.geom))::integer,
                height => (ST_YMax(g.geom) - ST_YMin(g.geom))::integer,
                upperleftx => ST_XMin(g.geom), 
                upperlefty => ST_YMax(g.geom), 
                scalex =>  (SELECT (ST_MetaData(rast)).scalex FROM "{self.cfg.domain.case_schema}"."{self.cfg.tables.dem_or}" LIMIT 1),
                scaley => (SELECT (ST_MetaData(rast)).scaley FROM "{self.cfg.domain.case_schema}"."{self.cfg.tables.dem_or}" LIMIT 1),
                skewx => (SELECT (ST_MetaData(rast)).skewx FROM "{self.cfg.domain.case_schema}"."{self.cfg.tables.dem_or}" LIMIT 1), 
                skewy => (SELECT (ST_MetaData(rast)).skewy FROM "{self.cfg.domain.case_schema}"."{self.cfg.tables.dem_or}" LIMIT 1),
                srid => %s
            ) AS t(rast) 
            INNER JOIN "{self.cfg.domain.case_schema}"."{self.cfg.tables.dem_or}" AS r 
                ON ST_Transform(t.rast::geometry, %s) && r.rast 
            GROUP BY t.rast;
        """

        params = (self.cfg.dem_srid, self.cfg.srid, self.cfg.srid, self.cfg.dem_srid)
        self.execute(sqltext, params)

        # 4. Finalize ownership
        self.set_table_owner(
            schema=self.cfg.domain.case_schema,
            table_name=self.cfg.tables.dem
        )

        # 5. Clean up DEM
        if self.cfg.clean_up:
            debug('Deleting original imported DEM table')
            sqltext = f'DROP TABLE "{self.cfg.domain.case_schema}"."{self.cfg.tables.dem_or}" CASCADE;'
            self.execute(sqltext)

    def run_buildings(self):
        progress('Processing buildings')
        # Refactored for self.cfg (ConfigObj) and Database execution patterns

        debug('Checking buildings raster existence in input schema')

        # Use a parameterized query to check for table existence
        check_sql = """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = %s AND table_name = %s
            )
        """
        res = self.execute(check_sql, (self.cfg.domain.case_schema, self.cfg.tables.buildings_or))
        rel_exists = res[0][0] if res else False

        if rel_exists:
            progress('Processing buildings DEM')

            # 1. Create transformed table
            debug('Create new table with transformed coordinates')
            # identifiers use f-strings; values use %s
            sql_transform = f"""
                DROP TABLE IF EXISTS "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings}" CASCADE; 

                CREATE TABLE "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings}" AS 
                SELECT ROW_NUMBER() OVER(ORDER BY t.rast::geometry) AS rid, 
                       ST_Union(ST_Clip( ST_Transform( r.rast, t.rast), t.rast::geometry ), 'MAX') AS rast 
                FROM (
                    SELECT ST_Transform(ST_SetSRID(ST_Extent(rast::geometry), %s), %s) AS geom 
                    FROM "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_or}"
                ) AS g, 
                ST_MakeEmptyCoverage(
                    tilewidth => (SELECT (ST_MetaData(rast)).width FROM "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_or}" LIMIT 1), 
                    tileheight => (SELECT (ST_MetaData(rast)).height FROM "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_or}" LIMIT 1), 
                    width => (ST_XMax(g.geom) - ST_XMin(g.geom))::integer,
                    height => (ST_YMax(g.geom) - ST_YMin(g.geom))::integer,
                    upperleftx => ST_XMin(g.geom), 
                    upperlefty => ST_YMax(g.geom), 
                    scalex => (SELECT (ST_MetaData(rast)).scalex FROM "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_or}" LIMIT 1),
                    scaley => (SELECT (ST_MetaData(rast)).scaley FROM "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_or}" LIMIT 1),
                    skewx => (SELECT (ST_MetaData(rast)).skewx FROM "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_or}" LIMIT 1), 
                    skewy => (SELECT (ST_MetaData(rast)).skewy FROM "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_or}" LIMIT 1),
                    srid => %s
                ) AS t(rast) 
                INNER JOIN "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_or}" AS r 
                    ON ST_Transform(t.rast::geometry, %s) && r.rast 
                GROUP BY t.rast;
            """
            params = (self.cfg.dem_srid, self.cfg.srid, self.cfg.srid, self.cfg.dem_srid)
            self.execute(sql_transform, params)

            # 2. Change Ownership (using the helper method)
            self.set_table_owner(self.cfg.domain.case_schema, self.cfg.tables.buildings)

            # 3. Handle rid index
            debug('Adding serial rid index')
            sql_rid = f"""
                ALTER TABLE "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings}" DROP COLUMN IF EXISTS rid; 
                ALTER TABLE "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings}" ADD COLUMN rid SERIAL;
            """
            self.execute(sql_rid)

            # 4. Cleanup
            if self.cfg.get('clean_up', False):
                debug('Cleaning up imported buildings DEM')
                sql_cleanup = f'DROP TABLE "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_or}" CASCADE;'
                self.execute(sql_cleanup)
        else:
            verbose('no buildings raster in case schema; skipping building DEM processing')