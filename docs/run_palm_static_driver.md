# Running the static driver generator

Before the first run, load the custom SQL functions into your PostgreSQL database — see [Installation](install.md#load-sql-functions).

Create a configuration YAML (see the [example configurations](../examples/) and the [configuration reference](configuration_docs.md)) with your database connection, domain definition (center, resolution, extent), the SRIDs of your UTM zone, and the tasks to run in `run_tasks`. A typical list is `initialize_domain`, optionally `lad` / `lai` for trees, then `static_driver`; add `prepare_slurb` (before `initialize_domain`) and `slurb_driver` for a SLURB case (`slurb: True`), or `cct_processing` and `cct_driver` for cut-cell topography.

> **Set the SRIDs.** The shipped defaults are UTM zone 32N (`srid`, `srid_input`, `srid_palm`, `srid_utm`: 32632). A domain in another zone (e.g. Czech Republic, Berlin: zone 33N, 32633) needs all four set, otherwise the grid is built in the wrong zone and no input data intersects it.

Run:

```bash
python main.py -c your_config.yaml
```

The static driver NetCDF is written to `output/<case_schema>_static.nc` (`case_schema` = `<domain.name>_<domain.scenario>`), the log of the last run to `logs/<case_schema>`. Right after writing, the driver is checked against the PALM Input Data Standard and cross-variable consistency rules; the findings are in the log. If `visual_check.enabled` is set, PNG previews are written to `visual_check/<case_schema>/`. Add the `qa_report` task for an HTML report of the driver, and `qgis_export` for a styled GeoPackage of the case — see [checking and visualizing results](visualization.md).

The driver tasks can also run on their own in a later run, reading the grid an earlier run left in the database (e.g. to emit several parameter variants) — see [tasks.md](tasks.md).
