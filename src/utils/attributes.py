from src.logger import progress, debug, warning, verbose, error


def standardize_columns(cfg, db, schema, table_name):
    """
    standardize column names of one vector table in ``schema``.

    For each vector table, ``cfg.attribute_mapping.<table>`` gives a one-to-one
    ``{standard_name: source_name}`` map (default identity). When the source
    column is present it is renamed to the standard name. Requiredness is
    governed by ``cfg.attribute_spec.<table>.necessary``: a missing *necessary*
    attribute is a hard error; any other missing attribute only warns (soft).
    Tables not listed in the mapping are left untouched.

    gis_import runs this on the input schema right after each import;
    initialize_domain runs it again on the case-schema copies, so input schemas
    imported by an older PALM-GeM (which kept legacy column names such as
    vysstr) work once the mapping is set, without re-importing.
    """
    progress('standardizing table columns (source names -> standard names)')

    mapping = cfg.attribute_mapping
    spec = cfg.get('attribute_spec', None)

    # iterate by logical table name (landcover, walls, ...) and resolve to
    # the actual table name via the tables: section.
    for table_key in mapping._settings.keys():
        actual_table = cfg.tables.get(table_key, table_key)
        if not actual_table == table_name:
            debug(f'skipping {table_key}: not among imported tables')
            continue

        debug(f'checking table: {actual_table}')

        # necessary attributes for this table (everything else is soft)
        necessary = []
        if spec is not None and table_key in spec._settings:
            necessary = spec._settings[table_key].get('necessary', []) or []

        # fetch existing columns once to avoid repeated information_schema queries
        sql_cols = """
            select column_name
            from information_schema.columns
            where table_schema = %s and table_name = %s
        """
        res = db.execute(sql_cols, (schema, actual_table))
        existing_cols = [r[0] for r in res]

        table_map = mapping._settings[table_key]
        for standard_name, source_name in table_map._settings.items():
            # already standardized -> nothing to do
            if standard_name in existing_cols:
                continue

            if source_name in existing_cols:
                verbose(f'renaming column in {actual_table}: {source_name} -> {standard_name}')
                sql_rename = f"""
                    alter table "{schema}"."{actual_table}"
                    rename column {source_name} to {standard_name}
                """
                try:
                    db.execute(sql_rename)
                    existing_cols.remove(source_name)
                    existing_cols.append(standard_name)
                except Exception as e:
                    # a failed rename of a necessary attribute is fatal
                    if standard_name in necessary:
                        error(f'failed to rename necessary attribute {source_name} -> '
                              f'{standard_name} in {actual_table}: {e}')
                        raise
                    error(f'failed to rename {source_name} -> {standard_name} in {actual_table}: {e}')
                continue

            # neither standard nor source column present
            if standard_name in necessary:
                msg = (f"required attribute '{standard_name}' not found in table "
                       f"'{schema}.{actual_table}' (looked for source column '{source_name}'). "
                       f"Set attribute_mapping.{table_key}.{standard_name} to the "
                       f"matching column name in your data (input schemas imported by "
                       f"PALM-GeM 1.x keep legacy names, e.g. vysstr for treeh).")
                error(msg)
                raise ValueError(msg)
            else:
                warning(f"optional attribute '{standard_name}' not found in table "
                        f"'{actual_table}' (source column '{source_name}'); skipping")

    progress('column standardization complete')
