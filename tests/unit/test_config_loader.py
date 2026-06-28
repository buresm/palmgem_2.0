import yaml
import pytest
import src.config_loader  # registers !join constructor as a side-effect
from src.config_loader import ConfigObj, load_config


class TestConfigObj:

    def test_get_existing_key(self):
        c = ConfigObj()
        c._ingest_dict({'foo': 42})
        assert c.get('foo') == 42

    def test_get_missing_key_returns_none(self):
        c = ConfigObj()
        assert c.get('missing') is None

    def test_get_missing_key_returns_default(self):
        c = ConfigObj()
        assert c.get('missing', 99) == 99

    def test_dot_notation_access(self):
        c = ConfigObj()
        c._ingest_dict({'section': {'key': 'value'}})
        assert c.section.key == 'value'

    def test_getitem(self):
        c = ConfigObj()
        c._ingest_dict({'key': 'val'})
        assert c['key'] == 'val'

    def test_missing_attr_raises(self):
        c = ConfigObj()
        with pytest.raises(AttributeError):
            _ = c.missing

    def test_merge_precedence_later_wins(self):
        c = ConfigObj()
        c._ingest_dict({'a': 1})
        c._ingest_dict({'a': 2})
        assert c.a == 2

    def test_nested_merge_preserves_untouched_keys(self):
        c = ConfigObj()
        c._ingest_dict({'db': {'host': 'localhost', 'port': 5432}})
        c._ingest_dict({'db': {'host': 'remotehost'}})
        assert c.db.host == 'remotehost'
        assert c.db.port == 5432

    def test_update_setting_creates_new_key(self):
        c = ConfigObj()
        c.update_setting('foo', 'bar')
        assert c.foo == 'bar'

    def test_update_setting_overwrites_existing(self):
        c = ConfigObj()
        c._ingest_dict({'foo': 1})
        c.update_setting('foo', 2)
        assert c.foo == 2

    def test_update_setting_force_new_false_skips_missing(self):
        c = ConfigObj()
        c.update_setting('nonexistent', 42, force_new=False)
        with pytest.raises(AttributeError):
            _ = c.nonexistent

    def test_update_setting_nested_section(self):
        c = ConfigObj()
        c._ingest_dict({'domain': {'dx': 10}})
        c.domain.update_setting('dx', 5)
        assert c.domain.dx == 5

    def test_list_values_are_preserved(self):
        c = ConfigObj()
        c._ingest_dict({'items': [1, 2, 3]})
        assert c.items == [1, 2, 3]


class TestJoinTag:

    def test_join_concatenates_strings(self):
        result = yaml.full_load("val: !join ['hello', ' ', 'world']")
        assert result['val'] == 'hello world'

    def test_join_mixed_types(self):
        result = yaml.full_load("val: !join ['x*', 0.5]")
        assert result['val'] == 'x*0.5'

    def test_join_single_element(self):
        result = yaml.full_load("val: !join ['only']")
        assert result['val'] == 'only'


class TestLoadConfig:

    def test_loads_without_user_config(self):
        cfg = load_config('')
        assert cfg is not None

    def test_domain_defaults_present(self):
        cfg = load_config('')
        assert cfg.domain.dx == 10.0
        assert cfg.domain.nx == 128
        assert cfg.domain.ny == 128

    def test_lsm_config_merged(self):
        cfg = load_config('')
        assert cfg.ground.nzsoil == 8
        assert cfg.type_range.building_min == 900
        assert cfg.type_range.vegetation_min == 100

    def test_tree_config_merged(self):
        cfg = load_config('')
        assert cfg.trees.nhv == 10
        assert cfg.canopy.using_lai is False

    def test_usm_config_merged(self):
        cfg = load_config('')
        assert cfg.walls.wall_directions is not None
        assert len(cfg.walls.wall_directions) == 4

    def test_fill_values_present(self):
        cfg = load_config('')
        assert cfg.fill_values['f4'] == -9999.0
        assert cfg.fill_values['b'] == -127

    def test_cfg_get_method(self):
        cfg = load_config('')
        assert cfg.get('multipolygon') is True
        assert cfg.get('nonexistent_key', 'fallback') == 'fallback'

    def test_output_dirs_created(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        load_config('')
        assert (tmp_path / 'output').is_dir()
        assert (tmp_path / 'logs').is_dir()
        assert (tmp_path / 'visual_check').is_dir()
