# 3D buildings

PALM-GeM supports 3D building structures including **bridges**, **overhanging structures**, and **passages**. Placement follows the PALM PIDS specification.

## How it works

Standard (2D) buildings define a footprint with a single bottom-at-ground and a top at building height. The 3D extension allows the bottom of a building volume to be lifted off the ground:

- **Bridge** — the grid cells between ground level and the bridge bottom are left open. The bridge bottom height is taken from the `extras` raster; the bridge top is at `extras + build_3d.bridge_width`.
- **Overhang / passage** — the structure is first created as a standard 2D building. Wherever an `extras_shp` polygon is defined, the building bottom is raised to the height given by the `extras` raster, creating the void below.

With this approach only a single empty zone per column is supported. Support for multiple void zones (e.g. stacked balconies) is planned for future releases.

> **Note:** 3D buildings are incompatible with cut-cell topography (`do_cct: True`). When CCT is enabled, the 3D buildings feature is automatically disabled.
>
> **Resolution guidance:** 3D structures are best represented at resolutions below 3 m; at coarser resolutions, data quality and grid cell count limit fidelity.

## Required input data

Two additional tables must be imported into PostGIS for the 3D buildings feature:

### `extras_shp` — polygon shapefile

| Attribute | Type | Values | Description |
|:----------|:-----|:-------|:------------|
| gid       | int  | ≥ 1   | Unique polygon identifier |
| type      | int  | ≥ 900 | Building type (PALM building range) |
| typeu     | int  | ≥ 1   | Surface type of the space *under* the structure |
| typed     | int  | ≥ 1   | Surface type of the space *above* the structure |
| class3d   | char |        | Structure class: `bridge`, `passage`, or `overhang` |

### `extras` — raster

| Attribute | Type | Values | Description |
|:----------|:-----|:-------|:------------|
| rast      | real | > 0.0  | Height (m) of the structure bottom above ground |

## Configuration keys

| Key | Default | Description |
|:----|:--------|:------------|
| `tables.extras_shp` | `extras_shp` | Name of the polygon table in the case schema |
| `tables.extras`     | `extras`     | Name of the raster table in the case schema |
| `build_3d.bridge_width` | `2.0` | Vertical extent of the bridge structure (m) |
| `build_3d.bridge`   | `bridge`   | `class3d` value for bridge structures |
| `build_3d.passage`  | `passage`  | `class3d` value for passage structures |
| `build_3d.overhanging` | `overhang` | `class3d` value for overhanging structures |
