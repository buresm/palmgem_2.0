"""QGIS project export: a styled .qgs pointing at the case schema in PostGIS.

Generates one QGIS 3.x project file per case with pre-styled layers —
landcover categorised by PALM type (vegetation greens / pavement greys /
water blues / building reds), building grid graduated by height, SLURB
centerlines, etc. Only layers actually present in the case schema are
included. The database password is left out of the project unless
``qgis_export.include_password`` is enabled (QGIS will prompt once and can
store the credential itself).
"""
import os
import xml.etree.ElementTree as ET
from xml.dom import minidom

from .base import BaseTask
from src.logger import progress, debug, verbose, warning

# candidate layers, top-of-tree first: (logical key for cfg.tables/cfg.idx,
# checked-by-default, renderer kind)
_LAYER_CANDIDATES = [
    ('centerline', True, 'line_or_point'),
    ('trees', True, 'single'),
    ('buildings_grid', True, 'graduated_height'),
    ('building_area', False, 'single'),
    ('walls', False, 'single'),
    ('roofs', False, 'single'),
    ('landcover', True, 'categorized_type'),
    ('grid', False, 'single'),
]

# base colours per PALM type century (r, g, b)
_TYPE_BASE_COLOURS = {
    1: (96, 156, 80),    # 1xx vegetation
    2: (130, 130, 130),  # 2xx pavement
    3: (70, 120, 190),   # 3xx water
    9: (176, 66, 52),    # 9xx buildings
}
_DEFAULT_COLOUR = (205, 170, 90)

_SINGLE_COLOURS = {
    'centerline': (230, 60, 140),
    'trees': (30, 120, 40),
    'building_area': (240, 150, 60),
    'walls': (90, 40, 120),
    'roofs': (200, 90, 90),
    'grid': (60, 60, 60),
}


def colour_for_type(palm_type):
    """Deterministic colour for a PALM landcover type: century picks the hue
    family, the offset within the century varies the shade."""
    century = int(palm_type) // 100
    base = _TYPE_BASE_COLOURS.get(century, _DEFAULT_COLOUR)
    tweak = (int(palm_type) % 100) * 9 % 72 - 36
    return tuple(max(0, min(255, c + tweak)) for c in base)


def _geometry_flavour(pg_type):
    """Map a PostGIS geometry type to the maplayer 'geometry' attribute."""
    t = (pg_type or '').upper()
    if 'POINT' in t:
        return 'Point'
    if 'LINE' in t:
        return 'Line'
    return 'Polygon'


_WKB_NAMES = {
    'POINT': 'Point', 'MULTIPOINT': 'MultiPoint',
    'LINESTRING': 'LineString', 'MULTILINESTRING': 'MultiLineString',
    'POLYGON': 'Polygon', 'MULTIPOLYGON': 'MultiPolygon',
}


def _symbol(el_symbols, name, geometry, rgb, outline_width='0.12'):
    sym_type = {'Point': 'marker', 'Line': 'line', 'Polygon': 'fill'}[geometry]
    symbol = ET.SubElement(el_symbols, 'symbol',
                           {'type': sym_type, 'name': name, 'alpha': '1',
                            'clip_to_extent': '1'})
    colour = f'{rgb[0]},{rgb[1]},{rgb[2]},255'
    if geometry == 'Polygon':
        layer = ET.SubElement(symbol, 'layer', {'class': 'SimpleFill', 'enabled': '1'})
        props = {'color': colour, 'outline_color': '35,35,35,255',
                 'outline_width': outline_width, 'style': 'solid'}
    elif geometry == 'Line':
        layer = ET.SubElement(symbol, 'layer', {'class': 'SimpleLine', 'enabled': '1'})
        props = {'line_color': colour, 'line_width': '0.5'}
    else:
        layer = ET.SubElement(symbol, 'layer', {'class': 'SimpleMarker', 'enabled': '1'})
        props = {'color': colour, 'size': '1.6', 'name': 'circle',
                 'outline_color': '35,35,35,255'}
    for k, v in props.items():
        ET.SubElement(layer, 'prop', {'k': k, 'v': v})


