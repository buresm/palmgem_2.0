"""QGIS export: a styled GeoPackage snapshot of the case schema.

Writes ``output/<case>.gpkg`` with every case-schema layer that exists,
plus the standard QGIS ``layer_styles`` table so the styling auto-applies
when the file is opened — landcover categorised by PALM type (vegetation
greens / pavement greys / water blues / building reds), building grid
graduated by height, SLURB centerlines, etc.

The GeoPackage is written through geopandas/GDAL, which embeds the full CRS
definition from PostGIS per layer — QGIS then georeferences the data itself,
with no hand-written CRS information involved (an earlier .qgs-based export
misplaced the data when QGIS could not resolve the hand-crafted CRS block).
"""
import os
import sqlite3
import xml.etree.ElementTree as ET

import geopandas as gpd

from .base import BaseTask
from src.logger import progress, debug, verbose, warning

# candidate layers, top-of-tree first: (logical key for cfg.tables,
# renderer kind)
_LAYER_CANDIDATES = [
    ('centerline', 'single'),
    ('trees', 'single'),
    ('buildings_grid', 'graduated_height'),
    ('building_area', 'single'),
    ('walls', 'single'),
    ('roofs', 'single'),
    ('landcover', 'categorized_type'),
    ('grid', 'single'),
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
    """Map a PostGIS/OGC geometry type to the symbol flavour."""
    t = (pg_type or '').upper()
    if 'POINT' in t:
        return 'Point'
    if 'LINE' in t:
        return 'Line'
    return 'Polygon'


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


def build_layer_qml(layer):
    """Symbology-only QML document for one layer, stored in the GeoPackage
    layer_styles table and auto-applied by QGIS on load."""
    qgis = ET.Element('qgis', {'version': '3.28.0', 'styleCategories': 'Symbology'})
    _renderer(qgis, layer)
    body = ET.tostring(qgis, encoding='unicode')
    return ("<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n" + body)


class QgisExportTask(BaseTask):
    """Write output/<case>.gpkg with all case-schema layers + default styles."""

    def run(self):
        schema = self.cfg.domain.case_schema

        gpkg_file = self.cfg.qgis_export.gpkg_file or os.path.join(
            'output', f'{schema}.gpkg')
        os.makedirs(os.path.dirname(gpkg_file) or '.', exist_ok=True)
        if os.path.exists(gpkg_file):
            try:
                os.remove(gpkg_file)
            except PermissionError:
                # typically the snapshot is open in QGIS while the pipeline
                # re-runs; skip the export rather than aborting the run
                warning(f'qgis_export: {gpkg_file} is locked (open in QGIS?); '
                        'close it and re-run the qgis_export task')
                return

        layers = []
        for logical, renderer in _LAYER_CANDIDATES:
            table = self.cfg.tables.get(logical, logical)
            info = self._geometry_info(schema, table)
            if info is None:
                verbose(f'qgis_export: no table {table} in {schema}; skipping layer')
                continue
            geom_col, pg_type = info

            layer = {
                'name': logical,
                'table': table,
                'geometry': _geometry_flavour(pg_type),
                'renderer': renderer,
                'colour': _SINGLE_COLOURS.get(logical, _DEFAULT_COLOUR),
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

            debug(f'qgis_export: reading layer {logical} <- "{schema}"."{table}"')
            gdf = gpd.read_postgis(
                f'select * from "{schema}"."{table}"',
                self.db.engine, geom_col=geom_col)
            if gdf.crs is None:
                gdf = gdf.set_crs(epsg=self.cfg.srid_palm)
            gdf.to_file(gpkg_file, layer=logical, driver='GPKG')

            layers.append(layer)
            verbose(f'qgis_export: wrote layer {logical} ({len(gdf)} features, '
                    f'crs {gdf.crs})')

        if not layers:
            warning(f'qgis_export: no exportable tables found in schema {schema}')
            return

        self._write_styles(gpkg_file, layers)
        progress('qgis_export written: {} ({} layer(s), styles embedded)',
                 gpkg_file, len(layers))

    def _write_styles(self, gpkg_file, layers):
        """Embed one default QML style per layer via the standard QGIS
        layer_styles table (the 'save style in database' mechanism)."""
        con = sqlite3.connect(gpkg_file)
        try:
            # geometry column name as GDAL actually wrote it
            geom_cols = dict(con.execute(
                'select table_name, column_name from gpkg_geometry_columns'))

            con.execute("""
                create table if not exists layer_styles (
                    id integer primary key autoincrement,
                    f_table_catalog text, f_table_schema text, f_table_name text,
                    f_geometry_column text, styleName text, styleQML text,
                    styleSLD text, useAsDefault boolean, description text,
                    owner text, ui text,
                    update_time datetime default current_timestamp)
            """)
            for layer in layers:
                qml = build_layer_qml(layer)
                con.execute(
                    'insert into layer_styles (f_table_catalog, f_table_schema, '
                    'f_table_name, f_geometry_column, styleName, styleQML, '
                    'styleSLD, useAsDefault, description, owner, ui) '
                    "values ('', '', ?, ?, ?, ?, '', 1, 'PALM-GeM default style', '', '')",
                    (layer['name'], geom_cols.get(layer['name'], 'geom'),
                     f"{layer['name']}_palmgem", qml))
            con.commit()
        finally:
            con.close()

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
