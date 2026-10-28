"""Unit tests for GisImporter data_imports section handling (no live DB needed)."""
from src.config_loader import ConfigObj
from src.tasks.gis_importer import GisImporter


def _make_importer(data_imports):
    cfg = ConfigObj()
    cfg._ingest_dict({'data_imports': data_imports})
    # bypass BaseTask.__init__ — _import_section only touches self.cfg
    imp = GisImporter.__new__(GisImporter)
    imp.cfg = cfg
    return imp


def test_both_sections_present():
    imp = _make_importer({
        'vectors': {'landcover': {'path': 'a.shp', 'table': 'landcover', 'srid': 32633}},
        'rasters': {'dem': {'path': 'd.tif', 'table': 'dem', 'srid': 32633}},
    })
    assert list(imp._import_section('vectors')) == ['landcover']
    assert list(imp._import_section('rasters')) == ['dem']


def test_vectors_only_config():
    """rasters key absent entirely (user data_imports replaces defaults wholesale)."""
    imp = _make_importer({
        'vectors': {'landcover': {'path': 'a.shp', 'table': 'landcover', 'srid': 32633}},
    })
    assert list(imp._import_section('vectors')) == ['landcover']
    assert imp._import_section('rasters') == {}


def test_rasters_only_config():
    imp = _make_importer({
        'rasters': {'dem': {'path': 'd.tif', 'table': 'dem', 'srid': 32633}},
    })
    assert imp._import_section('vectors') == {}
    assert list(imp._import_section('rasters')) == ['dem']


def test_empty_section_value():
    """a present-but-empty section (e.g. `vectors:` with nothing under it)."""
    imp = _make_importer({'vectors': None, 'rasters': {}})
    assert imp._import_section('vectors') == {}
    assert imp._import_section('rasters') == {}
