import numpy as np
import pytest
from netCDF4 import Dataset
from tests.utils.netcdf_validator import validate_palm_static_driver, REQUIRED_VARIABLES


def _build_valid_nc(path):
    """Create a minimal but valid PALM static driver NetCDF for testing."""
    ds = Dataset(str(path), 'w', format='NETCDF4')

    ds.setncattr('Conventions', 'CF-1.7')
    ds.setncattr('origin_x', 0.0)
    ds.setncattr('origin_y', 0.0)
    ds.setncattr('origin_lat', 50.0)
    ds.setncattr('origin_lon', 14.0)

    ds.createDimension('x', 10)
    ds.createDimension('y', 10)

    ds.createVariable('x', 'f8', ('x',))[:] = np.arange(10) * 10.0
    ds.createVariable('y', 'f8', ('y',))[:] = np.arange(10) * 10.0
    ds.createVariable('crs', 'i')
    ds.createVariable('lat', 'f4', ('y', 'x'))[:] = np.full((10, 10), 50.0)
    ds.createVariable('lon', 'f4', ('y', 'x'))[:] = np.full((10, 10), 14.0)
    ds.createVariable('E_UTM', 'f8', ('y', 'x'))[:] = np.zeros((10, 10))
    ds.createVariable('N_UTM', 'f8', ('y', 'x'))[:] = np.zeros((10, 10))
    ds.createVariable('zt', 'f4', ('y', 'x'))[:] = np.zeros((10, 10))
    ds.createVariable('vegetation_type', 'i1', ('y', 'x'))[:] = np.ones((10, 10))
    ds.createVariable('pavement_type', 'i1', ('y', 'x'))[:] = np.zeros((10, 10))
    ds.createVariable('water_type', 'i1', ('y', 'x'))[:] = np.zeros((10, 10))
    ds.createVariable('soil_type', 'i1', ('y', 'x'))[:] = np.ones((10, 10))

    ds.close()


def test_valid_file_passes(tmp_path):
    nc = tmp_path / 'valid.nc'
    _build_valid_nc(nc)
    errors = validate_palm_static_driver(str(nc))
    assert errors == [], f"Unexpected errors: {errors}"


def test_missing_variable_reported(tmp_path):
    nc = tmp_path / 'missing_var.nc'

    # Build a file without 'zt'
    ds = Dataset(str(nc), 'w', format='NETCDF4')
    ds.setncattr('Conventions', 'CF-1.7')
    ds.setncattr('origin_x', 0.0)
    ds.setncattr('origin_y', 0.0)
    ds.setncattr('origin_lat', 50.0)
    ds.setncattr('origin_lon', 14.0)
    ds.createDimension('x', 10)
    ds.createDimension('y', 10)
    ds.createVariable('x', 'f8', ('x',))[:] = np.arange(10) * 10.0
    ds.createVariable('y', 'f8', ('y',))[:] = np.arange(10) * 10.0
    ds.createVariable('crs', 'i')
    ds.createVariable('lat', 'f4', ('y', 'x'))[:] = np.full((10, 10), 50.0)
    ds.createVariable('lon', 'f4', ('y', 'x'))[:] = np.full((10, 10), 14.0)
    ds.createVariable('E_UTM', 'f8', ('y', 'x'))[:] = np.zeros((10, 10))
    ds.createVariable('N_UTM', 'f8', ('y', 'x'))[:] = np.zeros((10, 10))
    # 'zt' intentionally omitted
    ds.createVariable('vegetation_type', 'i1', ('y', 'x'))[:] = np.ones((10, 10))
    ds.createVariable('pavement_type', 'i1', ('y', 'x'))[:] = np.zeros((10, 10))
    ds.createVariable('water_type', 'i1', ('y', 'x'))[:] = np.zeros((10, 10))
    ds.createVariable('soil_type', 'i1', ('y', 'x'))[:] = np.ones((10, 10))
    ds.close()

    errors = validate_palm_static_driver(str(nc))
    assert any("'zt'" in e for e in errors)


def test_missing_global_attr_reported(tmp_path):
    nc = tmp_path / 'missing_attr.nc'
    _build_valid_nc(nc)

    ds = Dataset(str(nc), 'a')
    ds.delncattr('origin_lat')
    ds.close()

    errors = validate_palm_static_driver(str(nc))
    assert any('origin_lat' in e for e in errors)


def test_building_check_optional(tmp_path):
    nc = tmp_path / 'no_buildings.nc'
    _build_valid_nc(nc)

    # Without buildings flag — no error
    errors = validate_palm_static_driver(str(nc), check_buildings=False)
    assert errors == []

    # With buildings flag — should report missing building variables
    errors = validate_palm_static_driver(str(nc), check_buildings=True)
    assert any('buildings_2d' in e for e in errors)


def test_unreadable_file_returns_error():
    errors = validate_palm_static_driver('/nonexistent/path.nc')
    assert len(errors) == 1
    assert 'Cannot open' in errors[0]
