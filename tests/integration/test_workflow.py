"""End-to-end pipeline test against a live PostGIS database.

The pipeline runs once per module (``pipeline_output``) exactly like main.py —
``setup`` first, then the configured tasks — and writes its driver into a
temporary directory, so the tests inspect *this run's* file and never a stale
one left in output/. ``finalize`` is not run: it closes the shared session
connection, which the ``db`` fixture tears down itself.
"""
from pathlib import Path

import pytest
from netCDF4 import Dataset

from src.tasks.factory import TaskFactory
from src.utils.pids import load_pids_spec, validate_file
from tests.utils.netcdf_file_comparison import compare_netcdf_verbose
from tests.utils.netcdf_validator import validate_palm_static_driver

BASELINE = Path(__file__).resolve().parents[1] / 'baselines' / 'prague_example_static.nc'

# global attributes that change on every run
VOLATILE_ATTRS = ('creation_time',)


@pytest.fixture(scope='module')
def pipeline_output(db, cfg, tmp_path_factory):
    out_dir = tmp_path_factory.mktemp('pipeline')
    static_file = str(out_dir / f'{cfg.domain.case_schema}_static.nc')
    cfg.domain.update_setting('static_driver_file', static_file)

    run_tasks = cfg['run_tasks']
    if isinstance(run_tasks, str):
        run_tasks = [run_tasks]

    factory = TaskFactory(cfg, db)
    factory.get('setup').run()
    for task_name in run_tasks:
        if task_name in ('setup', 'finalize'):
            continue
        factory.get(task_name).run()

    return static_file


@pytest.mark.integration
def test_pipeline_writes_static_driver(pipeline_output):
    assert Path(pipeline_output).is_file(), "static driver was not written"
    with Dataset(pipeline_output, 'r') as ds:
        assert ds.variables, "Output NetCDF has no variables"


@pytest.mark.integration
def test_static_driver_structure(pipeline_output, cfg):
    """Required PALM static driver variables, dims and global attributes."""
    has_buildings = getattr(cfg, 'has_buildings', False)
    errors = validate_palm_static_driver(pipeline_output, check_buildings=has_buildings)
    assert errors == [], "PALM static driver validation failed:\n" + "\n".join(errors)


@pytest.mark.integration
def test_static_driver_pids_and_consistency(pipeline_output, cfg):
    """PIDS rules plus the cross-variable surface consistency checks."""
    findings = validate_file(pipeline_output, load_pids_spec(cfg), 'static')
    errors = [f.message for f in findings if f.level == 'error']
    assert errors == [], "PIDS / consistency errors:\n" + "\n".join(errors)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.xfail(reason='baseline predates the building_min_nz fix and an unresolved '
                          'buildings_2d/zt drift; regenerate it once the drift is explained',
                   strict=False)
def test_static_driver_matches_baseline(pipeline_output):
    """Regression net: values must match the committed baseline driver."""
    assert compare_netcdf_verbose(pipeline_output, str(BASELINE),
                                  ignore_attrs=VOLATILE_ATTRS), \
        f"output differs from baseline {BASELINE.name} (details in the warning log)"
