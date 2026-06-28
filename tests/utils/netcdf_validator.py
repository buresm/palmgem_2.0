from netCDF4 import Dataset

# Minimum set of variables required in every PALM static driver
REQUIRED_VARIABLES = [
    'x', 'y',
    'crs',
    'lat', 'lon',
    'E_UTM', 'N_UTM',
    'zt',
    'vegetation_type',
    'pavement_type',
    'water_type',
    'soil_type',
]

# Variables present only when buildings are included
BUILDING_VARIABLES = [
    'buildings_2d',
    'building_id',
]


def validate_palm_static_driver(nc_path, check_buildings=False):
    """
    Returns a list of error strings for a PALM static driver NetCDF file.
    Empty list means the file is valid.
    """
    errors = []

    try:
        ds = Dataset(nc_path, 'r')
    except Exception as e:
        return [f"Cannot open file: {e}"]

    try:
        required = REQUIRED_VARIABLES + (BUILDING_VARIABLES if check_buildings else [])
        for var in required:
            if var not in ds.variables:
                errors.append(f"Missing required variable: '{var}'")

        if 'x' in ds.variables and 'y' in ds.variables:
            if 'x' not in ds.dimensions:
                errors.append("Dimension 'x' not found")
            if 'y' not in ds.dimensions:
                errors.append("Dimension 'y' not found")

        required_global_attrs = ['Conventions', 'origin_x', 'origin_y', 'origin_lat', 'origin_lon']
        for attr in required_global_attrs:
            if attr not in ds.ncattrs():
                errors.append(f"Missing global attribute: '{attr}'")

    finally:
        ds.close()

    return errors
