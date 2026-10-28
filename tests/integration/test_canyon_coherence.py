"""Canyon orientation coherence check (PG-74) against a live PostGIS.

Builds a throw-away schema with two SLUrb cells: one on a straight street
(coherence ~1 -> orientation kept) and one at a four-way junction
(coherence ~0 -> orientation set to fill = isotropic canyon).
"""
import pytest

from src.config_loader import load_config
from src.tasks.netcdf_generator import SlurbDriverGen

SCHEMA = 'pytest_pg74_coherence'
SRID = 32633


@pytest.fixture
def coherence_case(db):
    db.execute(f'drop schema if exists "{SCHEMA}" cascade; create schema "{SCHEMA}"')
    db.execute(f'''
        create table "{SCHEMA}".grid_slurb (id int, point geometry(point, {SRID}),
                                            street_canyon_orientation double precision);
        insert into "{SCHEMA}".grid_slurb values
            (1, st_setsrid(st_point(0, 0), {SRID}), 90.0),        -- straight E-W street
            (2, st_setsrid(st_point(1000, 0), {SRID}), 45.0),     -- junction
            (3, st_setsrid(st_point(5000, 0), {SRID}), 10.0);     -- no street nearby
        create table "{SCHEMA}".centerline_simplified_segments (geom geometry(linestring, {SRID}));
        insert into "{SCHEMA}".centerline_simplified_segments values
            (st_setsrid(st_makeline(st_point(-100, 5), st_point(100, 5)), {SRID})),
            (st_setsrid(st_makeline(st_point(900, 0), st_point(1100, 0)), {SRID})),
            (st_setsrid(st_makeline(st_point(1000, -100), st_point(1000, 100)), {SRID}));
    ''')
    yield
    db.execute(f'drop schema if exists "{SCHEMA}" cascade')


class _Driver(SlurbDriverGen):
    def __init__(self, cfg, db):
        self.cfg, self.db = cfg, db


def _orientations(db):
    return dict(db.fetch(f'select id, street_canyon_orientation from "{SCHEMA}".grid_slurb'))


@pytest.mark.integration
def test_junction_becomes_isotropic_straight_street_kept(db, coherence_case):
    cfg = load_config('')
    cfg.domain.update_setting('case_schema', SCHEMA)
    cfg.update_setting('canyon_orientation_min_coherence', 0.4)
    _Driver(cfg, db)._apply_canyon_coherence()
    o = _orientations(db)
    assert o[1] == 90.0          # one street direction: kept
    assert o[2] is None          # crossing streets cancel: isotropic
    assert o[3] is None          # no street within the radius: isotropic


@pytest.mark.integration
def test_threshold_zero_disables_the_check(db, coherence_case):
    cfg = load_config('')
    cfg.domain.update_setting('case_schema', SCHEMA)
    cfg.update_setting('canyon_orientation_min_coherence', 0.0)
    _Driver(cfg, db)._apply_canyon_coherence()
    assert _orientations(db) == {1: 90.0, 2: 45.0, 3: 10.0}
