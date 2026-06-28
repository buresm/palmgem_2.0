from src.logger import progress, verbose, debug


def compute_envelope(cfg, db, schema, table, srid=None):
    """
    Computes and stores the domain envelope geometry in cfg.envelope.

    If cfg.domain.crop_domain is True, builds the envelope from xl/yl/xh/yh
    values already in cfg.domain. Otherwise, unions all geometries in
    schema.table, transforms to srid, and takes the bounding rectangle.

    Corner coordinates (xl, yl, xh, yh) are written back into cfg.domain
    when computed from data (crop_domain=False).

    Returns the envelope geometry (as returned by PostGIS).
    """
    if srid is None:
        srid = getattr(cfg, 'srid', getattr(cfg, 'srid_palm', 4326))

    if cfg.domain.crop_domain:
        progress('computing envelope from user-defined bounds')
        sql = 'SELECT ST_MakeEnvelope(%s, %s, %s, %s, %s)'
        result = db.fetch(sql, (cfg.domain.xl, cfg.domain.yl, cfg.domain.xh, cfg.domain.yh, srid))
        envelope = result[0][0] if result else None

    else:
        progress(f'computing envelope from extent of {schema}.{table}')
        # We only need the bounding rectangle of all geometries, so take the
        # envelope of an ST_Collect (cheap grouping) rather than a full ST_Union,
        # which dissolves every polygon and dominates runtime on city-scale data.
        # ST_Collect preserves the source SRID; transform the result to `srid`.
        sql_env = f'SELECT ST_Transform(ST_Envelope(ST_Collect(geom)), %s) FROM "{schema}"."{table}"'
        result = db.fetch(sql_env, (srid,))
        envelope = result[0][0] if result else None

        verbose('extracting envelope corner coordinates')
        sql_corners = """
            SELECT ST_XMin(%s::geometry), ST_YMin(%s::geometry),
                   ST_XMax(%s::geometry), ST_YMax(%s::geometry)
        """
        result = db.fetch(sql_corners, (envelope, envelope, envelope, envelope))
        if result:
            xl, yl, xh, yh = result[0]
            cfg.domain._settings.update({'xl': xl, 'yl': yl, 'xh': xh, 'yh': yh})
            verbose('envelope corners: xl={}, yl={}, xh={}, yh={}', xl, yl, xh, yh)

    cfg.update_setting('envelope', envelope)
    debug('envelope stored in cfg.envelope')
    return envelope
