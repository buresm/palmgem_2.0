"""Cut-cell topography (do_cct) end to end against a live PostGIS.

box case (synthetic, ~20 s)
    One 10 x 10 x 10 m building on flat ground (tests/utils/cct_box_case.py).
    initialize_domain -> cct_driver must write a static driver whose CCT mesh
    passes PIDS and the CCT validation with no finding at all: watertight,
    every grid column covered exactly once, roof at the building height,
    building ids matching building_id. A second, driver-only run must reuse the
    stored geometry.

Prague smoke test (real data, ~2 min, skipped without inputs_prague_lod2)
    A 64 x 64 m patch at 1 m around an isolated building of the Prague LOD2
    example, run with its LOD2 inputs present (do_cct must switch LOD2 off):
    no errors, no split vertices, nearly every column covered exactly once.

Both write into a temporary directory and drop their schemas afterwards.
"""
from pathlib import Path

import netCDF4
import numpy as np
import pytest

from src.config_loader import load_config
from src.tasks.factory import TaskFactory
from src.utils.cct_validation import check_cct_geometry, load_mesh
from src.utils.pids import load_pids_spec, validate_file
from tests.utils import cct_box_case as box


def _run(cfg, db, tasks):
    factory = TaskFactory(cfg, db)
    factory.get('setup').run()
    for name in tasks:
        factory.get(name).run()


def _footprint(m, faces):
    total = 0.0
    for f in faces:
        vs = m['faces'][:int(m['nvert'][f]), f]
        px, py = m['vert'][2, vs], m['vert'][1, vs]
        total += 0.5 * abs(np.dot(px, np.roll(py, -1)) - np.dot(py, np.roll(px, -1)))
    return total


@pytest.fixture(scope='module')
def box_driver(db, tmp_path_factory):
    static_file = str(tmp_path_factory.mktemp('cct_box') / 'box_static.nc')
    cfg = box.box_config(static_file)
    box.build_inputs(db)
    _run(cfg, db, cfg.run_tasks)
    yield cfg, static_file
    db.execute(f'drop schema if exists "{box.INPUT_SCHEMA}" cascade; '
               f'drop schema if exists "{box.CASE_SCHEMA}" cascade')


@pytest.mark.integration
def test_box_driver_passes_pids_and_cct_validation(box_driver):
    cfg, path = box_driver
    findings = validate_file(path, load_pids_spec(cfg), 'static')
    errors = [f.message for f in findings if f.level == 'error']
    cct = [f.message for f in findings if f.message.startswith('CCT')]
    assert errors == [], errors
    assert cct == [], cct


@pytest.mark.integration
def test_box_mesh_is_watertight_and_matches_the_building(box_driver):
    _, path = box_driver
    with netCDF4.Dataset(path) as ds:
        _, stats = check_cct_geometry(ds)
        m = load_mesh(ds)
        building_ids = set(np.ma.compressed(ds.variables['building_id'][:]).astype(int).tolist())

    assert stats['open_interior_edges'] == 0
    assert stats['nonmanifold_edges'] == 0
    assert stats['unused_vertices'] == 0
    assert stats['faces_per_cell_max'] == 1
    assert stats['stairstep_columns'] == 0        # the stair-step grid follows the cut surface
    assert stats['split_vertices'] == 0
    assert stats['columns_covered_once'] == 1.0
    assert stats['projected_area_ratio'] == pytest.approx(1.0, abs=1e-9)
    assert min(stats['faces_land'], stats['faces_wall'], stats['faces_roof']) > 0

    roof = np.where(m['stype'] == 2)[0]
    # roof edges are lowered to floor(height) within slanted_pars.roofs_dist2edge,
    # which trims the footprint a little at the corners
    assert _footprint(m, roof) == pytest.approx(box.BOX ** 2, rel=0.03)
    # origin_z is half a cell below the ground, so the roof top is at HEIGHT + dz/2
    assert m['vert'][0].max() == pytest.approx(box.HEIGHT + box.DX / 2)
    urban = m['stype'] > 0
    assert set(m['bid'][urban].tolist()) == building_ids
    assert set(m['building'][urban].tolist()) == {1}                 # type 901
    assert set(m['vegetation'][m['stype'] == 0].tolist()) == {3}     # short grass, 103


@pytest.mark.integration
def test_driver_only_run_reuses_the_geometry(db, box_driver, tmp_path):
    cfg, path = box_driver
    again = str(tmp_path / 'again_static.nc')
    cfg.domain.update_setting('static_driver_file', again)
    task = TaskFactory(cfg, db).get('cct_driver')
    assert task.cct_geometry_complete()
    _run(cfg, db, ['cct_driver'])
    with netCDF4.Dataset(path) as a, netCDF4.Dataset(again) as b:
        assert len(a.dimensions['cct_num_faces']) == len(b.dimensions['cct_num_faces'])
        np.testing.assert_array_equal(a['cct_vertices_per_face'][:], b['cct_vertices_per_face'][:])


# --- real data -------------------------------------------------------------

PRAGUE_INPUT = 'inputs_prague_lod2'
PRAGUE_CASE = 'pytest_cct_prague'


@pytest.mark.integration
@pytest.mark.slow
def test_prague_patch_end_to_end(db, tmp_path):
    exists = db.fetchone('select count(*) from information_schema.schemata where schema_name = %s',
                         (PRAGUE_INPUT,))
    if not exists:
        pytest.skip(f'input schema {PRAGUE_INPUT} not imported (run the prague_lod2 example gis_import)')
    root = Path(__file__).resolve().parents[2]
    cfg = load_config(str(root / 'examples' / 'prague_lod2' / 'prague_lod2.yaml'))
    d = cfg.domain
    d.update_setting('name', 'pytest')
    d.update_setting('scenario', 'cct_prague')
    d.update_setting('case_schema', PRAGUE_CASE)
    d.update_setting('cent_x', 460076.0)
    d.update_setting('cent_y', 5546368.0)
    d.update_setting('nx', 64)
    d.update_setting('ny', 64)
    d.update_setting('static_driver_file', str(tmp_path / 'prague_cct_static.nc'))
    cfg.update_setting('do_cct', True)
    cfg.visual_check.update_setting('enabled', False)
    cfg.slanted_pars.update_setting('do_vtk', False)
    try:
        _run(cfg, db, ['initialize_domain', 'lad', 'cct_driver'])
        assert cfg.lod2 is False
        findings = validate_file(d.static_driver_file, load_pids_spec(cfg), 'static')
        errors = [f.message for f in findings if f.level == 'error']
        assert errors == [], errors
        with netCDF4.Dataset(d.static_driver_file) as ds:
            _, stats = check_cct_geometry(ds)
        assert stats['faces_wall'] > 0 and stats['faces_roof'] > 0
        assert stats['split_vertices'] == 0
        assert stats['nonmanifold_edges'] == 0
        # known limitation: the wall/terrain merge can leave a malformed face at
        # the foot of a diagonal wall (about 0.1 % of the columns here); the
        # validation reports them, the test bounds them
        assert stats['columns_covered_once'] >= 0.99
        assert stats['open_interior_edges'] <= 0.005 * stats['faces']
    finally:
        db.execute(f'drop schema if exists "{PRAGUE_CASE}" cascade')
