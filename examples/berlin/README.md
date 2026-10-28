# Berlin example

Follow [preprocessor documentation](../../docs/run_preprocessor.md) for the full workflow.

## Steps

1. Download Berlin from **OpenStreetMap**. Use the [QGIS procedure](../../docs/user_preprocess.md) to clip to the area of interest.
2. Download Berlin from **UrbanAtlas**. Use the [QGIS procedure](../../docs/user_preprocess.md) to clip unnecessary polygons.
3. Download a **EU-DEM** tile covering Berlin. Use the [QGIS procedure](../../docs/user_preprocess.md) to clip the raster to the area of interest.
4. Download the **UrbanAtlas building height** raster for Berlin. Clip as above.
5. Configure the import script [import_pgsql_berlin.sh](import_pgsql_berlin.sh) with the correct paths to your downloaded files.
6. Set database credentials in `.env` (copy from `.env.example`) or directly in [berlin.yaml](berlin.yaml). Review domain extent settings in [berlin.yaml](berlin.yaml).
7. Run the preprocessing (`urban_atlas_osm` merges UrbanAtlas + OSM footprints, `urban_atlas_dem_buildings` processes the rasters; results stay in the `inputs_berlin` schema): `python main.py -c examples/berlin/berlin.yaml` — check the log in `logs/inputs_berlin`.
8. Inspect the imported data in QGIS — see [visualization guide](../../docs/visualization.md).
9. Review the static driver config [berlin_palm.yaml](berlin_palm.yaml) (`initialize_domain` + `static_driver`) and run: `python main.py -c examples/berlin/berlin_palm.yaml` — the driver is `output/berlin_static.nc`, the log `logs/berlin`.
10. Check the PIDS findings in the log and the output in QGIS (see [checking results](../../docs/visualization.md)); add `qa_report` to `run_tasks` for an HTML report.

> The input data is not shipped; these configurations follow the PALM-GeM 2.0 task layout but have not been re-run end to end with the city data since the 2.0 migration. The [Prague LOD2 example](../prague_lod2/prague_lod2.md) is the self-contained, verified one.
