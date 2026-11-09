"""Unit tests for the PIDS compliance validator (no live DB needed)."""
import netCDF4
import numpy as np
import pytest
import yaml
from pathlib import Path

from src.utils.pids import validate_dataset, validate_file

SPEC = {
    'required_global_attributes': ['origin_x', 'origin_y', 'origin_lat', 'origin_lon'],
    'required_dimensions': ['x', 'y'],
    'coordinate_variables': ['x', 'y'],
    'exempt_variables': ['crs'],
    'variable_rules': {
        'zt': {'dims': ['y', 'x'], 'dtype_kind': 'f',
               'required_attrs': ['units', 'long_name', '_FillValue']},
    },
}


def _make_nc(path, *, drop_attr=None, zt_dims=('y', 'x'), bad_coord=False,
             with_units=True):
    ds = netCDF4.Dataset(path, 'w')
    for attr, val in (('origin_x', 1000.0), ('origin_y', 2000.0),
                      ('origin_lat', 50.5), ('origin_lon', 13.6)):
        if attr != drop_attr:
            ds.setncattr(attr, val)
    ds.createDimension('x', 4)
    ds.createDimension('y', 3)
    x = ds.createVariable('x', 'f8', ('x',))
    x[:] = [30, 20, 10, 0] if bad_coord else [0, 10, 20, 30]
    y = ds.createVariable('y', 'f8', ('y',))
    y[:] = [0, 10, 20]
    zt = ds.createVariable('zt', 'f4', zt_dims, fill_value=-9999.0)
    zt[:] = np.zeros(tuple(len(ds.dimensions[d]) for d in zt_dims), dtype='f4')
    zt.long_name = 'terrain height'
    if with_units:
        zt.units = 'm'
    ds.close()


def _levels(findings):
    return [f.level for f in findings]


def test_clean_file_has_no_findings(tmp_path):
    path = str(tmp_path / 'ok.nc')
    _make_nc(path)
    with netCDF4.Dataset(path) as ds:
        findings = validate_dataset(ds, SPEC)
    assert findings == []


def test_missing_global_attribute_is_error(tmp_path):
    path = str(tmp_path / 'noattr.nc')
    _make_nc(path, drop_attr='origin_lat')
    with netCDF4.Dataset(path) as ds:
        findings = validate_dataset(ds, SPEC)
    assert any(f.level == 'error' and 'origin_lat' in f.message for f in findings)


def test_wrong_dims_is_error(tmp_path):
    path = str(tmp_path / 'dims.nc')
    _make_nc(path, zt_dims=('x', 'y'))
    with netCDF4.Dataset(path) as ds:
        findings = validate_dataset(ds, SPEC)
    assert any(f.level == 'error' and 'zt' in f.message and 'dimensions' in f.message
               for f in findings)


def test_non_monotonic_coordinate_is_error(tmp_path):
    path = str(tmp_path / 'coord.nc')
    _make_nc(path, bad_coord=True)
    with netCDF4.Dataset(path) as ds:
        findings = validate_dataset(ds, SPEC)
    assert any(f.level == 'error' and 'strictly increasing' in f.message
               for f in findings)


def test_missing_units_flagged(tmp_path):
    """units missing -> generic warning + per-rule error for zt."""
    path = str(tmp_path / 'units.nc')
    _make_nc(path, with_units=False)
    with netCDF4.Dataset(path) as ds:
        findings = validate_dataset(ds, SPEC)
    assert 'warning' in _levels(findings)
    assert any(f.level == 'error' and 'units' in f.message for f in findings)


def test_shipped_spec_parses_and_covers_both_drivers():
    spec_path = Path(__file__).resolve().parents[2] / 'config' / 'pids_spec.yaml'
    with open(spec_path) as f:
        spec = yaml.safe_load(f)
    assert 'static' in spec and 'slurb' in spec
    for section in ('static', 'slurb'):
        assert spec[section]['required_dimensions'] == ['x', 'y']
        assert 'variable_rules' in spec[section]


def test_validate_file_selects_section(tmp_path):
    path = str(tmp_path / 'file.nc')
    _make_nc(path)
    findings = validate_file(path, {'static': SPEC}, 'static')
    assert findings == []
    findings = validate_file(path, {'static': SPEC}, 'nonexistent')
    assert findings and findings[0].level == 'warning'


# --- cross-variable consistency (check_static_consistency) -------------------

