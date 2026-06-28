#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright 2018-2024 Institute of Computer Science of the Czech Academy of
# Sciences, Prague, Czech Republic. Authors: Martin Bures, Jaroslav Resler.
#
# This file is part of PALM-GeM.
#
# PALM-GeM is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# PALM-GeM is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# PALM-GeM. If not, see <https://www.gnu.org/licenses/>.

import sys
import logging
import os
from pathlib import Path

# Define custom levels using higher ranges to avoid clashing with standard Python levels
EXTRA_VERBOSE = 5
VERBOSE = 15
DEBUG = 10  # Standard Python DEBUG is 10
PROGRESS = 25  # Between INFO (20) and WARNING (30)
WARNING = 30
ERROR = 40


def _log_to_level(level, name, msg, *args, **kwargs):
    """Helper to route logs correctly with the 'source' extra field."""
    source = {'source': name}
    logger = logging.getLogger()
    if logger.isEnabledFor(level):
        if args or kwargs:
            logger.log(level, msg.format(*args, **kwargs), extra=source)
        else:
            logger.log(level, msg, extra=source)


def _process_pg_notices(con, level, name):
    """Shared logic for parsing psycopg2 notices."""
    source = {'source': name}
    if logging.getLogger().isEnabledFor(level):
        # Use a slice to avoid modification issues during iteration
        for n in con.notices[:]:
            for nn in n.splitlines():
                clean_notice = nn.replace('NOTICE:', '').strip()
                if clean_notice:
                    logging.log(level, clean_notice, extra=source)
        con.notices.clear()


# --- Custom Level Wrappers ---

def extra_verbose(msg, *args, **kwargs): _log_to_level(EXTRA_VERBOSE, "EXTRA VERBOSE", msg, *args, **kwargs)


def verbose(msg, *args, **kwargs):       _log_to_level(VERBOSE, "VERBOSE", msg, *args, **kwargs)


def debug(msg, *args, **kwargs):         _log_to_level(DEBUG, "DEBUG", msg, *args, **kwargs)


def progress(msg, *args, **kwargs):      _log_to_level(PROGRESS, "PROGRESS", msg, *args, **kwargs)


def warning(msg, *args, **kwargs):       _log_to_level(WARNING, "WARNING", msg, *args, **kwargs)


def error(msg, *args, **kwargs):         _log_to_level(ERROR, "ERROR", msg, *args, **kwargs)


# --- SQL Specific Handlers ---

def sql_extra_verbose(con): _process_pg_notices(con, EXTRA_VERBOSE, "SQL EXTRA")


def sql_verbose(con):       _process_pg_notices(con, VERBOSE, "SQL VERBOSE")


def sql_debug(con):         _process_pg_notices(con, DEBUG, "SQL DEBUG")


# Register Levels with the logging module
for lvl, name in [(EXTRA_VERBOSE, "EXTRA_VERBOSE"), (VERBOSE, "VERBOSE"), (PROGRESS, "PROGRESS")]:
    logging.addLevelName(lvl, name)


# --- Output Redirection ---

class LoggerWriter:
    """Redirects writes (like sys.stderr) to a logger function."""

    def __init__(self, writer_func):
        self._writer = writer_func
        self._buffer = ''

    def write(self, message):
        self._buffer += message
        while '\n' in self._buffer:
            pos = self._buffer.find('\n')
            self._writer(self._buffer[:pos])
            self._buffer = self._buffer[pos + 1:]

    def flush(self):
        if self._buffer:
            self._writer(self._buffer)
            self._buffer = ''


# --- Configuration Handlers ---

Log_Format = "{asctime:20s} {source:15s} - {message}"


def setup_logging(cfg):
    """Initializes logging based on the ConfigObj settings."""
    # Ensure the log path exists (critical for Docker)
    log_path = Path(cfg.logs.path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=int(cfg.logs.level),
        format=Log_Format,
        datefmt='%Y-%m-%d %H:%M:%S',
        style='{',
        handlers=[
            logging.FileHandler(log_path, "w"),
            logging.StreamHandler(sys.stdout),
        ]
    )

    # Redirect stderr to the logger
    sys.stderr = LoggerWriter(error)

    # Silence chatty libraries
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("fiona").setLevel(logging.WARNING)  # Common in GIS


def change_log_level(new_level):
    logging.getLogger().setLevel(new_level)
    progress('Log level changed to: {}', logging.getLevelName(new_level))


def restore_log_level(cfg):
    logging.getLogger().setLevel(cfg.logs.level)
    progress('Log level restored to: {}', cfg.logs.level)