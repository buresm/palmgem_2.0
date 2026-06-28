# Impervious surfaces

An optional refinement on top of the UrbanAtlas + OpenStreetMap landcover classification. An imperviousness raster (0–100% sealed soil) is intersected with the PALM grid. Cells classified as sealed (landcover type `202`) whose imperviousness value is **≤ 50%** are reclassified from pavement to vegetation instead.

This corrects for UrbanAtlas/OSM polygons that are nominally "urban fabric" but contain a significant fraction of unsealed soil (gardens, verges) at the target grid resolution.

## How to enable

The correction runs automatically when an imperviousness raster is available as a grid table: import it via the `gis_import` task and reference it as `tables.impervious` in your config. If no such table is present, the step is skipped (an empty correction table is used) and the run is unaffected.

The 50% threshold is currently fixed in `InitializeDomainTask.check_impervious_grids()` (`src/tasks/initialize_domain.py`).