FILL = -9999.0
FILL_B = -127


def _make_surface_nc(path, *, veg=None, pave=None, bld_h=None, bld_id=None,
                     bld_type=None, soil=None, wat=None, zt=None, surface_fraction=False,
                     no_water=False):
    """2x2 driver holding only the surface variables. Each argument is a 2x2
    list; None entries become fill values. Variables left as None are not
    written at all, except water_type, which is all fill by default (the
    driver always writes it) and left out with no_water."""
    ds = netCDF4.Dataset(path, 'w')
    ds.createDimension('x', 2)
    ds.createDimension('y', 2)

    def var(name, values, dtype, fill):
        if values is None:
            return
        v = ds.createVariable(name, dtype, ('y', 'x'), fill_value=fill)
        v[:] = np.ma.masked_equal(
            np.array([[fill if c is None else c for c in row] for row in values],
                     dtype=dtype), fill)

    var('zt', zt if zt is not None else [[0, 0], [0, 0]], 'f4', FILL)
    var('vegetation_type', veg, 'i1', FILL_B)
    var('pavement_type', pave, 'i1', FILL_B)
    var('buildings_2d', bld_h, 'f4', FILL)
    var('building_id', bld_id, 'i4', -9999)
    var('building_type', bld_type, 'i1', FILL_B)
    var('soil_type', soil, 'i1', FILL_B)
    if not no_water:
        var('water_type', wat if wat is not None else [[None, None], [None, None]], 'i1', FILL_B)
    if surface_fraction:
        ds.createDimension('nsurface_fraction', 3)
        ds.createVariable('surface_fraction', 'f4', ('nsurface_fraction', 'y', 'x'))
    ds.close()


def _consistency(path):
    from src.utils.pids import check_static_consistency
    with netCDF4.Dataset(path) as ds:
        return check_static_consistency(ds)


def test_consistent_surface_is_clean(tmp_path):
    path = str(tmp_path / 'ok.nc')
    _make_surface_nc(path,
                     veg=[[3, None], [None, None]], pave=[[None, 1], [None, None]],
                     bld_h=[[None, None], [10, 20]], bld_id=[[None, None], [1, 1]],
                     bld_type=[[None, None], [2, 2]],
                     soil=[[1, 1], [None, None]])
    assert _consistency(path) == []


def test_cell_without_surface_type_is_error(tmp_path):
    path = str(tmp_path / 'hole.nc')
    _make_surface_nc(path, veg=[[3, 3], [3, None]], pave=[[None, None], [None, None]],
                     soil=[[1, 1], [1, None]])
    findings = _consistency(path)
    assert any(f.level == 'error' and 'without any surface type' in f.message for f in findings)


def test_two_surface_types_error_unless_surface_fraction(tmp_path):
    kwargs = dict(veg=[[3, 3], [3, 3]], pave=[[1, None], [None, None]],
                  soil=[[1, 1], [1, 1]])
    path = str(tmp_path / 'multi.nc')
    _make_surface_nc(path, **kwargs)
    assert any(f.level == 'error' and 'more than one' in f.message for f in _consistency(path))

    path = str(tmp_path / 'multi_sf.nc')
    _make_surface_nc(path, surface_fraction=True, **kwargs)
    findings = _consistency(path)
    assert any(f.level == 'warning' and 'more than one' in f.message for f in findings)
    assert not any(f.level == 'error' for f in findings)


def test_zero_height_building_is_error(tmp_path):
    """a building cell whose height rounded down to 0"""
    path = str(tmp_path / 'flat.nc')
    _make_surface_nc(path, veg=[[3, 3], [None, None]],
                     bld_h=[[None, None], [0, 10]], bld_id=[[None, None], [1, 1]],
                     bld_type=[[None, None], [2, 2]], soil=[[1, 1], [None, None]])
    findings = _consistency(path)
    assert any(f.level == 'error' and 'height <= 0' in f.message for f in findings)


def test_building_variables_disagree_is_error(tmp_path):
    path = str(tmp_path / 'bvars.nc')
    _make_surface_nc(path, veg=[[3, 3], [None, None]],
                     bld_h=[[None, None], [10, 10]], bld_id=[[None, None], [1, None]],
                     bld_type=[[None, None], [2, 2]], soil=[[1, 1], [None, None]])
    findings = _consistency(path)
    assert any(f.level == 'error' and 'building_id' in f.message and 'disagree' in f.message
               for f in findings)


