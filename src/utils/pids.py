"""PALM Input Data Standard (PIDS) compliance validation.

Validates a driver NetCDF file against a declarative spec
(config/pids_spec.yaml): required global attributes, dimensions, coordinate
variable sanity, and per-variable rules (dims, dtype kind, required attrs).

Per-variable rule violations are reported as errors; generic expectations
(long_name/units/_FillValue on data variables) only as warnings, because the
standard leaves room for extra or tool-specific variables.
"""
import os
from collections import namedtuple
from pathlib import Path

import numpy as np
import yaml

from src.logger import progress, debug, warning, error
from src.utils.cct_validation import has_cct, check_cct_geometry

Finding = namedtuple('Finding', ['level', 'message'])

_ERROR = 'error'
_WARNING = 'warning'


def load_pids_spec(cfg):
    """Load the PIDS spec YAML configured under ``pids.spec_file``.

    A relative path resolves against the repository ``config/`` directory,
    mirroring how ``surface_params_file`` behaves.
    """
    spec_file = cfg.pids.spec_file
    if not os.path.isabs(spec_file):
        spec_file = str(Path(__file__).resolve().parents[2] / 'config' / spec_file)

    if not os.path.exists(spec_file):
        raise FileNotFoundError(f'PIDS spec file not found: {spec_file}')

    with open(spec_file, 'r') as f:
        return yaml.safe_load(f)


def validate_dataset(ds, spec_section):
    """Validate an open netCDF4 Dataset against one driver section of the spec.

    Returns a list of Finding(level, message); empty list means fully clean.
    """
    findings = []

    # 1. required global attributes
    global_attrs = set(ds.ncattrs())
    for attr in spec_section.get('required_global_attributes', []) or []:
        if attr not in global_attrs:
            findings.append(Finding(_ERROR, f'missing required global attribute: {attr}'))

    # plausibility of the geo-referencing attributes when present
    if 'origin_lat' in global_attrs:
        lat = float(ds.getncattr('origin_lat'))
        if not -90.0 <= lat <= 90.0:
            findings.append(Finding(_ERROR, f'origin_lat out of range [-90, 90]: {lat}'))
    if 'origin_lon' in global_attrs:
        lon = float(ds.getncattr('origin_lon'))
        if not -180.0 <= lon <= 180.0:
            findings.append(Finding(_ERROR, f'origin_lon out of range [-180, 180]: {lon}'))

    # 2. required dimensions
    for dim in spec_section.get('required_dimensions', []) or []:
        if dim not in ds.dimensions:
            findings.append(Finding(_ERROR, f'missing required dimension: {dim}'))
        elif len(ds.dimensions[dim]) == 0:
            findings.append(Finding(_ERROR, f'required dimension has zero length: {dim}'))

    # 3. coordinate variables: 1-D, strictly monotonic, uniformly spaced
    coord_vars = spec_section.get('coordinate_variables', []) or []
    for cv in coord_vars:
        if cv not in ds.variables:
            continue
        var = ds.variables[cv]
        if var.ndim != 1:
            findings.append(Finding(_ERROR, f'coordinate variable {cv} is not 1-D'))
            continue
        vals = np.asarray(var[:], dtype='f8')
        if vals.size < 2:
            continue
        steps = np.diff(vals)
        if not np.all(steps > 0):
            findings.append(Finding(_ERROR, f'coordinate variable {cv} is not strictly increasing'))
        elif not np.allclose(steps, steps[0], rtol=1e-6, atol=1e-9):
            findings.append(Finding(_WARNING, f'coordinate variable {cv} is not uniformly spaced'))

    # 4. generic expectations on data variables
    exempt = set(coord_vars) | set(spec_section.get('exempt_variables', []) or [])
    rules = spec_section.get('variable_rules', {}) or {}
    for vn, var in ds.variables.items():
        if vn in exempt or var.ndim < 2:
            continue
        var_attrs = set(var.ncattrs())
        if 'long_name' not in var_attrs:
            findings.append(Finding(_WARNING, f'variable {vn}: missing long_name attribute'))
        if 'units' not in var_attrs:
            findings.append(Finding(_WARNING, f'variable {vn}: missing units attribute'))
        if '_FillValue' not in var_attrs:
            findings.append(Finding(_WARNING, f'variable {vn}: missing _FillValue'))

    # 5. per-variable hard rules
    for vn, rule in rules.items():
        if vn not in ds.variables:
            # a spec rule does not make the variable mandatory: drivers
            # legitimately omit variables their case does not use
            continue
        var = ds.variables[vn]

        expected_dims = rule.get('dims')
        if expected_dims and list(var.dimensions) != list(expected_dims):
            findings.append(Finding(
                _ERROR, f'variable {vn}: dimensions {list(var.dimensions)} '
                        f'do not match PIDS {list(expected_dims)}'))

        dtype_kind = rule.get('dtype_kind')
        if dtype_kind and var.dtype.kind != dtype_kind:
            findings.append(Finding(
                _ERROR, f'variable {vn}: dtype kind {var.dtype.kind!r} '
                        f'does not match PIDS {dtype_kind!r}'))

        for attr in rule.get('required_attrs', []) or []:
            present = attr in var.ncattrs()
            if not present:
                findings.append(Finding(_ERROR, f'variable {vn}: missing required attribute {attr}'))

    # 6. cross-variable consistency: True / 'static' -> static driver rules,
    # 'slurb' -> SLURB driver rules
    rule_set = spec_section.get('consistency_checks')
    if rule_set is True or rule_set == 'static':
        findings.extend(check_static_consistency(ds))
    elif rule_set == 'slurb':
        findings.extend(check_slurb_consistency(ds))

    # 7. cut-cell topography mesh (static drivers written by cct_driver)
    if has_cct(ds):
        cct_findings, cct_stats = check_cct_geometry(ds)
        findings.extend(Finding(level, msg) for level, msg in cct_findings)
        if cct_stats:
            progress('CCT mesh: {faces} faces ({faces_land} land, {faces_wall} wall, {faces_roof} roof), '
                     '{vertices} vertices; columns covered once {columns_covered_once:.1%}, '
                     'projected area / domain {projected_area_ratio:.3f}', **cct_stats)

    return findings


