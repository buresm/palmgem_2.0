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

        # 3. Mosaic the in-domain source tiles into one continuous raster, then
        # reproject once. The previous approach reprojected each source tile
        # independently and re-tiled it via ST_MakeEmptyCoverage, which left thin
        # NODATA seams (regular horizontal/vertical missing lines) at every tile
        # boundary: edge resampling needs the neighbouring tile's pixels, which
        # were not part of the per-tile join. raster2pgsql tiles are adjacent and
        # non-overlapping, so ST_Union stitches them seamlessly before transform.
        debug('Create new DEM table (mosaic source tiles, then reproject once)')
        sqltext = f"""
            DROP TABLE IF EXISTS "{schema}"."{self.cfg.tables.dem}";

            CREATE TABLE "{schema}"."{self.cfg.tables.dem}" AS
            SELECT 1 AS rid,
                   ST_Transform(ST_Union(rast), %s) AS rast
            FROM "{schema}"."{dem_or}";
        """
        self.execute(sqltext, (self.cfg.srid,))

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

            # 1. Mosaic the source tiles into one continuous raster, then
            # reproject once. Per-tile reproject + retile (the old
            # ST_MakeEmptyCoverage approach) left NODATA seams at tile boundaries;
            # see run_dem for the full explanation.
            debug('Create new buildings table (mosaic source tiles, then reproject once)')
            sql_transform = f"""
                DROP TABLE IF EXISTS "{self.cfg.input_schema}"."{self.cfg.tables.buildings}" CASCADE;

                CREATE TABLE "{self.cfg.input_schema}"."{self.cfg.tables.buildings}" AS
                SELECT 1 AS rid,
                       ST_Transform(ST_Union(rast), %s) AS rast
                FROM "{self.cfg.input_schema}"."{self.cfg.tables.buildings_or}";
            """
            self.execute(sql_transform, (self.cfg.srid,))

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