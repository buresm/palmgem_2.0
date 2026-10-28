"""Sliding reference window for SLURB urban morphology (PG-72).

The SLUrb guide: morphological parameters "are well-defined only for
reference areas of at least 100x100 m2", so on finer grids they should be
averaged over a sliding window. Plan/urban/frontal fractions are area sums
per cell, so the window value is exactly the mean of the per-cell values over
the window; building height is the plan-area weighted mean.

The window is centred on each cell and therefore spans an odd number of
cells: the smallest odd count whose extent is >= slurb_reference_size. At the
domain edge it is clipped and averaged over the cells inside the domain.
All functions work on (ny, nx) arrays ordered like the grid (j, i).
"""
from math import ceil

import numpy as np


def window_cells(cfg):
    """Window width in grid cells (odd); 1 means per-cell (no window)."""
    size = float(cfg.get('slurb_reference_size', 0.0) or 0.0)
    dx = float(cfg.domain.dx)
    if size <= dx:
        return 1
    n = int(ceil(size / dx - 1e-9))
    return n if n % 2 else n + 1


def box_sum(a, n):
    """Sum of each cell's centred n x n neighbourhood (cells outside the
    domain count as zero). Integral-image implementation, O(ny*nx)."""
    a = np.asarray(a, dtype=float)
    if n <= 1:
        return a.copy()
    r = n // 2
    ny, nx = a.shape
    c = np.pad(a, r, mode='constant').cumsum(axis=0).cumsum(axis=1)
    c = np.pad(c, ((1, 0), (1, 0)), mode='constant')
    out = (c[n:n + ny, n:n + nx] - c[0:ny, n:n + nx]
           - c[n:n + ny, 0:nx] + c[0:ny, 0:nx])
    # the integral image subtracts large running totals: a window that holds
    # nothing comes out as rounding residue (~1e-10 for areas summing to
    # 1e6 m2), not as 0, and would count as "data present". Zero everything
    # below a tolerance well above that residue and far below any real value.
    tol = 1e-9 * max(1.0, float(np.abs(a).max()))
    out[np.abs(out) < tol] = 0.0
    return out


def box_mean(a, n):
    """Mean over the centred window, normalised by the number of in-domain
    cells (so edge windows are not diluted by the outside)."""
    a = np.asarray(a, dtype=float)
    return box_sum(a, n) / box_sum(np.ones_like(a), n)


def weighted_box_mean(values, weights, n):
    """sum(values*weights) / sum(weights) over the window; NaN where the
    window holds no weight."""
    values = np.nan_to_num(np.asarray(values, dtype=float))
    weights = np.asarray(weights, dtype=float)
    wsum = box_sum(weights, n)
    out = np.full(wsum.shape, np.nan)
    np.divide(box_sum(values * weights, n), wsum, out=out, where=wsum > 0)
    return out


def dominant_type(type_areas, n):
    """Dominant surface type per cell over the window.

    ``type_areas``: {type: (ny, nx) area array}. Returns (types, found):
    the type with the largest windowed area and a mask of cells where any
    such area exists (``types`` is 0 where nothing was found).
    """
    if not type_areas:
        return None, None
    keys = sorted(type_areas)
    stack = np.stack([box_sum(type_areas[k], n) for k in keys])
    best = np.argmax(stack, axis=0)
    found = stack.max(axis=0) > 0
    types = np.where(found, np.asarray(keys)[best], 0)
    return types, found
