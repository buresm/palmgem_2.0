# Checking and visualizing results

## Automatic checks

Every driver is validated right after it is written (`pids.enabled: True`, default) against `config/pids_spec.yaml`: required global attributes and dimensions, coordinate variables, per-variable dimensions/types/attributes from the PALM Input Data Standard, and cross-variable consistency rules:

- **static driver** — terrain everywhere, exactly one surface type per cell, building variables on the same cells, no zero-height buildings, soil under vegetation and pavement;
- **SLURB driver** — plan fraction ≤ urban fraction, fractions within [0, 1], positive height and canyon aspect ratio, orientation in [0, 360) or fill (isotropic), missing inputs in SLUrb cells (see the [SLURB section](configuration_docs.md#slurb-single-layer-urban-model-driver)).

Findings are written to the log (`logs/<case_schema>`) as errors and warnings. `pids.strict: True` aborts the pipeline on errors. To re-check existing files without regenerating them, run the `pids_check` task.

## QA report

The `qa_report` task writes `output/<case_schema>_qa_report.html`, a single self-contained page with a map and histogram of every driver variable, the PIDS findings, landcover type shares, building statistics and the task timings of the run. Add it at the end of `run_tasks`.

## QGIS

**GeoPackage snapshot.** The `qgis_export` task writes `output/<case_schema>.gpkg` with every case-schema layer (grid, landcover, buildings, trees, SLURB centerlines, …) and embedded default styles (landcover coloured by PALM type, buildings graduated by height). Drag it into QGIS; the CRS comes with the file. Close it in QGIS before re-running the export, otherwise the locked file is skipped with a warning.

**Live database connection.** To browse the input and case schemas directly:

1. Browser panel → right-click **PostgreSQL** → **New Connection…** (or *Layer → Data Source Manager → PostgreSQL → New*).
2. Host, port, database and credentials as in your config / `.env` (e.g. `localhost`, `5432`, `palm_static`); SSL mode `disable` for a local server; Authentication *Basic*.
3. Tick *Also list tables with no geometry* and *Use estimated table metadata*, then **Test Connection** and **OK**.
4. Expand the connection, open a schema (`<input_schema>` or `<case_schema>`) and drag tables onto the map. PostGIS raster tables load the same way.

## NetCDF drivers

The driver files can be dragged into QGIS directly (choose the variable, e.g. `buildings_2d` or `street_canyon_aspect_ratio`) to see exactly what PALM will read. For a quick look outside QGIS, use standard netCDF viewers such as ncview or Panoply. With `visual_check.enabled: True` PALM-GeM also writes PNG previews to `visual_check/<case_schema>/`.
