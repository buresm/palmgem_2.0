import pytest
from src.database import Database
from src.config_loader import load_config

@pytest.fixture(scope="session")
def cfg():
    return load_config(config_path="test.yaml", config_folder='tests/configs')

@pytest.fixture(scope="session")
def db(cfg):
    """Provides a single, persistent DB connection for the entire session."""
    db_instance = Database(cfg.database._settings, cfg.pg_owner)
    yield db_instance
    db_instance.close() # Teardown after all tests finish