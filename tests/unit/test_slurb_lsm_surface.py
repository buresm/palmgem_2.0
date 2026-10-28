"""Unit tests for the SLURB-mode land surface of the static driver (PG-70).

``StaticDriverGen._write_slurb_lsm_surface`` gives every SLUrb cell its
dominant non-urban LSM type and leaves all other cells untouched. The SQL
inputs (``_slurb_cell_plan`` / ``_slurb_cell_type_areas``) are replaced by
canned arrays built from
(urban flag, dominant non-urban landcover type) per cell, so no database is
needed.
"""
import netCDF4
import numpy as np
import pytest

from src.config_loader import load_config
from src.tasks.netcdf_generator import StaticDriverGen

FILL_B = -127


class _Stub(StaticDriverGen):
    """StaticDriverGen without the DB. ``rows`` (j, i order) give per cell
    (urban flag, dominant non-urban landcover type or None); they become a
    building plan fraction (0.5 / 0.0) and 10 m2 of that type."""

    def __init__(self, cfg, ncfile, rows):
        self.cfg, self.ncfile, self._rows = cfg, ncfile, rows

    def _slurb_cell_plan(self):
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx
        plan = np.zeros((ny, nx))
        for k, (urban, _) in enumerate(self._rows):
            j, i = divmod(k, nx)
            plan[j, i] = 0.5 if urban else 0.0
        return plan

    def _slurb_cell_type_areas(self, cells):
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx
        type_areas = {}
        for k, (_, lc_type) in enumerate(self._rows):
            j, i = divmod(k, nx)
            if lc_type is not None and cells[j, i]:
                type_areas.setdefault(lc_type, np.zeros((ny, nx)))[j, i] = 10.0
        return type_areas


@pytest.fixture
def cfg():
    c = load_config('')
    c.domain.update_setting('nx', 2)
    c.domain.update_setting('ny', 2)
    c.update_setting('slurb_reference_size', 0.0)   # per-cell mode
    return c


def _make_driver(path, veg, pav, wat, soil):
    ds = netCDF4.Dataset(path, 'w')
    ds.createDimension('x', 2)
    ds.createDimension('y', 2)
    for name, values in (('vegetation_type', veg), ('pavement_type', pav),
                         ('water_type', wat), ('soil_type', soil)):
        v = ds.createVariable(name, 'i1', ('y', 'x'), fill_value=FILL_B)
        v[:] = np.ma.masked_equal(
            np.array([[FILL_B if c is None else c for c in row] for row in values], dtype='i1'), FILL_B)
    return ds


def _get(ds, name):
    return np.ma.getdata(ds[name][:]).tolist(), np.ma.getmaskarray(ds[name][:]).tolist()


def test_slurb_cells_get_dominant_non_urban_type(cfg, tmp_path):
    # cells in (j, i) order: (0,0) road outside SLUrb, (0,1) SLUrb with grass,
    # (1,0) SLUrb with water, (1,1) SLUrb with no non-urban surface at all
    ds = _make_driver(str(tmp_path / 'd.nc'),
                      veg=[[None, None], [None, None]],
                      pav=[[1, 1], [1, None]],
                      wat=[[None, None], [None, None]],
                      soil=[[1, 1], [1, None]])
    rows = [(False, None), (True, 103), (True, 302), (True, None)]
    _Stub(cfg, ds, rows)._write_slurb_lsm_surface()

    veg, veg_m = _get(ds, 'vegetation_type')
    pav, pav_m = _get(ds, 'pavement_type')
    wat, wat_m = _get(ds, 'water_type')
    _, soil_m = _get(ds, 'soil_type')
    ds.close()

    # outside SLUrb: untouched pavement
    assert pav[0][0] == 1 and not pav_m[0][0] and veg_m[0][0]
    # SLUrb + grass: vegetation 3, pavement removed
    assert veg[0][1] == 3 and not veg_m[0][1] and pav_m[0][1]
    # SLUrb + water: water 2, no vegetation, no pavement, no soil
    assert wat[1][0] == 2 and not wat_m[1][0] and veg_m[1][0] and pav_m[1][0] and soil_m[1][0]
    # SLUrb without non-urban surface: default type 103 -> vegetation 3
    assert veg[1][1] == 3 and not veg_m[1][1]


def test_exactly_one_lsm_type_per_slurb_cell(cfg, tmp_path):
    ds = _make_driver(str(tmp_path / 'one.nc'),
                      veg=[[2, 2], [2, 2]], pav=[[1, 1], [1, 1]],
                      wat=[[None, None], [None, None]], soil=[[1, 1], [1, 1]])
    rows = [(True, 102), (True, 301), (True, None), (False, None)]
    _Stub(cfg, ds, rows)._write_slurb_lsm_surface()
    masks = [np.ma.getmaskarray(ds[n][:]) for n in ('vegetation_type', 'pavement_type', 'water_type')]
    ds.close()
    n_types = sum((~m).astype(int) for m in masks)
    assert n_types[0, 0] == 1 and n_types[0, 1] == 1 and n_types[1, 0] == 1


def test_default_type_is_configurable(cfg, tmp_path):
    cfg.update_setting('slurb_lsm_default_type', 102)
    ds = _make_driver(str(tmp_path / 'def.nc'),
                      veg=[[None, None], [None, None]], pav=[[1, 1], [1, 1]],
                      wat=[[None, None], [None, None]], soil=[[1, 1], [1, 1]])
    _Stub(cfg, ds, [(True, None)] * 4)._write_slurb_lsm_surface()
    veg = ds['vegetation_type'][:]
    ds.close()
    assert (veg == 2).all()


def test_window_mode_uses_windowed_mask_and_type(cfg, tmp_path):
    """3x3 window over a 2x2 grid: every cell sees the whole grid. One
    building cell (plan 0.5) gives a windowed plan of 0.125 < 0.2 -> no
    SLUrb cell; two give 0.25 -> all four cells are SLUrb, and a cell without
    own green space takes the window's dominant non-urban type (crops)."""
    cfg.update_setting('slurb_reference_size', 30.0)    # dx 10 m -> 3 cells
    cfg.domain.update_setting('dx', 10.0)
    ds = _make_driver(str(tmp_path / 'w1.nc'),
                      veg=[[None, None], [None, None]], pav=[[1, 1], [1, 1]],
                      wat=[[None, None], [None, None]], soil=[[1, 1], [1, 1]])
    _Stub(cfg, ds, [(True, None), (False, None), (False, None), (False, None)])._write_slurb_lsm_surface()
    assert ds['pavement_type'][:].count() == 4          # nothing became SLUrb
    ds.close()

    ds = _make_driver(str(tmp_path / 'w2.nc'),
                      veg=[[None, None], [None, None]], pav=[[1, 1], [1, 1]],
                      wat=[[None, None], [None, None]], soil=[[1, 1], [1, 1]])
    _Stub(cfg, ds, [(True, None), (True, None), (False, 102), (False, None)])._write_slurb_lsm_surface()
    veg, pav = ds['vegetation_type'][:], ds['pavement_type'][:]
    ds.close()
    assert pav.count() == 0                             # all four are SLUrb cells
    assert (veg == 2).all()                             # window-dominant crops, not the grass default
