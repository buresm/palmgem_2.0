# Running the static driver generator

Before the first run, load the custom SQL functions into your PostgreSQL database — see [Installation](install.md).

Create a configuration YAML in `config/` (see the [example configurations](../examples/) and the [configuration reference](configuration_docs.md)) with your database connection, domain definition (center, resolution, extent), and the tasks to run in `run_tasks` (typically ending with `initialize_domain`, `static_driver`, and any of `lad`/`lai`/`cct_driver`/`slurb_driver`).

Run:

```bash
python main.py -c your_config.yaml
```

Progress is written to `logs/<name><scenario>.log`. If `visual_check.enabled` is set, PNG previews of the generated static driver are written to `visual_check/`. The static driver NetCDF itself is written to `output/`. You can also inspect the PostGIS grid tables directly in QGIS — see [visualization](visualization.md).
