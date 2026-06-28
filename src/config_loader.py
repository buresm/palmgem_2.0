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

import os
import sys
import yaml
import datetime
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv  # Added for Docker/Env support

error_output = sys.stderr.write


def join(loader, node):
    seq = loader.construct_sequence(node)
    return ''.join([str(i) for i in seq])


yaml.add_constructor('!join', join)


def warn(s, *args, **kwargs):
    if args or kwargs:
        error_output(s.format(*args, **kwargs) + '\n')
    else:
        error_output(s + '\n')


class ConfigError(Exception):
    """Custom exception for configuration mismatches."""

    def __init__(self, desc, section=None, key=None):
        self.desc = desc
        self.msg = f"Configuration error: {desc}"
        if section and key:
            path = ':'.join(section._get_path() + [key])
            self.msg += f" at {path}"
        super().__init__(self.msg)


class ConfigObj(object):
    """
    Recursive config object allowing dot notation: cfg.database.host
    """
    __slots__ = ['_parent', '_name', '_settings']

    def __init__(self, parent=None, name=None):
        self._parent = parent
        self._name = name
        self._settings = {}

    def __getattr__(self, name):
        try:
            return self._settings[name]
        except KeyError:
            # Return None instead of crashing if a section is missing,
            # or keep your strict AttributeError logic:
            raise AttributeError(f"Setting '{name}' not found in {':'.join(self._get_path()) or 'root'}")

    def __getitem__(self, key):
        return self._settings[key]

    def get(self, key, default=None):
        return self._settings.get(key, default)

    def _get_path(self):
        if self._parent is None: return []
        return self._parent._get_path() + [self._name]

    def _ingest_dict(self, d, overwrite=True, extend=True, check_exist=False):
        """Merges a dictionary into the ConfigObj tree."""
        if not d: return
        for k, v in d.items():
            if isinstance(v, dict):
                vl = self._settings.setdefault(k, ConfigObj(self, k))
                if not isinstance(vl, ConfigObj):  # Handle type mismatch
                    raise ConfigError(f"Cannot replace value with section", self, k)
                vl._ingest_dict(v, overwrite, extend, check_exist)
            elif extend and isinstance(v, list):
                self._settings.setdefault(k, []).extend(v)
            else:
                if overwrite or k not in self._settings:
                    if check_exist and k not in self._settings:
                        warn(f"WARNING: Unknown setting {':'.join(self._get_path() + [k])}")
                    self._settings[k] = v

    def update_setting(self, key, value, force_new=True):
        """
        A simple wrapper to update or insert new entries.

        :param key: The setting name (string)
        :param value: The value to assign
        :param force_new: If True, creates the key if it doesn't exist.
                          If False, only updates existing keys.
        """
        if not force_new and key not in self._settings:
            warn(f"Value '{key}' not found in {':'.join(self._get_path())}. Skipping update.")
            return

        # If the value is a dict, we convert it to a ConfigObj to maintain dot-notation
        if isinstance(value, dict):
            new_obj = ConfigObj(self, key)
            new_obj._ingest_dict(value)
            self._settings[key] = new_obj
        else:
            self._settings[key] = value



