from netCDF4 import Dataset
import numpy as np
import numpy.ma as ma
from src.logger import warning, debug


def compare_netcdf_verbose(file1, file2, tolerance=1e-5, max_verbose_points=10):
    """
    Compares two NetCDF files: dimensions, global attributes, and variable data.
    Returns True if files match within tolerance, False otherwise.
    """
    ds1 = Dataset(file1, 'r')
    ds2 = Dataset(file2, 'r')
    diff_count = 0

    def log_diff(message):
        nonlocal diff_count
        diff_count += 1
        warning(f"[mismatch] {message}")

    try:
        # Dimension check
        dims1 = {k: len(v) for k, v in ds1.dimensions.items()}
        dims2 = {k: len(v) for k, v in ds2.dimensions.items()}
        for dim in set(dims1) | set(dims2):
            if dims1.get(dim) != dims2.get(dim):
                log_diff(f"dimension '{dim}': {dims1.get(dim)} vs {dims2.get(dim)}")

        # Global attribute check
        attrs1 = {a: getattr(ds1, a) for a in ds1.ncattrs()}
        attrs2 = {a: getattr(ds2, a) for a in ds2.ncattrs()}
        for attr in set(attrs1) | set(attrs2):
            if attrs1.get(attr) != attrs2.get(attr):
                log_diff(f"global attribute '{attr}': {attrs1.get(attr)!r} vs {attrs2.get(attr)!r}")

        # Variable check
        vars1 = set(ds1.variables.keys())
        vars2 = set(ds2.variables.keys())

        for var_name in vars1 - vars2:
            log_diff(f"variable '{var_name}' present in file1 but missing from file2")
        for var_name in vars2 - vars1:
            log_diff(f"variable '{var_name}' present in file2 but missing from file1")

        for var_name in vars1 & vars2:
            v1 = ds1.variables[var_name][:]
            v2 = ds2.variables[var_name][:]

            if v1.shape != v2.shape:
                log_diff(f"variable '{var_name}' shape mismatch: {v1.shape} vs {v2.shape}")
                continue

            mask1 = ma.getmaskarray(v1)
            mask2 = ma.getmaskarray(v2)
            if not np.array_equal(mask1, mask2):
                log_diff(f"variable '{var_name}' mask mismatch")
                diff_idx = np.where(mask1 != mask2)
                coords = list(zip(*diff_idx))[:max_verbose_points]
                warning(f"  > first {len(coords)} mask differences at indices: {coords}")

            d1 = ma.filled(v1.astype(float), np.nan)
            d2 = ma.filled(v2.astype(float), np.nan)
            diff_mask = ~np.isclose(d1, d2, atol=tolerance, equal_nan=True)

            if np.any(diff_mask):
                max_val_diff = np.nanmax(np.abs(d1 - d2))
                log_diff(f"variable '{var_name}' data mismatch. max diff: {max_val_diff}")
                diff_indices = np.where(diff_mask)
                coords = list(zip(*diff_indices))
                for i in range(min(len(coords), max_verbose_points)):
                    idx = coords[i]
                    warning(f"  > mismatch at {list(idx)}: baseline={d2[idx]}, current={d1[idx]} (delta={abs(d1[idx]-d2[idx])})")
                if len(coords) > max_verbose_points:
                    debug(f"  > ... and {len(coords) - max_verbose_points} more differences.")

        return diff_count == 0

    finally:
        ds1.close()
        ds2.close()
