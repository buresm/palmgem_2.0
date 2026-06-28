# Import datasets to PostgreSQL

GIS data is imported into PostGIS by the `gis_import` task (`GisImporter`), which wraps `ogr2ogr` (vectors) and `raster2pgsql` + `psql` (rasters). Add `gis_import` to `run_tasks` in your config.

List files to import under `data_imports` in your config YAML — `vectors` and `rasters` are dictionaries keyed by an arbitrary name:

```yaml
data_imports:
  vectors:
    landcover:
      path: 'path/to/landcover.shp'
      table: 'imported_landcover'
      srid: 32633
    osm_buildings:
      path: 'path/to/osm_buildings_a_free.shp'
      table: 'imported_buildings'
      srid: 32633
  rasters:
    dem:
      path: 'path/to/dem.tif'
      table: 'imported_dem'
      srid: 3035
```

Tool paths (`ogr2ogr_path`, `raster2psql_path`, `psql_path`) must be set — see [Installation](install.md). Tables are created in `input_schema`. If the source file is not found at `path`, that entry is skipped with a warning.

After import, inspect the loaded geometries in QGIS — see [visualization](visualization.md).
