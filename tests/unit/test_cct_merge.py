"""Unit tests for the wall/terrain merge of the cut-cell topography
(CctProcessing.merge_local_wall_terrain), no database needed.

The cell (i, j, k) = (0, 0, 10) spans z in [9, 10). A wall crosses it along
x = 0.5 from y = 0 to y = 1; the terrain west of it lies flat on the cell floor
(z = 9). Each wall foot sits on a cell face shared with a neighbour: (0, -1)
for the foot at y = 0, (0, 1) for the foot at y = 1.
"""
from types import SimpleNamespace

import numpy as np

from src.tasks.cct_processing import CctProcessing

FLOOR, TOP = 9.0, 10.0


def _task(terrain_cells):
    task = CctProcessing.__new__(CctProcessing)
    task.cfg = SimpleNamespace(domain=SimpleNamespace(origin_x=0.0, origin_y=0.0, dx=1.0, dy=1.0, dz=1.0))
    task.db = None
    task._terrain_cells = set(terrain_cells)
    return task


def _merge(terrain_cells):
    wall = np.array([[0.5, 0.0, FLOOR], [0.5, 1.0, FLOOR], [0.5, 1.0, TOP], [0.5, 0.0, TOP]], dtype=object)
    terr = np.array([[0.0, 0.0, FLOOR], [0.5, 0.0, FLOOR], [0.5, 1.0, FLOOR], [0.0, 1.0, FLOOR]], dtype=object)
    out = _task(terrain_cells).merge_local_wall_terrain(0, 0, 10, wall, terr, 4, 4)
    return [tuple(float(c) for c in row) for row in out if row[0] is not None]


def test_feet_next_to_plain_walls_climb_the_wall():
    # neither neighbour has terrain in this cell: both show a vertical wall
    # from the floor up, so the merged face keeps both feet
    ring = _merge([])
    assert ring == [(0.0, 0.0, FLOOR), (0.5, 0.0, FLOOR), (0.5, 0.0, TOP),
                    (0.5, 1.0, TOP), (0.5, 1.0, FLOOR), (0.0, 1.0, FLOOR)]


def test_feet_next_to_merged_cells_are_raised():
    # both neighbours merge terrain and wall in this cell too: the feet are
    # raised to the wall top on both sides, as before
    ring = _merge([(0, -1, 10), (0, 1, 10)])
    assert (0.5, 0.0, FLOOR) not in ring and (0.5, 1.0, FLOOR) not in ring
    assert (0.5, 0.0, TOP) in ring and (0.5, 1.0, TOP) in ring


def test_only_the_foot_next_to_a_plain_wall_is_kept():
    ring = _merge([(0, 1, 10)])
    assert ring == [(0.0, 0.0, FLOOR), (0.5, 0.0, FLOOR), (0.5, 0.0, TOP),
                    (0.5, 1.0, TOP), (0.0, 1.0, FLOOR)]
