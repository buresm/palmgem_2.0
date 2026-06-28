# Leaf Area Density (LAD)

PALM-GeM supports two approaches for deriving leaf area density (LAD), selected via `canopy.using_lai`:

- **Individual tree LAD** (default, `canopy.using_lai: False`) — gridding of point tree data via the `lad` task (`LadGenerator`). See [tree processing](tree.md) for details.
- **Raster LAI / canopy height** (`canopy.using_lai: True`) — the `lai` task (`LaiGenerator`) intersects the PALM grid with raster LAI and canopy height layers.

## Raster LAI approach

### LAI raster
Any gridded LAI raster covering the domain can be used (e.g. Copernicus Global Land Service LAI products). Import it as a raster table via the `gis_import` task and reference it as `tables.lai` in your config.

### Canopy height raster
Any gridded canopy height raster covering the domain can be used. Import it as a raster table via `gis_import` and reference it as `tables.canopy_height`. Values below 5.0 m are treated as noise/low vegetation and ignored.

### Processing
For each PALM grid cell, the `lai` task (`LaiGenerator`) intersects the grid point with the raster tiles and stores:

- `lai = LAI_raster_value * canopy.lai_mod`
- `canopy_height = LAI_canopy_raster_value * canopy.canopy_height_mod` (if ≥ 5.0 m, else 0)

The `*_mod` multipliers allow scenario generation (e.g. seasonal LAI reduction) without re-importing rasters.

## Individual tree LAD approach

See [tree.md](tree.md) for the point-tree gridding algorithm (`palm_tree_grid` SQL function), which produces per-layer `lad_<k>` / `bad_<k>` columns directly rather than a single LAI value.