def test_missing_soil_and_terrain_are_errors(tmp_path):
    path = str(tmp_path / 'soil.nc')
    _make_surface_nc(path, veg=[[3, 3], [3, 3]], soil=[[1, 1], [1, None]],
                     zt=[[0, 0], [0, None]])
    messages = [f.message for f in _consistency(path) if f.level == 'error']
    assert any('soil_type' in m for m in messages)
    assert any('zt' in m and 'terrain' in m for m in messages)


def test_missing_surface_classification_is_error(tmp_path):
    # PALM needs all four LSM classifications in the file (DRV0011)
    path = str(tmp_path / 'nowater.nc')
    _make_surface_nc(path, veg=[[3, 3], [3, 3]], pave=[[None, None], [None, None]],
                     soil=[[1, 1], [1, 1]], no_water=True)
    assert any(f.level == 'error' and 'water_type missing' in f.message and 'DRV0011' in f.message
               for f in _consistency(path))


def test_consistency_runs_only_when_spec_enables_it(tmp_path):
    path = str(tmp_path / 'gate.nc')
    _make_surface_nc(path, veg=[[3, 3], [3, None]], soil=[[1, 1], [1, None]])
    with netCDF4.Dataset(path) as ds:
        off = validate_dataset(ds, {'required_dimensions': ['x', 'y']})
        on = validate_dataset(ds, {'required_dimensions': ['x', 'y'],
                                   'consistency_checks': True})
    assert not any('surface type' in f.message for f in off)
    assert any('surface type' in f.message for f in on)


# --- SLURB consistency (check_slurb_consistency) -----------------------------

def _make_slurb_nc(path, **fields):
    """2x2 SLURB driver; every keyword is a 2x2 list (None = fill) and becomes
    an f4 variable of that name."""
    ds = netCDF4.Dataset(path, 'w')
    ds.createDimension('x', 2)
    ds.createDimension('y', 2)
    for name, values in fields.items():
        var = ds.createVariable(name, 'f4', ('y', 'x'), fill_value=FILL)
        var[:] = np.ma.masked_equal(
            np.array([[FILL if c is None else c for c in row] for row in values], dtype='f4'), FILL)
    ds.close()


# cells: (0,0) SLUrb, (0,1) SLUrb, (1,0) SLUrb, (1,1) non-urban (urban_fraction 0,
# the rest fill)
_SLURB_OK = dict(
    urban_fraction=[[0.9, 0.6], [0.5, 0.0]],
    building_plan_area_fraction=[[0.4, 0.3], [0.2, None]],
    building_frontal_area_fraction=[[0.1, 0.08], [0.05, None]],
    building_height=[[9.0, 7.0], [6.0, None]],
    street_canyon_aspect_ratio=[[0.3, 0.2], [0.1, None]],
    street_canyon_orientation=[[10.0, None], [179.0, None]],   # None = isotropic
    z0_urb=[[0.5, 0.4], [0.3, None]],
    deep_soil_temperature=[[285.0, 285.0], [285.0, None]],
)


def _slurb(path, **overrides):
    from src.utils.pids import check_slurb_consistency
    _make_slurb_nc(path, **{**_SLURB_OK, **overrides})
    with netCDF4.Dataset(path) as ds:
        return check_slurb_consistency(ds)


def _has(findings, level, *words):
    return any(f.level == level and all(w in f.message for w in words) for f in findings)


def test_slurb_consistent_driver_is_clean(tmp_path):
    assert _slurb(str(tmp_path / 'ok.nc')) == []


def test_slurb_inputs_without_palm_default_left_out_warn(tmp_path):
    # left out of the driver they must come from the namelist (no PALM default)
    path = str(tmp_path / 'nml.nc')
    fields = {k: val for k, val in _SLURB_OK.items() if k not in ('z0_urb', 'deep_soil_temperature')}
    _make_slurb_nc(path, **fields)
    from src.utils.pids import check_slurb_consistency
    with netCDF4.Dataset(path) as ds:
        f = check_slurb_consistency(ds)
    assert _has(f, 'warning', 'z0_urb', 'urban_roughness_length', 'SLU0019')
    assert _has(f, 'warning', 'deep_soil_temperature', 'SLU0019')
    assert not any(x.level == 'error' for x in f)


