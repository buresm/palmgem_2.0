# Brno example

Follow [preprocessor documentation](../../docs/run_preprocessor.md) for the full workflow.

## Steps

1. Download Brno from **OpenStreetMap**. Use the [QGIS procedure](../../docs/user_preprocess.md) to clip to the area of interest.
2. Download Brno from **UrbanAtlas**. Use the [QGIS procedure](../../docs/user_preprocess.md) to clip unnecessary polygons.
3. Download a **EU-DEM** tile covering Brno. Use the [QGIS procedure](../../docs/user_preprocess.md) to clip the raster to the area of interest.
4. Download the **UrbanAtlas building height** raster for Brno. Clip as above.
5. Configure the import script [import_pgsql_brno.sh](import_pgsql_brno.sh) with the correct paths to your downloaded files.
6. Set database credentials in `.env` (copy from `.env.example`) or directly in [brno.yaml](brno.yaml). Review domain extent settings in [brno.yaml](brno.yaml).
7. Run the GIS import: `python main.py -c examples/brno/brno.yaml` — check the log in `logs/`.
8. Inspect the imported data in QGIS — see [visualization guide](../../docs/visualization.md).
9. Review the static driver config [brno_palm.yaml](brno_palm.yaml) and run: `python main.py -c examples/brno/brno_palm.yaml`
10. Check output in QGIS, `visual_check/brno/`, and `output/`.