_SURFACE_TYPES = ('vegetation_type', 'pavement_type', 'water_type', 'building_type')
_BUILDING_VARS = ('buildings_2d', 'building_id', 'building_type')


def _defined(ds, vn):
    """Boolean (y, x) mask of cells where a 2-D variable holds a value."""
    return ~np.ma.getmaskarray(ds.variables[vn][:])


def check_static_consistency(ds):
    """Cross-variable rules a static driver must satisfy to describe each
    surface cell exactly once. Every rule here is something the per-variable
    checks cannot see: each variable is fine on its own, but together they
    contradict each other.

    Returns a list of Finding; empty means consistent.
    """
    findings = []
    v = ds.variables

    # terrain must be defined everywhere
    if 'zt' in v:
        n_bad = int((~_defined(ds, 'zt')).sum())
        if n_bad:
            findings.append(Finding(_ERROR, f'zt: {n_bad} cell(s) without terrain height'))

    # with LSM or USM on, PALM needs all four LSM classifications in the file,
    # even when one is fill everywhere (netcdf_data_input_check_static, DRV0011).
    # building_type is needed too with USM on; it is not checked here because a
    # driver without buildings (e.g. SLURB mode) is valid for runs without USM
    missing = [vn for vn in ('vegetation_type', 'pavement_type', 'water_type', 'soil_type') if vn not in v]
    if missing:
        findings.append(Finding(_ERROR, f'{", ".join(missing)} missing: PALM with the land or urban '
                                        f'surface model needs all four surface classifications (DRV0011)'))

    # every cell carries a surface type; at most one LSM type (more only with
    # surface_fraction, which says how the types share the cell); a building
    # and an LSM type together only under a 3-D building that is hollow at the
    # ground (bridge, overhang: buildings_3d[0] == 0 with the LSM surface below)
    present = [vn for vn in _SURFACE_TYPES if vn in v]
    if present:
        n_types = sum(_defined(ds, vn).astype(int) for vn in present)
        n_none = int((n_types == 0).sum())
        if n_none:
            findings.append(Finding(_ERROR, f'{n_none} cell(s) without any surface type '
                                            f'({", ".join(present)})'))
        lsm = [vn for vn in present if vn != 'building_type']
        n_lsm = sum(_defined(ds, vn).astype(int) for vn in lsm) if lsm else 0
        n_multi = int(np.sum(n_lsm > 1))
        if n_multi:
            level = _WARNING if 'surface_fraction' in v else _ERROR
            findings.append(Finding(level, f'{n_multi} cell(s) with more than one LSM surface type'
                                           + (' (surface_fraction present)' if level == _WARNING else '')))
        if 'building_type' in v and lsm:
            overlap = _defined(ds, 'building_type') & (n_lsm > 0)
            if 'buildings_3d' in v:
                ground = np.ma.filled(v['buildings_3d'][0, :, :], 0) == 1
                overlap &= ground
            n_overlap = int(overlap.sum())
            if n_overlap:
                findings.append(Finding(_ERROR, f'{n_overlap} building cell(s) that also carry an LSM '
                                                f'surface type (only valid under a building that is '
                                                f'hollow at the ground)'))

    # building variables describe the same set of cells
    bvars = [vn for vn in _BUILDING_VARS if vn in v]
    if len(bvars) > 1:
        ref = _defined(ds, bvars[0])
        for vn in bvars[1:]:
            n_diff = int((ref != _defined(ds, vn)).sum())
            if n_diff:
                findings.append(Finding(_ERROR, f'{bvars[0]} and {vn} disagree on '
                                                f'{n_diff} building cell(s)'))

    # a building cell must have a building in it
    if 'buildings_2d' in v:
        heights = v['buildings_2d'][:]
        n_flat = int(((~np.ma.getmaskarray(heights)) & (np.ma.filled(heights, 1.0) <= 0)).sum())
        if n_flat:
            findings.append(Finding(_ERROR, f'buildings_2d: {n_flat} building cell(s) with height <= 0'))

    # soil underneath every vegetation / pavement cell
    if 'soil_type' in v:
        needs_soil = np.zeros(v['soil_type'].shape, dtype=bool)
        for vn in ('vegetation_type', 'pavement_type'):
            if vn in v:
                needs_soil |= _defined(ds, vn)
        n_bare = int((needs_soil & ~_defined(ds, 'soil_type')).sum())
        if n_bare:
            findings.append(Finding(_ERROR, f'soil_type: {n_bare} vegetation/pavement cell(s) without soil type'))

    findings.extend(check_building_fractions(ds))
    return findings


