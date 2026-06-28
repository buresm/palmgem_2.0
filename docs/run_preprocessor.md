# Data sources and preprocessing

## Downloading input data

### OpenStreetMap (OSM)

Download from [Geofabrik](https://download.geofabrik.de/europe.html) as a `.shp.zip` file for your region. Extract and use the `osm_buildings_a_free` shapefile. To speed up import, crop the shapefile to your domain extent first — see [crop shapefile in QGIS](user_preprocess.md).

### Urban Atlas (UA) landcover

Create a free account at [land.copernicus.eu](https://land.copernicus.eu/), then download the [Urban Atlas](https://land.copernicus.eu/local/urban-atlas/urban-atlas-2018?tab=download) layer for your city. Extract the archive, then convert the `.gpkg` to shapefile:

```bash
ogr2ogr -f "ESRI Shapefile" . <file_name>.gpkg
```

Crop to your domain extent before import — see [crop shapefile in QGIS](user_preprocess.md).

### EU-DEM

Download from [opentopodata.org/datasets/eudem](https://www.opentopodata.org/datasets/eudem/). Use the `N***E***` tile(s) covering your domain. Crop to extent before import — see [crop raster in QGIS](user_preprocess.md).

### Urban Atlas building height

Download from [land.copernicus.eu/local/urban-atlas/building-height-2012](https://land.copernicus.eu/local/urban-atlas/building-height-2012?tab=download) (same account as landcover). Crop to extent before import — see [crop raster in QGIS](user_preprocess.md).

### Importing into PostgreSQL

See [import2postgresql.md](import2postgresql.md) for `ogr2ogr` / `raster2pgsql` import details, or use the `gis_import` task with `data_imports.vectors` / `data_imports.rasters` in your config.

---

## Running the preprocessing tasks

Add the relevant preprocessing tasks to `run_tasks` in your config (e.g. `gis_import`, `urban_atlas_osm`, `urban_atlas_dem_buildings`), then run:

```bash
python main.py -c your_config.yaml
```

The config path is relative to the `config/` directory. Logs are written to `logs/<name><scenario>.log`. Processed tables can be inspected in QGIS — see [visualization](visualization.md).
