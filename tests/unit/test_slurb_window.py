"""Unit tests for the SLURB sliding reference window (PG-72)."""
import numpy as np
import pytest

from src.config_loader import load_config
from src.utils.slurb_window import (box_mean, box_sum, dominant_type,
                                    weighted_box_mean, window_cells)


@pytest.mark.parametrize('size, dx, expected', [
    (100.0, 10.0, 11),   # 10 cells would not centre -> next odd count
    (90.0, 10.0, 9),
    (100.0, 5.0, 21),
    (10.0, 10.0, 1),     # window not larger than a cell -> per-cell
    (0.0, 10.0, 1),      # 0 = per-cell mode
    (100.0, 20.0, 5),
])
def test_window_cells(size, dx, expected):
    cfg = load_config('')
    cfg.update_setting('slurb_reference_size', size)
    cfg.domain.update_setting('dx', dx)
    assert window_cells(cfg) == expected


def test_box_sum_matches_brute_force():
    rng = np.random.default_rng(0)
    a = rng.random((7, 9))
    n = 3
    got = box_sum(a, n)
    p = np.pad(a, 1)
    want = np.array([[p[j:j + 3, i:i + 3].sum() for i in range(9)] for j in range(7)])
    np.testing.assert_allclose(got, want)


def test_box_mean_normalises_at_edges():
    a = np.ones((5, 5))
    np.testing.assert_allclose(box_mean(a, 3), 1.0)   # no dilution at the edge


def test_box_mean_of_isolated_building_spreads_it():
    a = np.zeros((5, 5))
    a[2, 2] = 0.9
    m = box_mean(a, 3)
    assert m[2, 2] == pytest.approx(0.1)
    assert m[1, 1] == pytest.approx(0.1)
    assert m[0, 0] == pytest.approx(0.0)


def test_n1_is_identity():
    a = np.arange(12.0).reshape(3, 4)
    np.testing.assert_allclose(box_mean(a, 1), a)
    np.testing.assert_allclose(weighted_box_mean(a, np.ones_like(a), 1), a)


def test_weighted_mean_ignores_cells_without_weight():
    h = np.array([[5.0, 99.0, 15.0]])
    w = np.array([[0.5, 0.0, 0.5]])           # middle cell has no buildings
    m = weighted_box_mean(h, w, 3)
    assert m[0, 1] == pytest.approx(10.0)      # 99 m ignored
    assert np.isnan(weighted_box_mean(h, np.zeros_like(w), 3)).all()


def test_dominant_type_over_window():
    grass = np.array([[0.0, 0.0, 30.0]])
    crops = np.array([[10.0, 0.0, 0.0]])
    types, found = dominant_type({103: grass, 102: crops}, 3)
    assert types.tolist() == [[102, 103, 103]]  # middle cell: 30 grass vs 10 crops
    assert found.all()
    types1, found1 = dominant_type({103: grass, 102: crops}, 1)
    assert types1.tolist() == [[102, 0, 103]] and found1.tolist() == [[True, False, True]]


def test_empty_window_is_exactly_zero_despite_large_values_elsewhere():
    """Integral-image rounding must not turn an empty window into 'area
    present' (PG-72 regression: noise made dominant_type pick random types)."""
    rng = np.random.default_rng(1)
    a = np.zeros((100, 100))
    a[:, 60:] = rng.random((100, 40)) * 100.0       # large areas on the right
    s = box_sum(a, 11)
    assert (s[:, :50] == 0.0).all()                  # left windows are empty
    types, found = dominant_type({102: a}, 11)
    assert not found[:, :50].any()
    assert np.isnan(weighted_box_mean(np.ones_like(a), a, 11)[:, :50]).all()