# PALM (usm_init) stops with 'relative material fractions do not sum-up to one
# at some surfaces' when wall + window + green of a surface is off 1 by more
# than this
_FRACTION_TOL = 1e-5
# building_fraction (building_surface_type): wall, window, green index per level
_FRACTION_LEVELS = {'ground floor': (0, 3, 6), 'upper floors': (1, 4, 7), 'roof': (2, 5, 8)}


def check_building_fractions(ds):
    """Wall + window + green fractions must sum to 1, as PALM checks them.

    building_fraction holds them per column and level (indices of
    _FRACTION_LEVELS), building_surface_pars per surface (0 wall, 1 window,
    2 green on wall, 3 green on roof; PALM lets the roof green overwrite the
    wall green). PALM fills an undefined fraction from the building type, so
    only fully defined sets are summed; a level that defines wall or window
    but not both is reported as a warning (the mix with the type default
    rarely sums to 1).
    """
    findings = []
    v = ds.variables

    def sums_off(wall, win, green):
        total = wall.astype(float) + win.astype(float) + green.astype(float)
        bad = ~np.ma.getmaskarray(total) & (np.abs(np.ma.filled(total, 1.0) - 1.0) > _FRACTION_TOL)
        return bad, np.ma.filled(total, np.nan)

    def sample(total, bad):
        vals = np.unique(np.round(total[bad], 3))
        return ', '.join(f'{x:g}' for x in vals[:5]) + (', ...' if vals.size > 5 else '')

    if 'building_fraction' in v and v['building_fraction'].shape[0] >= 9:
        bf = v['building_fraction'][:]
        for level, (iw, iwi, ig) in _FRACTION_LEVELS.items():
            bad, total = sums_off(bf[iw], bf[iwi], bf[ig])
            if bad.any():
                findings.append(Finding(_ERROR, f'building_fraction ({level}): wall + window + green '
                                                f'not 1 in {int(bad.sum())} cell(s) (sums {sample(total, bad)})'))
            n_half = int((np.ma.getmaskarray(bf[iw]) != np.ma.getmaskarray(bf[iwi])).sum())
            if n_half:
                findings.append(Finding(_WARNING, f'building_fraction ({level}): wall or window fraction '
                                                  f'undefined in {n_half} cell(s) where the other is set'))

    if 'building_surface_pars' in v and v['building_surface_pars'].shape[0] >= 4:
        sp = v['building_surface_pars'][:4]
        green = np.ma.where(np.ma.getmaskarray(sp[3]), sp[2], sp[3])
        bad, total = sums_off(sp[0], sp[1], green)
        if bad.any():
            findings.append(Finding(_ERROR, f'building_surface_pars: wall + window + green not 1 on '
                                            f'{int(bad.sum())} surface(s) (sums {sample(total, bad)})'))
        n_half = int((np.ma.getmaskarray(sp[0]) != np.ma.getmaskarray(sp[1])).sum())
        if n_half:
            findings.append(Finding(_WARNING, f'building_surface_pars: wall or window fraction undefined on '
                                              f'{n_half} surface(s) where the other is set'))

    return findings