def load_config(config_path='', config_folder='config'):
    """
    Modernized loader:
    1. Loads .env
    2. Merges Default YAMLs
    3. Merges User YAML
    4. Injects Environment Overrides
    """
    # Load .env from project root
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")

    config = ConfigObj()

    # Define paths relative to this file to be Docker-safe
    cfg_user_dir = root / config_folder
    cfg_default_dir = root / 'config'

    defaults = [
        'default_share.yaml',
        'default_config.yaml',
        'default_slurb.yaml',
        'default_config_preproc.yaml',
        'default_gis_importer.yaml',
        'default_import.yaml',
        'default_lsm_config.yaml',
        'default_tree_config.yaml',
        'default_usm_config.yaml',
        'default_attribute_mapping.yaml',
        'default_attribute_spec.yaml',
        'default_vars_bounds.yaml'
    ]

    # 1. Load Defaults
    for d_file in defaults:
        path = cfg_default_dir / d_file
        if path.exists():
            with open(path, 'r') as f:
                config._ingest_dict(yaml.load(f, Loader=yaml.FullLoader))

    # 2. Load User Config (from CLI)
    if not config_path == '':
        user_cfg = cfg_user_dir / config_path
        if user_cfg.exists():
            with open(user_cfg, 'r') as f:
                config._ingest_dict(yaml.load(f, Loader=yaml.FullLoader), check_exist=True)
        else:
            # A config was explicitly requested but not found. Fail loudly rather
            # than silently running on defaults (wrong domain/database/tasks).
            raise FileNotFoundError(
                f"Config file not found: {user_cfg}. The path passed to -c is "
                f"resolved relative to the '{config_folder}' directory."
            )

    # 3. OVERRIDE with Env Vars (for Docker / CI)
    # See .env.example for available variables.
    env_db = {
        'host':     os.getenv('PALM_GEM_DB_HOST'),
        'port':     os.getenv('PALM_GEM_DB_PORT'),
        'user':     os.getenv('PALM_GEM_DB_USER'),
        'password': os.getenv('PALM_GEM_DB_PASSWORD'),
        'database': os.getenv('PALM_GEM_DB_NAME'),
    }
    for key, val in env_db.items():
        if val is not None:
            config.database.update_setting(key, val)

    pg_owner = os.getenv('PALM_GEM_PG_OWNER')
    if pg_owner:
        config.update_setting('pg_owner', pg_owner)

    # 4. Post-processing (Case Schemas / Directory creation)
    _finalize_config(config)

    return config


def _finalize_config(cfg):
    """Handles directory creation and dynamic naming logic."""
    # Ensure necessary base directories exist (also needed for Docker volumes).
    for folder in ['output', 'logs', 'visual_check']:
        os.makedirs(folder, exist_ok=True)

    # Resolve the surface_params CSV path: relative names are taken against the
    # config/ directory (where the shipped default lives), absolute paths pass
    # through so a user can point at their own file from anywhere.
    sp_file = getattr(cfg, 'surface_params_file', None)
    if sp_file:
        sp_path = Path(sp_file)
        if not sp_path.is_absolute():
            sp_path = Path(__file__).resolve().parent.parent / 'config' / sp_file
        cfg.update_setting('surface_params_file', str(sp_path))

    if 'domain' in cfg._settings:
        # case_schema is the single source of truth for all output naming
        # (table/schema names, NetCDF filenames, visual_check and log paths).
        scenario = getattr(cfg.domain, 'scenario', "")
        name = getattr(cfg.domain, 'name', "default")
        case_schema = name if scenario == "" else f"{name}_{scenario}"
        cfg.domain._settings['case_schema'] = case_schema

        # static (and optional SLURB) driver NetCDF filenames
        if 'static_driver_file' not in cfg.domain._settings:
            cfg.domain._settings['static_driver_file'] = os.path.join('output', f"{case_schema}_static.nc")
        if getattr(cfg, 'slurb', False) and 'slurb_driver_file' not in cfg.domain._settings:
            cfg.domain._settings['slurb_driver_file'] = os.path.join('output', f"{case_schema}_slurb.nc")

        # visual_check / log output paths
        cfg.visual_check._settings['path'] = os.path.join('visual_check', case_schema)
        cfg.logs._settings['path'] = os.path.join('logs', case_schema)

        # create the per-case visual_check dir only when something writes to it
        if cfg.visual_check.enabled or cfg.slanted_pars.do_vtk:
            os.makedirs(cfg.visual_check.path, exist_ok=True)
    else:
        cfg.logs._settings['path'] = os.path.join('logs', cfg.input_schema)

    # per-area log levels inherit the general level unless explicitly set (-1)
    for lvl in cfg.logs._settings.keys():
        if 'level_' in lvl and cfg.logs[lvl] == -1:
            cfg.logs._settings[lvl] = cfg.logs.level

# Global instance for backward compatibility if needed,
# but better to use `cfg = load_config()` in main.py
cfg = ConfigObj()