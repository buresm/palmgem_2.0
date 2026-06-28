# Tasks, pipeline & staged (multi-run) execution

PALM-GeM runs an ordered list of **tasks** (`run_tasks` in your config). This page lists
every task, what it reads and writes, how the tasks follow on from one another, and how to
split the work across **several separate runs** that share one database.

## How a run works

Each invocation (`python main.py -c <config>.yaml`):

1. always runs **`setup`** first (computes domain origin/projection metadata into the
   in-memory config — it creates no tables);
2. runs every task in `run_tasks` (excluding `setup`/`finalize`) in order;
3. always runs **`finalize`** last (closes the database connection).

The important property: **all data lives in PostGIS, not in process memory.** `gis_import`
writes the *input schema*; `initialize_domain` and the preprocessing tasks write the *case
schema*; the driver tasks read the case schema and write a NetCDF file. Because that state
is persisted, the pipeline can be split across as many separate runs as you like — a later
run simply reads what an earlier run left in the database.

Two schemas hold all state:

| Schema | Set by | Holds |
|--------|--------|-------|
| `input_schema` (config key) | `gis_import` | raw imported vectors/rasters (`imported_*`) |
| `case_schema` = `domain.name` + `_` + `domain.scenario` | `initialize_domain` & preprocessing | the grid and all processed per-cell tables |

## Task reference

| Task key | Class | Reads | Writes | Needs to run first |
|----------|-------|-------|--------|--------------------|
| `setup` | `SetupTask` | `domain.*`, SRIDs | in-memory config only | — (always runs) |
| `gis_import` | `GisImporter` | `data_imports.vectors/rasters` + the files | `input_schema.imported_*` | — |
| `urban_atlas_osm` | `UrbanAtlasOSM` | `input_schema` UrbanAtlas landcover (+ OSM if `process_streetmaps`) | `case_schema` landcover/fishnet/streetmap | `gis_import` |
| `urban_atlas_dem_buildings` | `UrbanAtlasDemBuildings` | DEM + building-height rasters | `case_schema` dem/buildings | `gis_import` |
| `initialize_domain` | `InitializeDomainTask` | `input_schema` tables + `surface_params_file` CSV (LOD2) | `case_schema.grid` + landcover/buildings/terrain/LSM/USM + `surface_params`; sets capability flags | `gis_import` (+ optional UA/OSM/DEM tasks) |
| `lad` | `LadGenerator` | `case_schema` trees + grid | `trees_grid` (`lad_*`/`bad_*` columns) | `initialize_domain` |
| `lai` | `LaiGenerator` | `case_schema` grid + LAI/canopy rasters | `lai`/`canopy_height` columns on grid | `initialize_domain` (+ imported LAI/canopy rasters) |
| `prepare_slurb` | `PrepareSlurbInputs` | `case_schema` landcover + buildings | centreline / `building_area` tables | `initialize_domain` |
| `cct_processing` | `CctProcessing` | `case_schema` grid/landcover/buildings | slanted faces/vertices tables | `initialize_domain` (needs `do_cct: True`) |
| `static_driver` | `StaticDriverGen` | `case_schema.grid` + parameter tables in config | `output/<case>_static.nc` | `initialize_domain` (+ `lad`/`lai` if you want trees) |
| `slurb_driver` | `SlurbDriverGen` | `case_schema` grid + SLURB inputs | `output/<case>_slurb.nc` | `prepare_slurb` (needs `slurb: True`) |
| `cct_driver` | `CCTDriverGen` | slanted-face tables | slanted NetCDF | `cct_processing` |
| `finalize` | `FinalizeTask` | — | — | — (always runs) |

> The driver tasks (`static_driver`, `slurb_driver`, `cct_processing`/`cct_driver`) depend on
> a few **capability flags** (`has_buildings`, `has_3d_buildings`, `has_surface_params`,
> `lod2`) that `initialize_domain` normally derives in memory. When a driver task is run on
> its own — i.e. in a *separate process* from `initialize_domain` — those flags are rebuilt
> automatically from the persisted `case_schema` (see `src/utils/capabilities.py`), so the
> task runs independently. No extra configuration is needed.

## Config keys that must match across runs

When you split work across runs, the following keys **must be identical** in every config
file so that later runs target the schemas/grid that earlier runs created:

- `database.*` — the same PostgreSQL database.
- `input_schema` — where `gis_import` put the raw data.
- `domain.name` and `domain.scenario` — together they form `case_schema`; change either and
  you point at a *different* processed schema.
- `domain.dx/dy/nx/ny/cent_x/cent_y` and the SRIDs (`srid`, `srid_palm`, `srid_utm`,
  `srid_wgs84`, `dem_srid`) — these define the grid; changing them means the grid must be
  rebuilt (`initialize_domain`).
- `tables.*` — the table-name mapping.

The simplest approach is to keep one shared base config and only vary `run_tasks` (and, for
parameter studies, the parameter sections and the output filename) between runs.

## Recipe A — three configs, one NetCDF (staged build)

Split the build into import → prepare → emit. All three configs share `database`,
`input_schema`, `domain` and SRIDs; only `run_tasks` differs.

```yaml
# 1_import.yaml      — import + preprocess raw GIS into the input schema
run_tasks: [gis_import, urban_atlas_osm, urban_atlas_dem_buildings]

# 2_prepare.yaml     — build the domain grid and all per-cell processing
run_tasks: [initialize_domain, lad]      # add lai / prepare_slurb / cct_processing as needed

# 3_driver.yaml      — write the static driver from the prepared grid
run_tasks: [static_driver]
```

```bash
python main.py -c 1_import.yaml
python main.py -c 2_prepare.yaml
python main.py -c 3_driver.yaml
```

Each run reconnects, reads the schema state left by the previous run, and adds to it.

## Recipe B — populate once, many parameterisations

Build the schema once, then run `static_driver` repeatedly with different parameter sets to
emit several NetCDFs from the **same** grid. Keep `domain.name`/`scenario` (hence
`case_schema`) identical so the populated grid is reused, and override
`domain.static_driver_file` in each parameter config so the outputs don't overwrite each
other:

```yaml
# base populate run
run_tasks: [gis_import, urban_atlas_osm, urban_atlas_dem_buildings, initialize_domain, lad]

# variant_a.yaml  (same case_schema, different parameters)
run_tasks: [static_driver]
domain:
  static_driver_file: 'output/prague_variantA_static.nc'
# ... variant-A LSM/USM/albedo parameters ...

# variant_b.yaml
run_tasks: [static_driver]
domain:
  static_driver_file: 'output/prague_variantB_static.nc'
# ... variant-B parameters ...
```

```bash
python main.py -c base.yaml
python main.py -c variant_a.yaml
python main.py -c variant_b.yaml
```

Because `static_driver` re-derives the capability flags from the database and reads the grid
fresh each time, the variant runs need nothing from the populate run beyond the persisted
`case_schema`.

## Notes & caveats

- A driver run still needs whatever it intends to write to already exist in the grid. For
  example, run `lad`/`lai` before a `static_driver` run that should contain tree data; run
  `prepare_slurb` (and set `slurb: True`) before `slurb_driver`.
- `static_driver_file` (and `slurb_driver_file`) default to `output/<case_schema>_static.nc`.
  Override them per run to keep parameter variants side by side.
- Running everything in one config (`run_tasks: [gis_import, setup, initialize_domain,
  static_driver, finalize]`) still works exactly as before — staging is optional.