# SLUrb ignores cells below this urban fraction (PIDS_SLURB: "fr_urb < 0.01")
_SLURB_MIN_URBAN = 0.01
# SLUrb "does not perform very well with deep urban canopies (>60 m)"
_SLURB_MAX_HEIGHT = 60.0
# beyond these the street canyon is degenerate (nearly no street between the
# buildings, or far deeper than real streets); the driver caps both by default
_SLURB_MAX_PLAN_URBAN = 0.95
_SLURB_MAX_ASPECT = 10.0
# per-cell inputs without a usable PALM default (slurb_init, PALM 25.10):
# variable -> SLUrb namelist parameter. A variable in the driver overrides the
# namelist in every SLUrb cell, and a fill value there aborts (SLU0022); left
# out of the driver, the namelist value is used in every cell, and unset it
# is undefined memory (SLU0019 with values like 1e-319). Everything else
# SLUrb reads falls back to its building/pavement type tables.
_SLURB_CELL_VARS = {'building_plan_area_fraction': 'building_plan_area_fraction',
                    'building_frontal_area_fraction': 'building_frontal_area_fraction',
                    'building_height': 'building_height',
                    'street_canyon_aspect_ratio': 'street_canyon_aspect_ratio',
                    'z0_urb': 'urban_roughness_length',
                    'deep_soil_temperature': 'deep_soil_temperature'}


def _values(ds, vn):
    """(values, defined-mask) of a 2-D variable as float arrays."""
    a = ds.variables[vn][:]
    return np.ma.filled(a.astype(float), np.nan), ~np.ma.getmaskarray(a)


