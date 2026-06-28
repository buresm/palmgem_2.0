import glob
import pytest
from netCDF4 import Dataset
from src.tasks.factory import TaskFactory
from tests.utils.netcdf_validator import validate_palm_static_driver


@pytest.mark.integration
def test_full_pipeline_workflow(db, cfg):
    """Runs the configured tasks and verifies a valid NetCDF output is produced."""
    factory = TaskFactory(cfg, db)
    run_tasks = cfg['run_tasks']
    if isinstance(run_tasks, str):
        run_tasks = [run_tasks]

    for task_name in run_tasks:
        factory.get(task_name).run()

    nc_files = glob.glob('output/*.nc')
    assert nc_files, "No NetCDF output file found in output/"

    with Dataset(nc_files[0], 'r') as ds:
        assert ds.variables, "Output NetCDF has no variables"


@pytest.mark.integration
@pytest.mark.slow
def test_output_netcdf_structure(db, cfg):
    """
    Runs the full pipeline and validates the output NetCDF against
    the PALM static driver specification (required variables, dims, attributes).
    """
    factory = TaskFactory(cfg, db)
    run_tasks = cfg['run_tasks']
    if isinstance(run_tasks, str):
        run_tasks = [run_tasks]

    for task_name in run_tasks:
        factory.get(task_name).run()

    nc_files = glob.glob('output/*.nc')
    assert nc_files, "No NetCDF output file found in output/"

    has_buildings = getattr(cfg, 'has_buildings', False)
    errors = validate_palm_static_driver(nc_files[0], check_buildings=has_buildings)
    assert errors == [], "PALM static driver validation failed:\n" + "\n".join(errors)
