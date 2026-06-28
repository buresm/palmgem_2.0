"""Unit tests for staged-run capability-flag derivation (no live DB needed)."""
import pytest
from src.config_loader import ConfigObj
from src.utils.capabilities import ensure_capability_flags, ensure_domain_geometry


def _make_cfg(**flags):
    cfg = ConfigObj()
    cfg._ingest_dict({
        'domain': {'case_schema': 'test_case'},
        'tables': {
            'surface_params': 'surface_params',
            'landcover': 'landcover',
            'buildings_height': 'buildings',
            'extras_shp': 'extras_shp',
            'extras': 'extras',
            'roofs': 'roofs',
            'walls': 'walls',
            'grid': 'grid',
            'trees': 'trees',
        },
        'type_range': {'building_min': 900, 'building_max': 999},
        'landcover': {'surface_fractions': False},
    })
    for k, v in flags.items():
        cfg.update_setting(k, v)
    return cfg


class FakeDB:
    """Answers information_schema/exists/count probes without a real database."""

    def __init__(self, tables=(), columns=(), building_count=0, min_height=None):
        self.tables = set(tables)
        self.columns = set(columns)          # set of (table, column)
        self.building_count = building_count
        self.min_height = min_height         # answer to select min(height)
        self.queried = False

    def fetchone(self, query, params=None):
        self.queried = True
        q = query.lower()
        if 'information_schema.tables' in q:
            _schema, table = params
            return table in self.tables
        if 'information_schema.columns' in q:
            _schema, table, column = params
            return (table, column) in self.columns
        if 'count(*)' in q:
            return self.building_count
        if 'min(height)' in q:
            return self.min_height
        raise AssertionError(f'unexpected query: {query}')


def test_noop_when_all_flags_present():
    """Full single-process run: flags already set -> never touches the DB."""
    cfg = _make_cfg(has_buildings=True, has_3d_buildings=True,
                    has_surface_params=True, lod2=True, has_trees=True)
    db = FakeDB()
    ensure_capability_flags(cfg, db)
    assert db.queried is False
    # values are left exactly as initialize_domain set them
    assert cfg.has_buildings is True
    assert cfg.lod2 is True
    assert cfg.has_trees is True


def test_has_trees_derived_from_table():
    """A trees table in the case schema -> has_trees; absent -> False."""
    cfg = _make_cfg()
    db = FakeDB(tables={'trees'})
    ensure_capability_flags(cfg, db)
    assert cfg.has_trees is True

    cfg_none = _make_cfg()
    ensure_capability_flags(cfg_none, FakeDB())
    assert cfg_none.has_trees is False


def test_buildings_from_landcover_rows():
    """No buildings raster but building-type rows in landcover -> has_buildings."""
    cfg = _make_cfg()
    db = FakeDB(tables={'landcover'}, building_count=7)
    ensure_capability_flags(cfg, db)
    assert cfg.has_buildings is True
    assert cfg.has_3d_buildings is False
    assert cfg.has_surface_params is False
    assert cfg.lod2 is False


def test_buildings_from_raster_without_count():
    """A buildings_height raster alone is enough for has_buildings."""
    cfg = _make_cfg()
    db = FakeDB(tables={'buildings'})
    ensure_capability_flags(cfg, db)
    assert cfg.has_buildings is True


def test_lod2_when_surface_params_and_geometry_present():
    cfg = _make_cfg()
    db = FakeDB(tables={'surface_params', 'landcover', 'roofs', 'walls'},
                columns={('landcover', 'catland')})
    ensure_capability_flags(cfg, db)
    assert cfg.has_surface_params is True
    assert cfg.lod2 is True


def test_lod2_disabled_by_surface_fractions():
    cfg = _make_cfg()
    cfg.landcover.update_setting('surface_fractions', True)
    db = FakeDB(tables={'surface_params', 'landcover', 'roofs', 'walls'},
                columns={('landcover', 'catland')})
    ensure_capability_flags(cfg, db)
    assert cfg.has_surface_params is True
    assert cfg.lod2 is False


def test_3d_buildings_when_extras_present():
    cfg = _make_cfg()
    db = FakeDB(tables={'extras_shp', 'extras'})
    ensure_capability_flags(cfg, db)
    assert cfg.has_3d_buildings is True


def test_missing_flags_are_filled_not_overridden():
    """If some flags exist already, only the missing ones are derived."""
    cfg = _make_cfg(has_buildings=False)  # explicitly set False
    db = FakeDB(tables={'buildings'})     # DB would say True...
    ensure_capability_flags(cfg, db)
    # ...but has_buildings was already present, so it must stay False
    assert cfg.has_buildings is False
    # the others get derived
    assert cfg.has_3d_buildings is False


# --- ensure_domain_geometry ------------------------------------------------

def test_domain_geometry_noop_when_oro_min_present():
    """Full single-process run: oro_min already set -> never touches the DB."""
    cfg = _make_cfg()
    cfg.domain.update_setting('oro_min', 42.0)
    db = FakeDB(min_height=999.0)  # DB would say something else
    ensure_domain_geometry(cfg, db)
    assert db.queried is False
    assert cfg.domain.oro_min == 42.0


def test_domain_geometry_auto_origin_derives_from_grid():
    """origin_z == -1 (auto): both origin_z and oro_min come from min(height)."""
    cfg = _make_cfg()
    cfg.domain.update_setting('origin_z', -1)
    db = FakeDB(min_height=205.0)
    ensure_domain_geometry(cfg, db)
    assert cfg.domain.oro_min == 205.0
    assert cfg.domain.origin_z == 205.0


def test_domain_geometry_predefined_origin_no_grid_query():
    """A predefined origin_z is reused for oro_min without querying the grid."""
    cfg = _make_cfg()
    cfg.domain.update_setting('origin_z', 120.0)
    db = FakeDB(min_height=999.0)
    ensure_domain_geometry(cfg, db)
    assert db.queried is False
    assert cfg.domain.oro_min == 120.0
    assert cfg.domain.origin_z == 120.0


def test_domain_geometry_null_grid_defaults_to_zero():
    """Empty grid (min(height) is NULL) falls back to 0.0 like initialize_domain."""
    cfg = _make_cfg()
    cfg.domain.update_setting('origin_z', -1)
    db = FakeDB(min_height=None)
    ensure_domain_geometry(cfg, db)
    assert cfg.domain.oro_min == 0.0
    assert cfg.domain.origin_z == 0.0
