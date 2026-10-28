"""Unit tests for the QA report building blocks (no live DB needed)."""
import netCDF4
import numpy as np

from src.tasks.qa_report import _var_stats, collect_file_section, render_report


def _make_nc(path):
    ds = netCDF4.Dataset(path, 'w')
    ds.setncattr('origin_x', 1000.0)
    ds.createDimension('x', 4)
    ds.createDimension('y', 3)
    x = ds.createVariable('x', 'f8', ('x',))
    x[:] = [0, 10, 20, 30]
    zt = ds.createVariable('zt', 'f4', ('y', 'x'), fill_value=-9999.0)
    data = np.arange(12, dtype='f4').reshape(3, 4)
    zt[:] = data
    zt[0, 0] = -9999.0  # one fill cell
    zt.long_name = 'terrain height'
    ds.close()


def test_var_stats_handles_masked_values():
    arr = np.ma.masked_values([1.0, 2.0, 3.0, -9999.0], -9999.0)
    stats = _var_stats(arr)
    assert stats['count'] == 4
    assert stats['fill_fraction'] == 0.25
    assert stats['min'] == 1.0
    assert stats['max'] == 3.0


def test_var_stats_all_masked():
    arr = np.ma.masked_values([-9999.0, -9999.0], -9999.0)
    stats = _var_stats(arr)
    assert stats['fill_fraction'] == 1.0
    assert stats['min'] is None


def test_collect_file_section(tmp_path):
    path = str(tmp_path / 'static.nc')
    _make_nc(path)
    section = collect_file_section(path, 'static', pids_spec=None)

    assert ('x', 4) in section['dims'] and ('y', 3) in section['dims']
    names = {v['name']: v for v in section['variables']}
    assert 'zt' in names
    # 2D numeric variable gets stats and an embedded thumbnail
    assert names['zt']['stats']['max'] == 11.0
    assert names['zt']['image'] is not None
    # 1D coordinate gets stats but no thumbnail
    assert names['x']['image'] is None


def test_render_report_is_selfcontained_html(tmp_path):
    path = str(tmp_path / 'static.nc')
    _make_nc(path)
    context = {
        'case': 'test_case',
        'generated': '2026-07-03 12:00:00',
        'meta': [('case schema', 'test_case')],
        'files': [collect_file_section(path, 'static', pids_spec=None)],
        'landcover_shares': [(101, 12, 0.6), (901, 5, 0.4)],
        'building_stats': [('building grid cells', 5)],
        'timings': [('initialize_domain', 7.7)],
    }
    html = render_report(context)

    assert html.startswith('<!DOCTYPE html>')
    assert 'test_case' in html
    assert 'zt' in html
    assert 'data:image/png;base64,' in html      # embedded thumbnail
    assert 'initialize_domain' in html           # timings table
    assert '60.0 %' in html                      # landcover share
