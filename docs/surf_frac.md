# Surface fraction

Surface fractions represent the sub-grid-cell area contribution of each PALM surface type (vegetation, pavement, water, building) to a grid cell, rather than assigning each cell a single dominant type.

> **Status:** the per-cell fraction calculation is implemented in PostGIS, but the values are **not yet written to the static driver NetCDF** — the writer currently logs a "Surface fractions not implemented yet in PALM" warning and skips the `surface_fraction` variable. Enabling `landcover.surface_fractions` therefore has no effect on the output file at present.

## How it works

For each grid cell, the fraction is calculated as:

```
fraction(type) = AREA(type polygon ∩ grid cell) / AREA(grid cell)
```

Fractions below `landcover.min_fraction` are nullified (treated as zero). A grid cell is classified as a *building cell* when buildings occupy the majority of its area.

## Limitations

- Not yet emitted to the static driver (see Status above).
- Not compatible with LOD2 parametrization.
- Only PALM-type-level fractions are supported; per-material fractions require LOD2.

## Configuration keys

| Key | Default | Description |
|:----|:--------|:------------|
| `landcover.surface_fractions` | `False` | Enable sub-grid surface fraction calculation |
| `landcover.min_fraction`      | `False` | Minimum area fraction to retain a type (set to a float, e.g. `0.05` for 5%) |