def check_slurb_consistency(ds):
    """Cross-variable and range rules for a SLURB driver, from the PALM
    PIDS_SLURB reference and the SLUrb guide. A SLUrb cell is a cell with
    urban_fraction > 1 % (SLUrb ignores the others).

    Errors: rules PIDS_SLURB states (plan fraction cannot exceed urban
    fraction, fractions within [0, 1], urban_fraction set (0 for non-urban)
    in every cell, positive height and aspect ratio,
    orientation in [0, 360) or fill = isotropic canyon, no fill value of a
    required input in a SLUrb cell). Warnings: required inputs not in the
    driver (they must come from the SLUrb namelist),
    deep canopies > 60 m, values written in cells SLUrb ignores.
    """
    findings = []
    v = ds.variables

    def err(msg):
        findings.append(Finding(_ERROR, msg))

    def warn(msg):
        findings.append(Finding(_WARNING, msg))

    if 'urban_fraction' not in v:
        warn('urban_fraction missing: SLUrb cannot tell urban from non-urban cells '
             '(PALM falls back to the namelist urban_fraction)')
        urban = None
    else:
        uf, uf_def = _values(ds, 'urban_fraction')
        urban = uf_def & (uf > _SLURB_MIN_URBAN)
        # slurb_init_arrays range-checks urban_fraction in every cell and does
        # not honour the fill value (SLU0032): non-urban cells must be 0
        n_fill = int((~uf_def).sum())
        if n_fill:
            err(f'urban_fraction: fill value in {n_fill} cell(s); PALM-SLUrb checks every cell '
                f'for 0..1 and aborts (SLU0032), non-urban cells must be 0')

    # value ranges
    for vn in ('building_plan_area_fraction', 'urban_fraction', 'window_fraction'):
        if vn in v:
            a, d = _values(ds, vn)
            n_bad = int((d & ((a < 0) | (a > 1))).sum())
            if n_bad:
                err(f'{vn}: {n_bad} cell(s) outside [0, 1]')
    if 'building_frontal_area_fraction' in v:
        a, d = _values(ds, 'building_frontal_area_fraction')
        n_bad = int((d & (a < 0)).sum())
        if n_bad:
            err(f'building_frontal_area_fraction: {n_bad} negative cell(s)')
    for vn in ('building_height', 'street_canyon_aspect_ratio'):
        if vn in v:
            a, d = _values(ds, vn)
            n_bad = int((d & (a <= 0)).sum())
            if n_bad:
                err(f'{vn}: {n_bad} cell(s) <= 0')
    if 'building_height' in v:
        a, d = _values(ds, 'building_height')
        n_deep = int((d & (a > _SLURB_MAX_HEIGHT)).sum())
        if n_deep:
            warn(f'building_height: {n_deep} cell(s) above {_SLURB_MAX_HEIGHT:.0f} m, where '
                 f'SLUrb "does not perform very well"')
    if 'street_canyon_orientation' in v:
        a, d = _values(ds, 'street_canyon_orientation')
        n_bad = int((d & ((a < 0) | (a >= 360))).sum())
        if n_bad:
            err(f'street_canyon_orientation: {n_bad} cell(s) outside [0, 360) '
                f'(use the fill value for an isotropic canyon)')

    # plan fraction cannot exceed urban fraction
    if urban is not None and 'building_plan_area_fraction' in v:
        bp, bp_def = _values(ds, 'building_plan_area_fraction')
        n_bad = int((bp_def & uf_def & (bp > uf + 1e-6)).sum())
        if n_bad:
            err(f'building_plan_area_fraction exceeds urban_fraction in {n_bad} cell(s)')
        n_orphan = int((bp_def & ~uf_def).sum())
        if n_orphan:
            err(f'building_plan_area_fraction defined in {n_orphan} cell(s) without urban_fraction')
        # SLUrb divides the plan fraction by urban_fraction: a building share
        # near 1 leaves a street canyon of ~0 width
        n_narrow = int((urban & bp_def & (bp > _SLURB_MAX_PLAN_URBAN * uf)).sum())
        if n_narrow:
            warn(f'building_plan_area_fraction above {_SLURB_MAX_PLAN_URBAN:g} x urban_fraction in '
                 f'{n_narrow} SLUrb cell(s): the street canyon there is ~0 wide '
                 f'(slurb_max_plan_urban_ratio caps it)')
    if urban is not None and 'street_canyon_aspect_ratio' in v:
        hw, hw_def = _values(ds, 'street_canyon_aspect_ratio')
        n_deep = int((urban & hw_def & (hw > _SLURB_MAX_ASPECT)).sum())
        if n_deep:
            warn(f'street_canyon_aspect_ratio above {_SLURB_MAX_ASPECT:g} in {n_deep} SLUrb cell(s), '
                 f'far beyond real streets (slurb_max_aspect_ratio caps it)')

    if urban is not None:
        # every SLUrb cell needs these inputs (see _SLURB_CELL_VARS)
        for vn, nml in _SLURB_CELL_VARS.items():
            if vn not in v:
                hint = ' (at most half the first grid spacing)' if vn == 'z0_urb' else ''
                warn(f'{vn} not in the driver: set {nml} in the SLUrb namelist{hint}; it has no '
                     f'default and PALM aborts with SLU0019 when it is unset')
                continue
            _, d = _values(ds, vn)
            n_missing = int((urban & ~d).sum())
            if n_missing:
                err(f'{vn}: fill value in {n_missing} of {int(urban.sum())} SLUrb cell(s); PALM '
                    f'aborts there (SLU0022), the namelist {nml} does not replace a value in the driver')
        # values outside SLUrb cells are ignored by the model
        for vn in tuple(_SLURB_CELL_VARS) + ('street_canyon_orientation',):
            if vn in v:
                _, d = _values(ds, vn)
                n_ignored = int((d & ~urban).sum())
                if n_ignored:
                    warn(f'{vn}: {n_ignored} cell(s) with urban_fraction <= '
                         f'{_SLURB_MIN_URBAN:.0%} carry values SLUrb ignores')

    return findings


