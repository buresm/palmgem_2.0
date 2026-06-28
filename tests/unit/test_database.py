import pytest
from unittest.mock import MagicMock, patch, call


DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'user': 'test',
    'password': 'test',
    'database': 'testdb',
}


def make_db(mock_conn):
    """Construct a Database with a mocked connection, bypassing real network calls."""
    from src.database import Database

    mock_engine = MagicMock()
    mock_engine.raw_connection.return_value = mock_conn

    with patch('src.database.create_engine', return_value=mock_engine), \
         patch('src.database.URL.create', return_value='mock_url'):
        db = Database(DB_CONFIG, pg_owner='owner', retries=1, delay=0)

    return db


class TestDatabaseExecute:

    def test_commit_called_on_success(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.description = [('col',)]
        mock_cursor.fetchall.return_value = [('row',)]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        db = make_db(mock_conn)
        result = db.execute('SELECT 1')

        mock_conn.commit.assert_called_once()
        assert result == [('row',)]

    def test_rollback_called_on_failure(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception('SQL error')
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        db = make_db(mock_conn)

        with pytest.raises(Exception, match='SQL error'):
            db.execute('BAD SQL')

        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()

    def test_no_fetch_when_no_description(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.description = None
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        db = make_db(mock_conn)
        result = db.execute('DELETE FROM x')

        assert result is None

    def test_raises_when_connection_inactive(self):
        mock_conn = MagicMock()
        db = make_db(mock_conn)
        db.conn = None

        with pytest.raises(RuntimeError, match='not active'):
            db.execute('SELECT 1')


class TestDatabaseClose:

    def test_close_sets_conn_to_none(self):
        mock_conn = MagicMock()
        db = make_db(mock_conn)

        db.close()

        mock_conn.close.assert_called_once()
        assert db.conn is None

    def test_close_is_idempotent(self):
        mock_conn = MagicMock()
        db = make_db(mock_conn)

        db.close()
        db.close()  # second call — conn is None, should not raise

        mock_conn.close.assert_called_once()

    def test_close_noop_when_already_none(self):
        mock_conn = MagicMock()
        db = make_db(mock_conn)
        db.conn = None

        db.close()  # should not raise

        mock_conn.close.assert_not_called()


class TestDatabaseRetry:

    def test_retries_on_connection_failure(self):
        mock_engine = MagicMock()
        mock_engine.raw_connection.side_effect = [Exception('timeout'), MagicMock()]

        with patch('src.database.create_engine', return_value=mock_engine), \
             patch('src.database.URL.create', return_value='mock_url'), \
             patch('src.database.time.sleep'):
            from src.database import Database
            db = Database(DB_CONFIG, pg_owner='owner', retries=2, delay=0)

        assert mock_engine.raw_connection.call_count == 2

    def test_raises_after_all_retries_exhausted(self):
        mock_engine = MagicMock()
        mock_engine.raw_connection.side_effect = Exception('always fails')

        with patch('src.database.create_engine', return_value=mock_engine), \
             patch('src.database.URL.create', return_value='mock_url'), \
             patch('src.database.time.sleep'):
            from src.database import Database
            with pytest.raises(Exception, match='always fails'):
                Database(DB_CONFIG, pg_owner='owner', retries=3, delay=0)
