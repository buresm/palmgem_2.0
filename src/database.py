#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import psycopg2
import psycopg2.extras
import time
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from src.logger import error, verbose, warning, progress, sql_debug, sql_verbose, debug


class Database:
    """
    Core Database handler for PostGIS operations.
    Integrates with ConfigObj for settings and custom PALM-GeM logging.
    """

    def __init__(self, db_config, pg_owner, retries=5, delay=2):
        self.db_params = getattr(db_config, '_settings', db_config)
        self.pg_owner = pg_owner

        # 1. Create URL and Engine
        connection_url = URL.create(
            drivername="postgresql+psycopg2",
            username=self.db_params['user'],
            password=self.db_params['password'],
            host=self.db_params['host'],
            port=self.db_params['port'],
            database=self.db_params['database']
        )
        self.engine = create_engine(connection_url)

        # 2. Use a single connection source with retry logic
        self._connect_with_retry(retries, delay)
        debug("Database engine and connection initialized.")

    def _connect_with_retry(self, retries, delay):
        for i in range(retries):
            try:
                self.conn = self.engine.raw_connection()
                self.conn.autocommit = False
                return
            except Exception as e:
                if i < retries - 1:
                    time.sleep(delay)
                else:
                    raise e

    def execute(self, query, params=None, fetch=True):
        """
        Executes a query, handles cursor lifecycle, commits updates,
        and rolls back on failure to prevent 'InFailedSqlTransaction' errors.

        Note: this always commits, so it is the right call for mutations
        (DDL/DML, CREATE TABLE AS). For read-only SELECTs prefer fetch(),
        which does not commit.
        """
        if not self.conn:
            raise RuntimeError("Database connection is not active.")

        with self.conn.cursor() as cur:
            try:
                cur.execute(query, params)

                # Capture RAISE NOTICE logs
                sql_debug(self.conn)

                # COMMIT TRANSATION: Write structural mutations or row inserts to the disk
                self.conn.commit()

                if fetch and cur.description:
                    return cur.fetchall()
                return None

            except Exception as e:
                # CRITICAL: This clears the "poisoned" transaction state on failure
                self.conn.rollback()

                error("SQL Execution failed: {}\nQuery: {}", str(e), query)
                # We still raise the error so the Task knows it failed,
                # but the CONNECTION is now clean for the next attempt.
                raise

    def fetch(self, query, params=None):
        """Executes a query and returns all results."""
        if not self.conn:
            raise RuntimeError("Database connection is not active.")

        with self.conn.cursor() as cur:
            try:
                cur.execute(query, params)
                sql_debug(self.conn)
                if cur.description:
                    return cur.fetchall()
                return []
            except Exception as e:
                error("SQL Fetch failed: {}\nQuery: {}", str(e), query)
                raise

    def fetchone(self, query, params=None):
        """Executes a query and returns the first column of the first row.

        Returns None when the query yields no rows (instead of crashing on
        a None subscript).
        """
        if not self.conn:
            raise RuntimeError("Database connection is not active.")

        with self.conn.cursor() as cur:
            try:
                cur.execute(query, params)
                sql_debug(self.conn)
                if cur.description:
                    row = cur.fetchone()
                    return row[0] if row is not None else None
                return None
            except Exception as e:
                error("SQL Fetch failed: {}\nQuery: {}", str(e), query)
                raise

    def execute_batch(self, query, params_list, batch_size=10000):
        """
        Efficiently uploads a list of tuples (params_list) using execute_batch.
        :param query: SQL string with %s placeholders.
        :param params_list: List of tuples containing the data.
        :param batch_size: Number of records to send per network trip.
        """
        if not self.conn:
            raise RuntimeError("Database connection is not active.")

        with self.conn.cursor() as cur:
            try:
                debug("Executing batch insert/update ({} records)...", len(params_list))
                psycopg2.extras.execute_batch(cur, query, params_list, page_size=batch_size)
                sql_debug(self.conn)
            except Exception as e:
                error("Batch execution failed: {}\nQuery: {}", str(e), query)
                raise

    def set_table_owner(self, schema, table_name):
        """
        Changes the PostgreSQL owner of a specific table.
        """
        owner = self.pg_owner
        verbose(f"Changing owner of {schema}.{table_name} to {owner}")

        # We use an f-string for identifiers (schema, table, owner)
        sqltext = f'ALTER TABLE "{schema}"."{table_name}" OWNER TO {owner}'

        try:
            self.execute(sqltext)
        except Exception as e:
            error(f"Failed to change ownership for {table_name}: {e}")
            raise

    # Inside your Database class:
    def upload_dataframe(self, df: pd.DataFrame, schema: str, table: str, replace: bool = True):
        """
        Uploads a pandas DataFrame to the specified PostgreSQL table.

        :param df: The dataframe to upload
        :param schema: Target database schema
        :param table: Target table name
        :param replace: If True, drops the table before uploading ('replace').
                        If False, appends to existing table ('append').
        """
        if df.empty:
            warning(f"attempted to upload empty dataframe to {schema}.{table}")
            return

        # Map the 'replace' boolean to pandas 'if_exists' parameter
        mode = 'replace' if replace else 'append'

        try:
            # We use the engine directly for pandas compatibility
            df.to_sql(
                name=table,
                con=self.engine,  # Using the sqlalchemy engine from your class
                schema=schema,
                if_exists=mode,
                index=False,
                method='multi',  # Improves performance for bulk inserts
                chunksize=10000
            )
            debug(f"successfully uploaded {len(df)} rows to {schema}.{table} (mode: {mode})")

        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"failed to upload dataframe to {schema}.{table}: {str(e)}")

    def close(self):
        """Cleanly close the connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            debug("Database connection closed.")