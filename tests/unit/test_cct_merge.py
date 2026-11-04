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


# --- terrain step along a wall (Legerova subdomain, terrain raised 1 -> 4 m
# --- within one column next to the wall foot)

def _rows(out):
    return [tuple(round(float(c), 3) for c in row) for row in out if row[0] is not None]


def test_wall_on_terrain_step_is_clipped_and_joined():
    # cell z in [3, 4): the terrain rises across the cell towards x = 38 and
    # touches the wall along P3 -> (38, 32.284, 4); no terrain point lies under
    # a wall top, so the wall part above the contact is joined to the terrain
    p3 = [37.66666666668607, 32.23021105490625, 3.0]
    wall = np.array([[37.0, 32.12247377168387, 3.0], [37.0, 32.12247377168387, 4.0],
                     [38.0, 32.2840796969831, 4.0], [38.0, 32.2840796969831, 3.0]], dtype=object)
    terr = np.array([p3, [37.66666666668607, 33.0, 3.0], [38.0, 33.0, 4.0], [38.0, 32.2840796969831, 4.0]],
                    dtype=object)
    out = _task([]).merge_local_wall_terrain(37, 32, 4, wall, terr, 4, 4)
    assert _rows(out) == [(37.667, 32.23, 3.0), (37.667, 33.0, 3.0), (38.0, 33.0, 4.0), (38.0, 32.284, 4.0),
                          (37.0, 32.122, 4.0), (37.0, 32.122, 3.0)]


def _falling_terrain(terrain_cells):
    # cell z in [4, 5): flat terrain at z = 4 touches the wall in one point only,
    # the other wall foot stands over terrain that is lower (in the cell below)
    s = [41.0, 37.19621293991804, 4.0]
    wall = np.array([[40.694184497522656, 38.0, 4.0], [41.0, 37.19621293991804, 4.0],
                     [41.0, 37.19621293991804, 5.0], [40.694184497522656, 38.0, 5.0]], dtype=object)
    terr = np.array([[40.0, 37.0, 4.0], s, [41.0, 37.0, 4.0]], dtype=object)
    return _rows(_task(terrain_cells).merge_local_wall_terrain(40, 37, 5, wall, terr, 4, 3))


def test_wall_over_falling_terrain_is_kept():
    ring = _falling_terrain([(40, 37, 4)])
    assert ring == [(40.0, 37.0, 4.0), (40.694, 38.0, 4.0), (40.694, 38.0, 5.0), (41.0, 37.196, 5.0),
                    (41.0, 37.196, 4.0), (41.0, 37.0, 4.0)]


def test_wall_over_falling_terrain_without_terrain_below_keeps_old_merge():
    # no terrain in the cell below: the foot may be buried, the old merge
    # (point under the wall top raised to the top) applies
    ring = _falling_terrain([])
    assert (40.694, 38.0, 4.0) not in ring
    assert (41.0, 37.196, 5.0) in ring


def test_join_rings_on_shared_edge_needs_one_common_edge():
    assert CctProcessing._join_rings_on_shared_edge([(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                                                    [(5, 5, 5), (6, 5, 5), (6, 6, 5)]) is None
    joined = CctProcessing._join_rings_on_shared_edge([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                                                      [(1, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0)])
    assert [tuple(float(c) for c in p) for p in joined] == [(0, 0, 0), (1, 0, 0), (2, 0, 0), (2, 1, 0),
                                                            (1, 1, 0), (0, 1, 0)]


def _free(dsc):
    s = {0: (1, 0, 0), 1: (-1, 0, 0), 2: (0, 1, 0), 3: (0, -1, 0), 4: (0, 0, 1), 5: (0, 0, -1)}[dsc[3]]
    return dsc[0] + s[0], dsc[1] + s[1], dsc[2] + s[2]


def test_surface_corner_merge_links_both_neighbours():
    # wall face above flat terrain at z = 4: the wall foot vertex at x = 38
    # names the corner (4, 33, 38), which lies on the terrain, as free. It is
    # replaced by two descriptions of that corner, each sharing a corner with
    # one ring neighbour (dir: 0 +z, 2 +y, 5 -x)
    v1, moving, v3, v4 = (4, 32, 37, 2, 0.122), (4, 32, 38, 2, 0.284), (5, 32, 38, 2, 0.284), (5, 32, 37, 2, 0.122)
    g = (4.0, 33.0, 38.0)
    corners = {(4, 33, 38): {(4, 33, 38, 0, 0.0): g, (4, 33, 38, 2, 0.0): g, (4, 33, 38, 5, 0.0): g}}
    ring = [((37.0, 32.122, 4.0), v1), ((38.0, 32.284, 4.0), moving), ((38.0, 32.284, 5.0), v3),
            ((37.0, 32.122, 5.0), v4)]
    out = CctProcessing._merge_ring_into_corners(ring, {moving: (4, 33, 38)}, corners, _free, True)
    assert [d for _, d in out] == [v1, (4, 33, 38, 5, 0.0), (4, 33, 38, 0, 0.0), v3, v4, v1]


def test_surface_corner_merge_drops_corner_between_linked_neighbours():
    # the neighbours share their free corner: the cut runs past the corner
    prev, moving, nxt = (4, 38, 41, 5, 0.306), (4, 37, 41, 2, 0.196), (4, 37, 40, 2, 0.0)
    g = (41.0, 37.0, 4.0)
    corners = {(4, 37, 41): {(4, 37, 41, 0, 0.0): g}, (4, 37, 40): {nxt: (40.0, 37.0, 4.0)}}
    ring = [((40.694, 38.0, 4.0), prev), ((41.0, 37.196, 4.0), moving), ((40.0, 37.0, 4.0), nxt),
            ((40.0, 37.333, 3.0), (3, 37, 40, 2, 0.333))]
    out = CctProcessing._merge_ring_into_corners(ring, {moving: (4, 37, 41)}, corners, _free, True)
    assert [d for _, d in out] == [prev, nxt, (3, 37, 40, 2, 0.333), prev]
