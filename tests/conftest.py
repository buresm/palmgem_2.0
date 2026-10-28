import pytest
from src.database import Database
from src.config_loader import load_config

@pytest.fixture(scope="session")
def cfg():
    return load_config(config_path="test.yaml", config_folder='tests/configs')

@pytest.fixture(scope="session")
def db(cfg):
    """Provides a single, persistent DB connection for the entire session.

    Skips (instead of erroring) when no database is reachable, so the
    integration tests report *why* they did not run. Note that PALM_GEM_DB_*
    variables in .env override the database section of tests/configs/test.yaml.
    """
    params = cfg.database._settings
    try:
        db_instance = Database(params, cfg.pg_owner, retries=1)
    except Exception as e:
        pytest.skip(f"no PostGIS database at {params.get('host')}:{params.get('port')} "
                    f"(set PALM_GEM_DB_* in .env or the shell): {e}")
    yield db_instance
    db_instance.close() # Teardown after all tests finish
