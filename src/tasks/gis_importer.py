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
        for vec in vectors:
            debug(f'Creating vector {vec}')
            path = self.cfg.data_imports.vectors[vec]['path']
            table = self.cfg.data_imports.vectors[vec]['table']
            srid = self.cfg.data_imports.vectors[vec]['srid']
            ogr2ogr_exe = self.cfg.ogr2ogr_path
            if os.path.exists(path):
                shp_tool.import_shp(
                    file_path=path,
                    schema_name=self.cfg.input_schema,
                    table_name=table,
                    srid=srid,
                    ogr2ogr_exe=ogr2ogr_exe,
                )
            else:
                warning(f"File not found: path={path}")

        # 3. Process all Rasters
        rasters = dict(self.cfg.data_imports.rasters._settings)
        for rast in rasters:
            debug(f'Creating raster {rast}')
            path = self.cfg.data_imports.rasters[rast]['path']
            table = self.cfg.data_imports.rasters[rast]['table']
            srid = self.cfg.data_imports.rasters[rast]['srid']
            psql = self.cfg.psql_path
            raster2psql = self.cfg.raster2psql_path
            if os.path.exists(path):
                debug(f"Importing raster: {path}")
                rast_tool.import_tiff(
                    file_path=path,
                    schema_name=self.cfg.input_schema,
                    table_name=table,
                    srid=srid,
                    psql=psql,
                    raster2psql=raster2psql
                )
            else:
                warning(f"File not found: {path}")

        debug("Geospatial data ingestion complete.")