def test_slurb_plan_exceeding_urban_is_error(tmp_path):
    f = _slurb(str(tmp_path / 'p.nc'), building_plan_area_fraction=[[0.95, 0.3], [0.2, None]])
    assert _has(f, 'error', 'exceeds urban_fraction')


def test_slurb_ranges_are_errors(tmp_path):
    f = _slurb(str(tmp_path / 'r.nc'),
               urban_fraction=[[1.2, 0.6], [0.5, 0.0]],
               building_height=[[0.0, 7.0], [6.0, None]],
               street_canyon_aspect_ratio=[[-0.1, 0.2], [0.1, None]],
               street_canyon_orientation=[[360.0, None], [179.0, None]],
               building_frontal_area_fraction=[[-0.01, 0.08], [0.05, None]])
    assert _has(f, 'error', 'urban_fraction', 'outside [0, 1]')
    assert _has(f, 'error', 'building_height', '<= 0')
    assert _has(f, 'error', 'street_canyon_aspect_ratio', '<= 0')
    assert _has(f, 'error', 'street_canyon_orientation', 'outside [0, 360)')
    assert _has(f, 'error', 'building_frontal_area_fraction', 'negative')


def test_slurb_urban_fraction_fill_is_error(tmp_path):
    # PALM range-checks urban_fraction in every cell (SLU0032)
    f = _slurb(str(tmp_path / 'u.nc'), urban_fraction=[[0.9, 0.6], [0.5, None]])
    assert _has(f, 'error', 'urban_fraction', 'fill value in 1 cell', 'SLU0032')


def test_slurb_fill_in_slurb_cell_is_error(tmp_path):
    # a fill value in the driver is read as is and aborts PALM (SLU0022)
    f = _slurb(str(tmp_path / 'm.nc'), street_canyon_aspect_ratio=[[0.3, None], [0.1, None]])
    assert _has(f, 'error', 'street_canyon_aspect_ratio', 'fill value in 1 of 3', 'SLU0022')


def test_slurb_degenerate_canyon_warns(tmp_path):
    f = _slurb(str(tmp_path / 'deg.nc'),
               building_plan_area_fraction=[[0.89, 0.3], [0.2, None]],   # 0.89 / 0.9 urban
               street_canyon_aspect_ratio=[[0.3, 76.0], [0.1, None]])
    assert _has(f, 'warning', 'building_plan_area_fraction', '1 SLUrb cell', 'canyon')
    assert _has(f, 'warning', 'street_canyon_aspect_ratio', 'above 10', '1 SLUrb cell')
    assert not any(x.level == 'error' for x in f)


def test_slurb_isotropic_orientation_is_fine(tmp_path):
    f = _slurb(str(tmp_path / 'iso.nc'), street_canyon_orientation=[[None, None], [None, None]])
    assert f == []


def test_slurb_deep_canopy_and_ignored_cells_warn(tmp_path):
    f = _slurb(str(tmp_path / 'w.nc'),
               building_height=[[65.0, 7.0], [6.0, 5.0]],                 # 65 m; (1,1) not urban
               urban_fraction=[[0.9, 0.6], [0.5, 0.005]])
    assert _has(f, 'warning', 'above 60 m')
    assert _has(f, 'warning', 'building_height', 'SLUrb ignores')


def test_slurb_rules_selected_by_spec(tmp_path):
    path = str(tmp_path / 'sel.nc')
    _make_slurb_nc(path, **{**_SLURB_OK, 'building_plan_area_fraction': [[0.95, 0.3], [0.2, None]]})
    with netCDF4.Dataset(path) as ds:
        on = validate_dataset(ds, {'required_dimensions': ['x', 'y'], 'consistency_checks': 'slurb'})
        static = validate_dataset(ds, {'required_dimensions': ['x', 'y'], 'consistency_checks': 'static'})
    assert _has(on, 'error', 'exceeds urban_fraction')
    assert not _has(static, 'error', 'exceeds urban_fraction')