def validate_file(path, spec, driver):
    """Validate a driver NetCDF file. ``driver`` selects the spec section
    ('static' or 'slurb'). Returns a list of Finding."""
    import netCDF4

    section = spec.get(driver)
    if section is None:
        return [Finding(_WARNING, f'no PIDS spec section for driver type {driver!r}; skipping')]

    with netCDF4.Dataset(path, 'r') as ds:
        return validate_dataset(ds, section)


def run_pids_check(cfg, path, driver, force=False):
    """Validate ``path`` and route findings to the logger.

    Called automatically after a driver is written (gated by ``pids.enabled``)
    and by the standalone ``pids_check`` task (``force=True``). With
    ``pids.strict`` any error-level finding aborts the pipeline.
    Returns the findings list (empty = clean).
    """
    if not force and not cfg.pids.enabled:
        return []

    spec = load_pids_spec(cfg)
    version = spec.get('pids_version', '?')
    progress('PIDS {} compliance check: {}', version, path)

    try:
        findings = validate_file(path, spec, driver)
    except OSError as e:
        warning(f'PIDS check could not read {path}: {e}')
        return [Finding(_WARNING, f'unreadable file: {e}')]

    n_err = sum(1 for f in findings if f.level == _ERROR)
    n_warn = len(findings) - n_err

    for f in findings:
        if f.level == _ERROR:
            error(f'PIDS: {f.message}')
        else:
            warning(f'PIDS: {f.message}')

    if not findings:
        progress('PIDS check passed with no findings')
    else:
        progress('PIDS check finished: {} error(s), {} warning(s)', n_err, n_warn)

    if n_err and cfg.pids.strict:
        raise RuntimeError(f'PIDS compliance check failed with {n_err} error(s) for {path} '
                           '(pids.strict is enabled)')

    return findings
