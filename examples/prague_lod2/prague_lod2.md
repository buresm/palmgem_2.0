# Prague city-centre — LOD2 example

A small, fully featured **LOD2** test case: a 500 × 400 m patch of the Prague
(Czech Republic) city centre at **1 m** resolution, with detailed 3D buildings,
vertical walls, roofs, individual trees and surface physics.

Everything needed to produce a PALM static driver is in this folder — the GIS
sources, a ready-to-run configuration, and (optionally) a manual import script.

## What's in the dataset (`files/`)

| File | Type | Contents |
|------|------|----------|
| `landcover.shp` | vector | Land-cover polygons with `katland` surface code (→ `catland`) |
| `roofs.shp` | vector | Roof footprints (material, thickness `tloustka`) |
| `walls.shp` | vector | Vertical wall lines, lower/upper parameters (`stenakatd/stenakath`, …) |
| `trees.shp` | vector | Individual trees (height `vysstr`, crown/trunk geometry) |
| `extras_shp.shp` | vector | 3D-building extras (includes a bridge) |
| `dem.tif` | raster | Terrain elevation, 1 m |
| `buildings.tif` | raster | Building elevation model, 1 m |
| `extras.tif` | raster | 3D-building raster |
| `surface_params.csv` | table | Surface physical constants (reference copy of `config/surface_params.csv`) |

All layers are projected to **EPSG:32633** (UTM zone 33N), DEM included.

## Prerequisites

- PostgreSQL + PostGIS (native or the repo `docker-compose.yml`) — see
  [docs/install.md](../../docs/install.md).
- GDAL/OGR (`ogr2ogr`), `raster2pgsql` and `psql` on your `PATH`
  (or set full paths at the bottom of the config on Windows).
- Python dependencies: `pip install -r requirements.txt`.

## Run it

1. **Configure the database.** Edit the `database:` block (and `pg_owner`) at the
   top of [`prague_lod2.yaml`](prague_lod2.yaml) to match your PostgreSQL.

2. **Run the pipeline from the repository root:**

   ```bash
   python main.py -c ../examples/prague_lod2/prague_lod2.yaml
   ```

   The `-c` path is resolved relative to the `config/` directory, so `../` steps
   back out to this example. The configured `run_tasks` will:

   | task | does |
   |------|------|
   | `gis_import` | load the vectors/rasters above into the `inputs_prague_lod2` schema |
   | `initialize_domain` | build the grid; **LOD2 auto-enables** (roofs + walls + `catland` + surface params) |
   | `lad` | grid the trees into leaf-area density |
   | `static_driver` | write the NetCDF static driver |

3. **Output:** `output/prague_lod2_static.nc`. Visual checks (enabled in the
   config) are written to `visual_check/prague_lod2/`, logs to
   `logs/prague_lod2/`.

That's it — no manual SQL import or attribute renaming is required; the config
maps this dataset's legacy column names to the standard names and points
`initialize_domain` at the shipped `config/surface_params.csv`.

## Notes

- **Surface parameters** are loaded automatically from `config/surface_params.csv`.
  The identical `files/surface_params.csv` is kept here only for reference. To
  customise them, set `surface_params_file:` in the config.
- **Manual import (optional).** [`import_pgsql_prague_lod2.sh`](import_pgsql_prague_lod2.sh)
  imports the same layers with `ogr2ogr`/`raster2pgsql` directly. It is **not
  needed** when you run the `gis_import` task above; it is provided only for users
  who prefer to populate the input schema by hand (edit its connection variables
  first).
- **Resolution / domain.** 1 m `dx/dy/dz`, `nx=500`, `ny=400`, centred at
  (460198, 5546223). Adjust in the config to crop or move the domain.
