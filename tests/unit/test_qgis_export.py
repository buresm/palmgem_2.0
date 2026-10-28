"""Unit tests for the QGIS export style builder (no live DB needed)."""
import xml.etree.ElementTree as ET

from src.tasks.qgis_export import build_layer_qml, colour_for_type


def _layer(**overrides):
    layer = {
        'name': 'landcover',
        'table': 'landcover',
        'geometry': 'Polygon',
        'renderer': 'single',
        'colour': (10, 20, 30),
    }
    layer.update(overrides)
    return layer


def _parse(qml):
    body = '\n'.join(l for l in qml.split('\n') if not l.startswith('<!DOCTYPE'))
    return ET.fromstring(body)


def test_single_symbol_qml():
    root = _parse(build_layer_qml(_layer()))
    assert root.tag == 'qgis'
    assert root.get('styleCategories') == 'Symbology'
    renderer = root.find('renderer-v2')
    assert renderer.get('type') == 'singleSymbol'
    fill = renderer.find('symbols/symbol/layer')
    assert fill.get('class') == 'SimpleFill'
    props = {p.get('k'): p.get('v') for p in fill.findall('prop')}
    assert props['color'] == '10,20,30,255'


def test_point_layer_gets_marker_symbol():
    root = _parse(build_layer_qml(_layer(name='centerline', geometry='Point')))
    assert root.find('renderer-v2/symbols/symbol').get('type') == 'marker'
    assert root.find('renderer-v2/symbols/symbol/layer').get('class') == 'SimpleMarker'


def test_categorized_renderer_one_symbol_per_type():
    root = _parse(build_layer_qml(
        _layer(renderer='categorized_type', categories=[101, 201, 901])))
    renderer = root.find('renderer-v2')
    assert renderer.get('type') == 'categorizedSymbol'
    assert renderer.get('attr') == 'type'
    assert len(renderer.findall('categories/category')) == 3
    assert len(renderer.findall('symbols/symbol')) == 3


def test_graduated_renderer_five_classes():
    root = _parse(build_layer_qml(
        _layer(name='buildings_grid', renderer='graduated_height',
               height_range=(3.0, 33.0))))
    renderer = root.find('renderer-v2')
    assert renderer.get('type') == 'graduatedSymbol'
    ranges = renderer.findall('ranges/range')
    assert len(ranges) == 5
    assert float(ranges[0].get('lower')) == 3.0
    assert float(ranges[-1].get('upper')) == 33.0


def test_colour_for_type_families():
    r, g, b = colour_for_type(101)
    assert g > r  # vegetation is green-ish
    r, g, b = colour_for_type(901)
    assert r > g  # buildings are red-ish
    assert colour_for_type(101) == colour_for_type(101)  # deterministic
