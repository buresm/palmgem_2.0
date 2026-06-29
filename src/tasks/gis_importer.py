# src/tasks/prepare.py
from .base import BaseTask
from src.utils.linux_cmds import ShapefileImporter, RasterImporter
from src.logger import progress, debug, warning, verbose, error
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
            alter schema {self.cfg.input_schema} owner to {self.cfg.pg_owner};
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
            # ensure column names are standardized for PALM-GeM requirements
            self.rename_columns(table)

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

    def rename_columns(self, table_name):
        """
        standardize input column names per table during import.

        For each imported vector table, ``cfg.attribute_mapping.<table>`` gives
        a one-to-one ``{standard_name: source_name}`` map (default identity).
        When the source column is present it is renamed to the standard name.
        Requiredness is governed by ``cfg.attribute_spec.<table>.necessary``:
        a missing *necessary* attribute aborts the import (hard error); any
        other missing attribute only warns (soft). The check runs only for
        tables that are being imported, so level-of-detail
        tables that are simply absent never trigger a failure.
        """
        progress('standardizing table columns (source names -> standard names)')

        mapping = self.cfg.attribute_mapping
        spec = self.cfg.get('attribute_spec', None)

        # iterate by logical table name (landcover, walls, ...) and resolve to
        # the actual table name via the tables: section.
        for table_key in mapping._settings.keys():
            actual_table = self.cfg.tables.get(table_key, table_key)
            if not actual_table == table_name:
                debug(f'skipping {table_key}: not among imported tables')
                continue

            debug(f'checking table: {actual_table}')

            # necessary attributes for this table (everything else is soft)
            necessary = []
            if spec is not None and table_key in spec._settings:
                necessary = spec._settings[table_key].get('necessary', []) or []

            # fetch existing columns once to avoid repeated information_schema queries
            sql_cols = """
                select column_name
                from information_schema.columns
                where table_schema = %s and table_name = %s
            """
            res = self.execute(sql_cols, (self.cfg.input_schema, actual_table))
            existing_cols = [r[0] for r in res]

            table_map = mapping._settings[table_key]
            for standard_name, source_name in table_map._settings.items():
                # already standardized -> nothing to do
                if standard_name in existing_cols:
                    continue

                if source_name in existing_cols:
                    verbose(f'renaming column in {actual_table}: {source_name} -> {standard_name}')
                    sql_rename = f"""
                        alter table "{self.cfg.input_schema}"."{actual_table}"
                        rename column {source_name} to {standard_name}
                    """
                    try:
                        self.execute(sql_rename)
                        existing_cols.remove(source_name)
                        existing_cols.append(standard_name)
                    except Exception as e:
                        # a failed rename of a necessary attribute is fatal
                        if standard_name in necessary:
                            error(f'failed to rename necessary attribute {source_name} -> '
                                  f'{standard_name} in {actual_table}: {e}')
                            raise
                        error(f'failed to rename {source_name} -> {standard_name} in {actual_table}: {e}')
                    continue

                # neither standard nor source column present
                if standard_name in necessary:
                    msg = (f"required attribute '{standard_name}' not found in table "
                           f"'{actual_table}' (looked for source column '{source_name}'). "
                           f"Set attribute_mapping.{table_key}.{standard_name} to the "
                           f"matching column name in your data.")
                    error(msg)
                    raise ValueError(msg)
                else:
                    warning(f"optional attribute '{standard_name}' not found in table "
                            f"'{actual_table}' (source column '{source_name}'); skipping")

        progress('column standardization complete')