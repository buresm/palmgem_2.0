"""Unit tests for standardize_columns (fake DB, no live PostgreSQL needed)."""
import pytest

from src.config_loader import ConfigObj
from src.utils.attributes import standardize_columns


class FakeDb:
    """Holds the columns of one table; answers the information_schema query
    and applies `rename column` statements."""
    def __init__(self, columns):
        self.columns = list(columns)
        self.renames = []

    def execute(self, sql, params=None):
        if 'information_schema.columns' in sql:
            return [(c,) for c in self.columns]
        words = sql.split()
        old, new = words[words.index('column') + 1], words[words.index('to') + 1]
        self.columns[self.columns.index(old)] = new
        self.renames.append((old, new))
        return None


def _cfg(tree_mapping):
    cfg = ConfigObj()
    cfg._ingest_dict({
        'tables': {'trees': 'trees'},
        'attribute_mapping': {'trees': tree_mapping},
        'attribute_spec': {'trees': {'necessary': ['treeh'], 'optional': ['trunkh']}},
    })
    return cfg


def test_legacy_names_renamed_with_mapping():
    # a 1.x input schema keeps the legacy names; the case-schema copy is fixed
    db = FakeDb(['gid', 'vysstr', 'vyskmen', 'geom'])
    standardize_columns(_cfg({'treeh': 'vysstr', 'trunkh': 'vyskmen'}), db, 'case', 'trees')
    assert db.columns == ['gid', 'treeh', 'trunkh', 'geom']


def test_standard_names_left_alone():
    db = FakeDb(['gid', 'treeh', 'trunkh', 'geom'])
    standardize_columns(_cfg({'treeh': 'vysstr', 'trunkh': 'vyskmen'}), db, 'case', 'trees')
    assert db.renames == []


def test_missing_necessary_attribute_raises():
    db = FakeDb(['gid', 'vysstr', 'geom'])
    with pytest.raises(ValueError, match="attribute_mapping.trees.treeh"):
        standardize_columns(_cfg({'treeh': 'treeh', 'trunkh': 'trunkh'}), db, 'case', 'trees')


def test_missing_optional_attribute_only_warns():
    db = FakeDb(['gid', 'treeh', 'geom'])
    standardize_columns(_cfg({'treeh': 'treeh', 'trunkh': 'trunkh'}), db, 'case', 'trees')
    assert db.columns == ['gid', 'treeh', 'geom']


def test_other_tables_untouched():
    db = FakeDb(['gid', 'vysstr', 'geom'])
    standardize_columns(_cfg({'treeh': 'treeh', 'trunkh': 'trunkh'}), db, 'case', 'walls')
    assert db.renames == []
