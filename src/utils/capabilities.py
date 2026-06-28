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
