"""UrbanAtlas code -> PALM type mapping without OSM streetmaps.

The landcover finalisation (code cast, lid key, mt mapping) must run even
when process_streetmaps is off, which is the default; otherwise a classic
UrbanAtlas run leaves the landcover with raw codes and no type column.
Builds a throw-away schema with a clipped UrbanAtlas landcover table and
checks the mapping runs on its own.
"""
import pytest

from src.config_loader import load_config
from src.tasks.urban_atlas_osm import UrbanAtlasOSM

SCHEMA = 'pytest_ua_mapping'
SRID = 32633


@pytest.fixture
def ua_case(db):
    db.execute(f'drop schema if exists "{SCHEMA}" cascade; create schema "{SCHEMA}"')
    db.execute(f'''
        create table "{SCHEMA}".landcover (code text, geom geometry(polygon, {SRID}));
        insert into "{SCHEMA}".landcover values
            ('11100', st_setsrid(st_makeenvelope(0, 0, 10, 10), {SRID})),
            ('12100', st_setsrid(st_makeenvelope(10, 0, 20, 10), {SRID})),
            (null,    st_setsrid(st_makeenvelope(20, 0, 30, 10), {SRID}));  -- fill_boundary background
    ''')
    yield
    db.execute(f'drop schema if exists "{SCHEMA}" cascade')


class _Task(UrbanAtlasOSM):
    def __init__(self, cfg, db):
        self.cfg, self.db = cfg, db


def _cfg():
    cfg = load_config('')
    cfg.update_setting('input_schema', SCHEMA)
    cfg.update_setting('landcover_has_types', False)
    cfg.update_setting('clean_up', False)
    return cfg


@pytest.mark.integration
def test_mapping_runs_without_streetmaps(db, ua_case):
    cfg = _cfg()
    _Task(cfg, db).merge_urban_atlas_streetmaps(include_streetmaps=False)
    mt = {m[0]: m[1] for m in cfg.mt}
    rows = dict(db.fetch(f'select code_char, type from "{SCHEMA}".landcover'))
    assert rows['11100'] == mt[11100]          # landcover (osm_id null) branch
    assert rows['12100'] == mt[12100]
    assert rows[None] == cfg.mt_default        # no code -> mt_default
    assert db.fetchone(f'select count(distinct lid) from "{SCHEMA}".landcover') == 3


@pytest.mark.integration
def test_run_finalises_landcover_when_streetmaps_off(db, ua_case, monkeypatch):
    cfg = _cfg()
    cfg.update_setting('process_streetmaps', False)
    task = _Task(cfg, db)
    calls = []
    monkeypatch.setattr(task, 'create_envelope', lambda: None)
    monkeypatch.setattr(task, 'transform_urban_atlas', lambda: None)
    monkeypatch.setattr(task, 'transform_streetmaps', lambda: calls.append('streetmaps'))
    task.run()
    assert calls == []                         # streetmap steps skipped
    assert db.fetchone(f'select count(*) from "{SCHEMA}".landcover where type is null') == 0