def _renderer(parent, layer):
    """Attach the renderer-v2 element described by layer['renderer']."""
    kind, geometry = layer['renderer'], layer['geometry']

    if kind == 'categorized_type' and layer.get('categories'):
        r = ET.SubElement(parent, 'renderer-v2',
                          {'type': 'categorizedSymbol', 'attr': 'type',
                           'forceraster': '0', 'enableorderby': '0'})
        cats = ET.SubElement(r, 'categories')
        syms = ET.SubElement(r, 'symbols')
        for i, palm_type in enumerate(layer['categories']):
            ET.SubElement(cats, 'category',
                          {'render': 'true', 'symbol': str(i),
                           'value': str(palm_type), 'label': f'type {palm_type}'})
            _symbol(syms, str(i), geometry, colour_for_type(palm_type))
        return

    if kind == 'graduated_height' and layer.get('height_range'):
        lo, hi = layer['height_range']
        if hi <= lo:
            hi = lo + 1.0
        r = ET.SubElement(parent, 'renderer-v2',
                          {'type': 'graduatedSymbol', 'attr': 'height',
                           'graduatedMethod': 'GraduatedColor'})
        ranges = ET.SubElement(r, 'ranges')
        syms = ET.SubElement(r, 'symbols')
        n_classes = 5
        step = (hi - lo) / n_classes
        for i in range(n_classes):
            low, up = lo + i * step, lo + (i + 1) * step
            ET.SubElement(ranges, 'range',
                          {'render': 'true', 'symbol': str(i),
                           'lower': f'{low:.2f}', 'upper': f'{up:.2f}',
                           'label': f'{low:.0f} – {up:.0f} m'})
            shade = int(235 - i * (150 / (n_classes - 1)))
            _symbol(syms, str(i), geometry, (shade, int(shade * 0.45), int(shade * 0.35)))
        return

    # fallback: single symbol
    r = ET.SubElement(parent, 'renderer-v2', {'type': 'singleSymbol'})
    syms = ET.SubElement(r, 'symbols')
    _symbol(syms, '0', geometry, layer.get('colour', _DEFAULT_COLOUR))


def _crs_element(parent, crs):
    """Write a complete spatialrefsys element. QGIS cannot reconstruct a CRS
    from the authid alone — without wkt/proj4 the project opens with an
    unknown CRS and the layers land in the wrong place on the world map."""
    srs = ET.SubElement(parent, 'spatialrefsys', {'nativeFormat': 'Wkt'})
    ET.SubElement(srs, 'wkt').text = crs.get('wkt', '')
    ET.SubElement(srs, 'proj4').text = crs.get('proj4', '')
    ET.SubElement(srs, 'srid').text = str(crs['srid'])
    ET.SubElement(srs, 'authid').text = f"EPSG:{crs['srid']}"
    ET.SubElement(srs, 'description').text = crs.get('description', '')
    ET.SubElement(srs, 'geographicflag').text = 'true' if crs.get('geographic') else 'false'


def build_qgis_project(title, crs, extent, layers):
    """Build the .qgs project XML string from collected layer descriptions.

    ``crs``: dict with srid, wkt, proj4, description, geographic.
    ``layers``: list of dicts with keys name, schema, table, geom_col, key,
    pg_type, geometry, checked, renderer (+ categories / height_range /
    colour / datasource connection parts).
    """
    qgis = ET.Element('qgis', {'projectname': title, 'version': '3.28.0'})
    ET.SubElement(qgis, 'title').text = title

    _crs_element(ET.SubElement(qgis, 'projectCrs'), crs)

    tree = ET.SubElement(qgis, 'layer-tree-group')
    project_layers = ET.SubElement(qgis, 'projectlayers')
    order = ET.SubElement(qgis, 'layerorder')

    for layer in layers:
        layer_id = f"{layer['table']}_palmgem"
        checked = 'Qt::Checked' if layer['checked'] else 'Qt::Unchecked'
        ET.SubElement(tree, 'layer-tree-layer',
                      {'id': layer_id, 'name': layer['name'], 'checked': checked,
                       'expanded': '0', 'providerKey': 'postgres'})
        ET.SubElement(order, 'layer', {'id': layer_id})

        ml = ET.SubElement(project_layers, 'maplayer',
                           {'type': 'vector', 'geometry': layer['geometry'],
                            'autoRefreshEnabled': '0'})
        ET.SubElement(ml, 'id').text = layer_id
        ET.SubElement(ml, 'datasource').text = layer['datasource']
        ET.SubElement(ml, 'layername').text = layer['name']
        _crs_element(ET.SubElement(ml, 'srs'), crs)
        ET.SubElement(ml, 'provider', {'encoding': 'UTF-8'}).text = 'postgres'
        _renderer(ml, layer)

    if extent:
        canvas = ET.SubElement(qgis, 'mapcanvas', {'name': 'theMapCanvas'})
        ET.SubElement(canvas, 'units').text = 'meters'
        ext = ET.SubElement(canvas, 'extent')
        for tag, val in zip(('xmin', 'ymin', 'xmax', 'ymax'), extent):
            ET.SubElement(ext, tag).text = f'{val:.2f}'
        _crs_element(ET.SubElement(canvas, 'destinationsrs'), crs)

    raw = ET.tostring(qgis, encoding='unicode')
    pretty = minidom.parseString(raw).toprettyxml(indent='  ')
    # minidom adds its own xml declaration; insert the qgis doctype after it
    lines = pretty.split('\n')
    lines.insert(1, "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>")
    return '\n'.join(line for line in lines if line.strip())