def test_building_over_lsm_allowed_only_where_hollow_at_ground(tmp_path):
    """3-D buildings: a bridge/overhang cell (buildings_3d[0] == 0) keeps the
    LSM surface below it; a building solid at the ground must not."""
    from src.utils.pids import check_static_consistency
    path = str(tmp_path / 'b3d.nc')
    ds = netCDF4.Dataset(path, 'w')
    ds.createDimension('x', 2)
    ds.createDimension('y', 1)
    ds.createDimension('z', 2)
    zt = ds.createVariable('zt', 'f4', ('y', 'x'), fill_value=FILL)
    zt[:] = [[0.0, 0.0]]
    for name, vals in (('pavement_type', [[1, 1]]), ('building_type', [[2, 2]])):
        var = ds.createVariable(name, 'i1', ('y', 'x'), fill_value=FILL_B)
        var[:] = np.array(vals, dtype='i1')
    b3 = ds.createVariable('buildings_3d', 'i1', ('z', 'y', 'x'), fill_value=FILL_B)
    b3[:] = np.array([[[0, 1]], [[1, 1]]], dtype='i1')   # cell 0 hollow at ground (bridge)
    ds.close()
    with netCDF4.Dataset(path) as ds:
        findings = check_static_consistency(ds)
    assert any(f.level == 'error' and '1 building cell(s)' in f.message for f in findings)
    assert not any('more than one LSM' in f.message for f in findings)


# --- building material fractions (check_building_fractions) -----------------

def _make_fraction_nc(path, wall_win_green, surf_pars=None):
    """1x1 driver with building_fraction (9 levels: wall 0-2, window 3-5,
    green 6-8) set from {level: (wall, window, green)}, None = fill, and
    optionally building_surface_pars rows (wall, window, green_w, green_r)."""
    ds = netCDF4.Dataset(path, 'w')
    ds.createDimension('x', 1)
    ds.createDimension('y', 1)
    ds.createDimension('building_surface_type', 9)
    bf = ds.createVariable('building_fraction', 'f4', ('building_surface_type', 'y', 'x'), fill_value=FILL)
    vals = np.full((9, 1, 1), FILL, dtype='f4')
    for lvl, triple in wall_win_green.items():
        for off, val in zip((0, 3, 6), triple):
            if val is not None:
                vals[lvl + off] = val
    bf[:] = np.ma.masked_equal(vals, FILL)
    if surf_pars is not None:
        ds.createDimension('nbuilding_surface_pars', 4)
        ds.createDimension('s', len(surf_pars))
        sp = ds.createVariable('building_surface_pars', 'f4', ('nbuilding_surface_pars', 's'), fill_value=FILL)
        a = np.array([[FILL if c is None else c for c in row] for row in surf_pars], dtype='f4').T
        sp[:] = np.ma.masked_equal(a, FILL)
    ds.close()


def _fractions(path):
    from src.utils.pids import check_building_fractions
    with netCDF4.Dataset(path) as ds:
        return check_building_fractions(ds)


def test_fractions_summing_to_one_are_clean(tmp_path):
    path = str(tmp_path / 'ok.nc')
    _make_fraction_nc(path, {0: (0.7, 0.3, 0), 1: (0.6, 0.4, 0), 2: (1, 0, 0)},
                      surf_pars=[(0.7, 0.3, 0, 0), (1, 0, 0, 0), (0.5, 0.2, 0.9, 0.3)])
    assert _fractions(path) == []


def test_percent_fractions_are_errors(tmp_path):
    # wall/window given in percent (70/30) as in the Guelph inputs
    path = str(tmp_path / 'pct.nc')
    _make_fraction_nc(path, {0: (70, 30, 0), 1: (0.6, 0.4, 0), 2: (1, 0, 0)},
                      surf_pars=[(70, 30, 0, 0), (1, 0, 0, 0)])
    findings = _fractions(path)
    assert _has(findings, 'error', 'building_fraction (ground floor)', 'sums 100')
    assert not _has(findings, 'error', 'upper floors')
    assert _has(findings, 'error', 'building_surface_pars', '1 surface')


def test_roof_green_overrides_wall_green_on_surfaces(tmp_path):
    # PALM takes the roof green (index 3) over the wall green (index 2)
    path = str(tmp_path / 'green.nc')
    _make_fraction_nc(path, {}, surf_pars=[(0.5, 0.2, 0.3, 0.5)])
    assert _has(_fractions(path), 'error', 'building_surface_pars', 'sums 1.2')


def test_half_defined_fractions_warn(tmp_path):
    # undefined fractions come from the building type; only partial sets warn
    path = str(tmp_path / 'half.nc')
    _make_fraction_nc(path, {0: (None, None, 0), 1: (0.6, None, 0)})
    findings = _fractions(path)
    assert not any(f.level == 'error' for f in findings)
    assert _has(findings, 'warning', 'upper floors', 'undefined in 1 cell')
    assert not _has(findings, 'warning', 'ground floor')
