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
                schema=self.cfg.input_schema,
                table=self.cfg.tables.im_landcover_or,
                srid=self.cfg.srid,
            )
        self.run_dem()
        self.run_buildings()

    def run_dem(self):
        progress('Processing DEM')

        schema = self.cfg.input_schema
        dem_or = self.cfg.tables.dem_or

        # 1. Ensure the raster SRID matches dem_srid.
        # UpdateRasterSRID drops and rebuilds the raster constraints; when the
        # SRID is already set (e.g. raster2pgsql ran with -s/-C) there is nothing
        # to drop and PostGIS raises "None of the constraints specified could be
        # dropped". Skip the update when the SRID is already correct.
        current_srid = self.fetchone(
            f'SELECT ST_SRID(rast) FROM "{schema}"."{dem_or}" LIMIT 1')
        if current_srid == self.cfg.dem_srid:
            debug(f'DEM raster SRID already {self.cfg.dem_srid}; skipping UpdateRasterSRID')
        else:
            debug(f'updating DEM raster SRID {current_srid} -> {self.cfg.dem_srid}')
            self.execute("SELECT UpdateRasterSRID(%s, %s, %s, %s)",
                         (schema, dem_or, 'rast', self.cfg.dem_srid))

        # 2. Clip entries outside the envelope
        debug('Delete all entries from DEM imported table that are outside envelope')
        sqltext = f"""
            DELETE FROM "{self.cfg.input_schema}"."{self.cfg.tables.dem_or}" 
            WHERE NOT ST_Intersects(ST_Transform(%s::geometry, %s), rast)
        """
        self.execute(sqltext, (self.cfg.envelope, self.cfg.dem_srid))

        # guard: if the clip removed every tile (the DEM does not overlap the
        # domain) the table is now empty, and ST_Extent/ST_MetaData below return
        # NULL — which surfaces deep inside ST_MakeEmptyCoverage as the opaque
        # "upper bound of FOR loop cannot be null". Fail with an actionable
        # message instead.
        remaining = self.fetchone(
            f'SELECT count(*) FROM "{schema}"."{dem_or}"')
        if not remaining:
            raise RuntimeError(
                f'no DEM tiles remain in "{schema}"."{dem_or}" after the envelope '
                f'clip: the DEM does not overlap the domain. Check that dem_srid '
                f'({self.cfg.dem_srid}) matches the DEM, that srid ({self.cfg.srid}) '
                f'and the domain centre/extent are correct, and that the DEM covers '
                f'the domain.')
        debug(f'{remaining} DEM tile(s) intersect the domain envelope')

        # 3. Transform coordinates and create new DEM table
        debug('Create new table with transformed coordinates')
        # We use f-strings for the structural parts and %s for the values
        sqltext = f"""
            DROP TABLE IF EXISTS "{self.cfg.input_schema}"."{self.cfg.tables.dem}"; 

            CREATE TABLE "{self.cfg.input_schema}"."{self.cfg.tables.dem}" AS 
            SELECT ROW_NUMBER() OVER(ORDER BY t.rast::geometry) AS rid, 
                   ST_Union(ST_Clip( ST_Transform( r.rast, t.rast), t.rast::geometry ), 'MAX') AS rast 
            FROM (
                SELECT ST_Transform(ST_SetSRID(ST_Extent(rast::geometry), %s), %s) AS geom 
                FROM "{self.cfg.input_schema}"."{self.cfg.tables.dem_or}"
            ) AS g, 
            ST_MakeEmptyCoverage(
                tilewidth => (SELECT (ST_MetaData(rast)).width FROM "{self.cfg.input_schema}"."{self.cfg.tables.dem_or}" LIMIT 1), 
                tileheight => (SELECT (ST_MetaData(rast)).height FROM "{self.cfg.input_schema}"."{self.cfg.tables.dem_or}" LIMIT 1), 
                width => (ST_XMax(g.geom) - ST_XMin(g.geom))::integer,
                height => (ST_YMax(g.geom) - ST_YMin(g.geom))::integer,
                upperleftx => ST_XMin(g.geom), 
                upperlefty => ST_YMax(g.geom), 
                scalex =>  (SELECT (ST_MetaData(rast)).scalex FROM "{self.cfg.input_schema}"."{self.cfg.tables.dem_or}" LIMIT 1),
                scaley => (SELECT (ST_MetaData(rast)).scaley FROM "{self.cfg.input_schema}"."{self.cfg.tables.dem_or}" LIMIT 1),
                skewx => (SELECT (ST_MetaData(rast)).skewx FROM "{self.cfg.input_schema}"."{self.cfg.tables.dem_or}" LIMIT 1), 
                skewy => (SELECT (ST_MetaData(rast)).skewy FROM "{self.cfg.input_schema}"."{self.cfg.tables.dem_or}" LIMIT 1),
                srid => %s
            ) AS t(rast) 
            INNER JOIN "{self.cfg.input_schema}"."{self.cfg.tables.dem_or}" AS r 
                ON ST_Transform(t.rast::geometry, %s) && r.rast 
            GROUP BY t.rast;
        """

        params = (self.cfg.dem_srid, self.cfg.srid, self.cfg.srid, self.cfg.dem_srid)
        self.execute(sqltext, params)

        # 4. Finalize ownership
        self.set_table_owner(
            schema=self.cfg.input_schema,
            table_name=self.cfg.tables.dem
        )

        # 5. Clean up DEM
        if self.cfg.clean_up:
            debug('Deleting original imported DEM table')
            sqltext = f'DROP TABLE "{self.cfg.input_schema}"."{self.cfg.tables.dem_or}" CASCADE;'
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
        res = self.execute(check_sql, (self.cfg.input_schema, self.cfg.tables.buildings_or))
        rel_exists = res[0][0] if res else False

        if rel_exists:
            progress('Processing buildings DEM')

            # 1. Create transformed table
            debug('Create new table with transformed coordinates')
            # identifiers use f-strings; values use %s
            sql_transform = f"""
                DROP TABLE IF EXISTS "{self.cfg.input_schema}"."{self.cfg.tables.buildings}" CASCADE; 

                CREATE TABLE "{self.cfg.input_schema}"."{self.cfg.tables.buildings}" AS 
                SELECT ROW_NUMBER() OVER(ORDER BY t.rast::geometry) AS rid, 
                       ST_Union(ST_Clip( ST_Transform( r.rast, t.rast), t.rast::geometry ), 'MAX') AS rast 
                FROM (
                    SELECT ST_Transform(ST_SetSRID(ST_Extent(rast::geometry), %s), %s) AS geom 
                    FROM "{self.cfg.input_schema}"."{self.cfg.tables.buildings_or}"
                ) AS g, 
                ST_MakeEmptyCoverage(
                    tilewidth => (SELECT (ST_MetaData(rast)).width FROM "{self.cfg.input_schema}"."{self.cfg.tables.buildings_or}" LIMIT 1), 
                    tileheight => (SELECT (ST_MetaData(rast)).height FROM "{self.cfg.input_schema}"."{self.cfg.tables.buildings_or}" LIMIT 1), 
                    width => (ST_XMax(g.geom) - ST_XMin(g.geom))::integer,
                    height => (ST_YMax(g.geom) - ST_YMin(g.geom))::integer,
                    upperleftx => ST_XMin(g.geom), 
                    upperlefty => ST_YMax(g.geom), 
                    scalex => (SELECT (ST_MetaData(rast)).scalex FROM "{self.cfg.input_schema}"."{self.cfg.tables.buildings_or}" LIMIT 1),
                    scaley => (SELECT (ST_MetaData(rast)).scaley FROM "{self.cfg.input_schema}"."{self.cfg.tables.buildings_or}" LIMIT 1),
                    skewx => (SELECT (ST_MetaData(rast)).skewx FROM "{self.cfg.input_schema}"."{self.cfg.tables.buildings_or}" LIMIT 1), 
                    skewy => (SELECT (ST_MetaData(rast)).skewy FROM "{self.cfg.input_schema}"."{self.cfg.tables.buildings_or}" LIMIT 1),
                    srid => %s
                ) AS t(rast) 
                INNER JOIN "{self.cfg.input_schema}"."{self.cfg.tables.buildings_or}" AS r 
                    ON ST_Transform(t.rast::geometry, %s) && r.rast 
                GROUP BY t.rast;
            """
            params = (self.cfg.dem_srid, self.cfg.srid, self.cfg.srid, self.cfg.dem_srid)
            self.execute(sql_transform, params)

            # 2. Change Ownership (using the helper method)
            self.set_table_owner(self.cfg.input_schema, self.cfg.tables.buildings)

            # 3. Handle rid index
            debug('Adding serial rid index')
            sql_rid = f"""
                ALTER TABLE "{self.cfg.input_schema}"."{self.cfg.tables.buildings}" DROP COLUMN IF EXISTS rid; 
                ALTER TABLE "{self.cfg.input_schema}"."{self.cfg.tables.buildings}" ADD COLUMN rid SERIAL;
            """
            self.execute(sql_rid)

            # 4. Cleanup
            if self.cfg.get('clean_up', False):
                debug('Cleaning up imported buildings DEM')
                sql_cleanup = f'DROP TABLE "{self.cfg.input_schema}"."{self.cfg.tables.buildings_or}" CASCADE;'
                self.execute(sql_cleanup)
        else:
            verbose('no buildings raster in case schema; skipping building DEM processing')