# Prague example

Follow [preprocessor documentation](../../docs/run_preprocessor.md) for the full workflow.

## Steps

1. Download Prague from **OpenStreetMap**. Use the [QGIS procedure](../../docs/user_preprocess.md) to clip to the area of interest.
2. Download Prague from **UrbanAtlas**. Use the [QGIS procedure](../../docs/user_preprocess.md) to clip unnecessary polygons.
3. Download a **EU-DEM** tile covering Prague. Use the [QGIS procedure](../../docs/user_preprocess.md) to clip the raster to the area of interest.
4. Download the **UrbanAtlas building height** raster for Prague. Clip as above.
5. Import the downloaded files into the `inputs_prague` schema as `imported_landcover` (UrbanAtlas), `imported_streetmap` (OSM buildings), `imported_dem` and `imported_buildings`: either put `gis_import` first in `run_tasks` of [prague.yaml](prague.yaml) with a `data_imports` section (see [import guide](../../docs/import2postgresql.md)), or adapt the Brno script [import_pgsql_brno.sh](../brno/import_pgsql_brno.sh) (same tables; change `schema` and the file paths).
6. Set database credentials in `.env` (copy from `.env.example`) or directly in [prague.yaml](prague.yaml). Review domain extent settings in [prague.yaml](prague.yaml).
7. Run the preprocessing (`urban_atlas_osm` merges UrbanAtlas + OSM footprints, `urban_atlas_dem_buildings` processes the rasters; results stay in the `inputs_prague` schema): `python main.py -c examples/prague/prague.yaml` — check the log in `logs/inputs_prague`.
8. Inspect the imported data in QGIS — see [visualization guide](../../docs/visualization.md).
9. Review the static driver config [prague_palm.yaml](prague_palm.yaml) (`initialize_domain` + `static_driver`) and run: `python main.py -c examples/prague/prague_palm.yaml` — the driver is `output/prague_static.nc`, the log `logs/prague`.
10. Check the PIDS findings in the log and the output in QGIS (see [checking results](../../docs/visualization.md)); add `qa_report` to `run_tasks` for an HTML report.

> The input data is not shipped; these configurations follow the PALM-GeM 2.0 task layout but have not been re-run end to end with the city data since the 2.0 migration. The [Prague LOD2 example](../prague_lod2/prague_lod2.md) is the self-contained, verified one.
