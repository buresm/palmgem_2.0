# src/tasks/prepare.py
from .base import BaseTask
from src.utils.linux_cmds import ShapefileImporter, RasterImporter
from src.logger import progress, debug, warning
import os
import pandas as pd

class GisImporter(BaseTask):
    def run(self):
        # 1. Initialize our specialized tools
        shp_tool = ShapefileImporter(self.cfg.database._settings)
        rast_tool = RasterImporter(self.cfg.database._settings)

        # Check existence of target schema, else create
        debug('Creating schema if not exists')
        self.execute(f"""
            create schema if not exists {self.cfg.input_schema};
            alter schema {self.cfg.input_schema} owner to {self.cfg.database.user};
        """)

        os.environ.pop("PROJ_LIB", None)
        os.environ.pop("PROJ_DATA", None)

        # 2. Process all Vectors
        vectors = dict(self.cfg.data_imports.vectors._settings)
        rasters = dict(self.cfg.data_imports.rasters._settings)
        progress("importing {} vector(s) and {} raster(s) into schema '{}'",
                 len(vectors), len(rasters), self.cfg.input_schema)

        for vec in vectors:
            path = self.cfg.data_imports.vectors[vec]['path']
            table = self.cfg.data_imports.vectors[vec]['table']
            srid = self.cfg.data_imports.vectors[vec]['srid']
            ogr2ogr_exe = self.cfg.ogr2ogr_path
            if not os.path.exists(path):
                warning(f"vector '{vec}' source not found, skipping: {path}")
                continue
            progress("importing vector '{}' -> {}.{}", vec, self.cfg.input_schema, table)
            debug(f"source {path} (srid {srid})")
            try:
                shp_tool.import_shp(
                    file_path=path,
                    schema_name=self.cfg.input_schema,
                    table_name=table,
                    srid=srid,
                    ogr2ogr_exe=ogr2ogr_exe,
                    idx=self.cfg.idx[table]
                )
            except RuntimeError as e:
                # ogr2ogr may exit non-zero on benign loader warnings (e.g.
                # "libpq.so.5: no version information available") while still
                # importing the table. Don't crash on the message alone — the
                # DB check below is the source of truth.
                warning(f"ogr2ogr reported an issue importing '{table}': {e}")
            self._verify_imported(self.cfg.input_schema, table)

        # 3. Process all Rasters
        for rast in rasters:
            path = self.cfg.data_imports.rasters[rast]['path']
            table = self.cfg.data_imports.rasters[rast]['table']
            srid = self.cfg.data_imports.rasters[rast]['srid']
            psql = self.cfg.psql_path
            raster2psql = self.cfg.raster2psql_path
            if not os.path.exists(path):
                warning(f"raster '{rast}' source not found, skipping: {path}")
                continue
            progress("importing raster '{}' -> {}.{}", rast, self.cfg.input_schema, table)
            debug(f"source {path} (srid {srid})")
            try:
                rast_tool.import_tiff(
                    file_path=path,
                    schema_name=self.cfg.input_schema,
                    table_name=table,
                    srid=srid,
                    psql=psql,
                    raster2psql=raster2psql
                )
            except RuntimeError as e:
                # Same tolerance as vectors: confirm against the DB rather than
                # aborting purely on a non-zero subprocess exit / loader warning.
                warning(f"raster import reported an issue for '{table}': {e}")
            self._verify_imported(self.cfg.input_schema, table)

        progress("gis import complete")

    def _verify_imported(self, schema, table):
        """Confirm a table was actually created and populated in PostgreSQL.

        Used as the source of truth after an importer subprocess, so a benign
        non-zero exit (e.g. a dynamic-loader warning) does not abort the run
        when the data is in fact present. Raises only when the table is genuinely
        missing; an empty table is warned about but allowed through.
        """
        exists = self.fetchone(
            "select exists(select 1 from information_schema.tables "
            "where table_schema = %s and table_name = %s)",
            (schema, table))
        if not exists:
            raise RuntimeError(
                f"Import failed: table {schema}.{table} was not created")

        rows = self.fetchone(f'select count(*) from "{schema}"."{table}"')
        if not rows:
            warning(f"Imported table {schema}.{table} exists but is empty (0 rows)")
        else:
            debug(f"verified {schema}.{table} imported ({rows} rows)")
