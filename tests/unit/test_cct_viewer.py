"""The CCT 3-D viewer writes a self-contained HTML page for a driver."""
import base64
import gzip
import json
import re

import numpy as np

from src.utils.cct_viewer import mesh_payload, write_viewer
from tests.unit.test_cct_validation import _flat_mesh, _write


def test_payload_triangulates_every_face(tmp_path):
    path = str(tmp_path / 'cct.nc')
    _write(path, _flat_mesh())
    p = mesh_payload(path)
    tri_face = np.frombuffer(base64.b64decode(p['tri_face']), dtype='<u4')
    tri_idx = np.frombuffer(base64.b64decode(p['tri_idx']), dtype='<u4')
    assert sorted(set(tri_face.tolist())) == [0, 1, 2, 3]       # 4 quads ...
    assert tri_face.size == 8 and tri_idx.size == 24             # ... 2 triangles each
    assert p['findings'] == [] and p['stats']['faces_land'] == 4


def test_problem_faces_are_flagged(tmp_path):
    mesh = _flat_mesh()
    mesh['cct_face_area'][2] = 0.0
    path = str(tmp_path / 'cct.nc')
    _write(path, mesh)
    flags = np.frombuffer(base64.b64decode(mesh_payload(path)['flags']), dtype='u1')
    assert flags[2] & 1 and not flags[0] & 1


def test_html_is_written_with_embedded_data(tmp_path):
    path = str(tmp_path / 'cct.nc')
    _write(path, _flat_mesh())
    out = write_viewer(path, tmp_path / 'view.html', zscale=2)
    html = out.read_text(encoding='utf-8')
    packed = re.search(r"const PACKED = '([A-Za-z0-9+/=]+)';", html).group(1)
    data = json.loads(gzip.decompress(base64.b64decode(packed)))
    assert data['nfaces'] == 4 and data['zscale'] == 2.0
    assert 'three.min.js' in html and '__DATA__' not in html
