from src.logger import progress, debug


def _table_exists(db, schema, table):
    return bool(db.fetchone(
        "select exists(select 1 from information_schema.tables "
        "where table_schema = %s and table_name = %s)",
        (schema, table)))


def _column_exists(db, schema, table, column):
    return bool(db.fetchone(
        "select exists(select 1 from information_schema.columns "
        "where table_schema = %s and table_name = %s and column_name = %s)",
        (schema, table, column)))


def ensure_capability_flags(cfg, db):
    """Make the derived capability flags available without re-running initialize_domain.

    ``has_buildings`` / ``has_3d_buildings`` / ``has_surface_params`` / ``lod2`` are
    normally set in memory by :class:`InitializeDomainTask`. When a NetCDF or CCT
    task runs on its own (staged execution: a separate process that only emits the
    driver) those flags are absent, and reading them would raise ``AttributeError``.
    This reconstructs them from the persisted ``case_schema`` so the task can run
    independently of the process that built the domain.

    Only flags that are *missing* are filled, so a full single-process run — where
    ``initialize_domain`` already set them, including config-driven adjustments such
    as ``force_lsm_only`` — is left exactly as-is.
    """
    needed = ['has_buildings', 'has_3d_buildings', 'has_surface_params', 'lod2']
    if all(key in cfg._settings for key in needed):
        return

    schema = cfg.domain.case_schema
    progress('deriving capability flags from existing schema "{}" (staged run)', schema)

    # surface params: copied table present + catland column on the landcover table
    has_surface_params = (
        _table_exists(db, schema, cfg.tables.surface_params)
        and _column_exists(db, schema, cfg.tables.landcover, 'catland')
    )

    # buildings present: a buildings height raster, or building-type rows in landcover
    has_buildings = _table_exists(db, schema, cfg.tables.buildings_height)
    if not has_buildings and _table_exists(db, schema, cfg.tables.landcover):
        count = db.fetchone(
            f'select count(*) from "{schema}"."{cfg.tables.landcover}" '
            f'where type between %s and %s',
            (cfg.type_range.building_min, cfg.type_range.building_max))
        has_buildings = bool(count and count > 0)

    # 3d buildings: both the extras vector and extras raster were copied to the case
    has_3d_buildings = (
        _table_exists(db, schema, cfg.tables.extras_shp)
        and _table_exists(db, schema, cfg.tables.extras)
    )

    # lod2: surface params + roof/wall geometry present, unless surface fractions win
    lod2 = (
        has_surface_params
        and _table_exists(db, schema, cfg.tables.roofs)
        and _table_exists(db, schema, cfg.tables.walls)
    )
    if cfg.landcover.surface_fractions and lod2:
        lod2 = False

    for key, value in {
        'has_buildings': has_buildings,
        'has_3d_buildings': has_3d_buildings,
        'has_surface_params': has_surface_params,
        'lod2': lod2,
    }.items():
        if key not in cfg._settings:
            cfg.update_setting(key, value)
            debug('derived capability flag {} = {}', key, value)


def ensure_domain_geometry(cfg, db):
    """Make the derived vertical domain geometry available without re-running
    initialize_domain.

    ``calculate_origin_z_oro_min`` sets ``cfg.domain.oro_min`` (and ``origin_z``
    when it is the ``-1`` "auto" sentinel) in memory during initialize_domain.
    The driver tasks read ``cfg.domain.oro_min``/``origin_z``; when a driver runs
    on its own (staged execution) those are absent and reading them raises
    ``AttributeError``. This reconstructs them from the persisted grid the same
    way initialize_domain did — ``oro_min`` is the minimum cell ``height`` — so
    the task can run independently of the process that built the domain.

    Only fills what is missing: a full single-process run, where
    initialize_domain already set ``oro_min``, is left exactly as-is.
    """
    if 'oro_min' in cfg.domain._settings:
        return

    origin_z = getattr(cfg.domain, 'origin_z', -1)

    if origin_z == -1:
        # auto origin: mirror initialize_domain — pull min height from the case
        # schema (or the parent domain when nesting).
        source_schema = cfg.domain.case_schema
        if getattr(cfg.domain, 'parent_domain_schema', '') != '':
            source_schema = cfg.domain.parent_domain_schema

        min_height = db.fetchone(
            f'select min(height) from "{source_schema}"."{cfg.tables.grid}"')
        min_height = min_height if min_height is not None else 0.0

        progress('deriving origin_z/oro_min from grid "{}" (staged run) = {}',
                 source_schema, min_height)
        cfg.domain.update_setting('origin_z', min_height)
        cfg.domain.update_setting('oro_min', min_height)
    else:
        # predefined origin: oro_min follows it
        cfg.domain.update_setting('oro_min', origin_z)
        debug('derived oro_min from configured origin_z = {}', origin_z)