class QgisExportTask(BaseTask):
    """Write output/<case>.qgs with all case-schema layers that exist."""

    def run(self):
        schema = self.cfg.domain.case_schema
        layers = []
        for logical, checked, renderer in _LAYER_CANDIDATES:
            table = self.cfg.tables.get(logical, logical)
            info = self._geometry_info(schema, table)
            if info is None:
                verbose(f'qgis_export: no table {table} in {schema}; skipping layer')
                continue
            geom_col, pg_type = info
            geometry = _geometry_flavour(pg_type)

            layer = {
                'name': logical,
                'schema': schema,
                'table': table,
                'geom_col': geom_col,
                'pg_type': pg_type,
                'geometry': geometry,
                'checked': checked,
                'renderer': 'single' if renderer == 'line_or_point' else renderer,
                'colour': _SINGLE_COLOURS.get(logical, _DEFAULT_COLOUR),
                'key': self.cfg.idx.get(logical, 'gid'),
            }

            if renderer == 'categorized_type':
                layer['categories'] = [r[0] for r in self.fetch(
                    f'select distinct type from "{schema}"."{table}" '
                    f'where type is not null order by type')]
            if renderer == 'graduated_height':
                row = self.fetch(f'select min(height), max(height) '
                                 f'from "{schema}"."{table}"')[0]
                if row[0] is not None:
                    layer['height_range'] = (float(row[0]), float(row[1]))
                else:
                    layer['renderer'] = 'single'

            layer['datasource'] = self._datasource(layer)
            layers.append(layer)
            debug(f'qgis_export: layer {logical} -> {table} ({pg_type})')

        if not layers:
            warning(f'qgis_export: no exportable tables found in schema {schema}')
            return

        # derive the extent from the domain centre so the task also works
        # standalone (origin_x/y only exist after SetupTask ran in-process)
        d = self.cfg.domain
        half_w, half_h = d.nx * d.dx / 2.0, d.ny * d.dy / 2.0
        extent = (d.cent_x - half_w, d.cent_y - half_h,
                  d.cent_x + half_w, d.cent_y + half_h)

        xml = build_qgis_project(schema, self._crs_definition(), extent, layers)

        project_file = self.cfg.qgis_export.project_file or os.path.join(
            'output', f'{schema}.qgs')
        os.makedirs(os.path.dirname(project_file) or '.', exist_ok=True)
        with open(project_file, 'w', encoding='utf-8') as f:
            f.write(xml)
        progress('qgis_export written: {} ({} layer(s))', project_file, len(layers))
        if not self.cfg.qgis_export.include_password:
            verbose('qgis_export: database password not embedded; QGIS will prompt on open')

    def _crs_definition(self):
        """Full CRS definition for srid_palm from PostGIS spatial_ref_sys."""
        srid = self.cfg.srid_palm
        rows = self.fetch(
            'select srtext, proj4text from spatial_ref_sys where srid = %s', (srid,))
        wkt, proj4 = rows[0] if rows else ('', '')
        description = wkt.split('"')[1] if wkt and '"' in wkt else f'EPSG:{srid}'
        return {
            'srid': srid,
            'wkt': wkt or '',
            'proj4': proj4 or '',
            'description': description,
            'geographic': '+proj=longlat' in (proj4 or ''),
        }

    def _geometry_info(self, schema, table):
        """(geom_column, geometry_type) from geometry_columns, or None."""
        rows = self.fetch(
            'select f_geometry_column, type from geometry_columns '
            'where f_table_schema = %s and f_table_name = %s limit 1',
            (schema, table))
        if not rows:
            return None
        geom_col, pg_type = rows[0]
        if (pg_type or '').upper() == 'GEOMETRY':
            # untyped column (created via create-table-as-select): probe the
            # actual data so points do not get polygon styling
            probe = self.fetch(
                f'select replace(st_geometrytype("{geom_col}"), \'ST_\', \'\') '
                f'from "{schema}"."{table}" where "{geom_col}" is not null limit 1')
            if probe:
                pg_type = probe[0][0].upper()
        return geom_col, pg_type

    def _datasource(self, layer):
        db = self.cfg.database
        parts = [
            f"dbname='{db.database}'",
            f"host={db.host}",
            f"port={db.get('port', 5432)}",
            f"user='{db.user}'",
        ]
        if self.cfg.qgis_export.include_password:
            parts.append(f"password='{db.password}'")
        parts += [
            'sslmode=disable',
            f"key='{layer['key']}'",
            f"srid={self.cfg.srid_palm}",
            f"type={_WKB_NAMES.get((layer['pg_type'] or '').upper(), 'Geometry')}",
            f'table="{layer["schema"]}"."{layer["table"]}" ({layer["geom_col"]})',
        ]
        return ' '.join(parts)
