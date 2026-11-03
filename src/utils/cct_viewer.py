"""Interactive 3-D view of the cut-cell topography (CCT) mesh of a static driver.

Writes one self-contained HTML file (three.js from a CDN, mesh data embedded)
that opens in any browser:

    python -m src.utils.cct_viewer output/<case>_static.nc [-o view.html] [--zscale 1]

The page shows land, wall and roof faces as separate layers and colours them
by surface type, LSM class, building, normal direction (n_z) or by the
findings of the CCT validation (src/utils/cct_validation.py): faces with an
error, faces on an open edge, faces repeating a vertex and faces in columns
that are not covered exactly once. Clicking a face shows its values; the
"problem spots" list groups the faces with a finding by location and flies
the camera to each group. The
cct_driver task writes this file to visual_check/ when visual_check.enabled.
"""
import argparse
import base64
import gzip
import json
from pathlib import Path

import netCDF4
import numpy as np

from src.utils.cct_validation import check_cct_geometry, load_mesh

THREE_JS = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js'
ORBIT_JS = 'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js'

FLAG_ERROR, FLAG_OPEN, FLAG_REPEAT, FLAG_COVER, FLAG_STAIR = 1, 2, 4, 8, 16


def _b64(a, dtype):
    return base64.b64encode(np.ascontiguousarray(a, dtype=dtype).tobytes()).decode('ascii')


def mesh_payload(path):
    """Triangulated mesh, per-face attributes, validation stats and findings."""
    with netCDF4.Dataset(path) as ds:
        problems = {}
        findings, stats = check_cct_geometry(ds, problems=problems)
        m = load_mesh(ds)
        title = ds.getncattr('title') if 'title' in ds.ncattrs() else Path(path).stem
    nf = m['area'].size
    nv = m['vert'].shape[1]
    vz, vy, vx = m['vert']

    tri_idx, tri_face, edges = [], [], set()
    for f in range(nf):
        n = int(m['nvert'][f])
        vs = [int(v) for v in m['faces'][:n, f]]
        if n < 3 or min(vs) < 0 or max(vs) >= nv:
            continue
        for a in range(1, n - 1):                       # fan triangulation
            tri_idx.extend((vs[0], vs[a], vs[a + 1]))
            tri_face.append(f)
        for a, b in zip(vs, vs[1:] + vs[:1]):
            if a != b:
                edges.add((a, b) if a < b else (b, a))
    vpos = np.stack([vx, vz, -vy], axis=1)              # three.js: y up

    flags = np.zeros(nf, dtype=np.uint8)
    for key, bit in (('error', FLAG_ERROR), ('open_edge', FLAG_OPEN), ('repeat', FLAG_REPEAT),
                     ('coverage', FLAG_COVER), ('stairstep', FLAG_STAIR)):
        if problems.get(key) is not None and len(problems[key]):
            flags[problems[key]] |= bit

    def lsm_class(f):
        for code, key in ((1, 'vegetation'), (2, 'pavement'), (3, 'water')):
            if m[key] is not None and m[key][f] >= 0:
                return code
        return 0

    k, j, i = m['kji']
    return {
        'title': title, 'dx': m['dx'], 'dz': m['dz'], 'nx': m['nx'], 'ny': m['ny'],
        'nfaces': nf, 'stats': stats,
        'findings': [{'level': lvl, 'message': msg} for lvl, msg in findings],
        'vpos': _b64(vpos, '<f4'), 'tri_idx': _b64(tri_idx, '<u4'), 'tri_face': _b64(tri_face, '<u4'),
        'edge_idx': _b64(sorted(edges), '<u4'),
        'stype': _b64(m['stype'], 'u1'), 'flags': _b64(flags, 'u1'),
        'lsm': _b64([lsm_class(f) for f in range(nf)], 'u1'),
        'lsm_type': _b64([max((m[t][f] for t in ('vegetation', 'pavement', 'water') if m[t] is not None),
                              default=-1) for f in range(nf)], '<i4'),
        'btype': _b64(m['building'] if m['building'] is not None else np.full(nf, -1), '<i4'),
        'bid': _b64(m['bid'] if m['bid'] is not None else np.full(nf, -1), '<i4'),
        'area': _b64(m['area'], '<f4'), 'nz': _b64(m['normal'][0], '<f4'),
        'kji': _b64(np.vstack([k, j, i]).T, '<i4'),
    }


def write_viewer(nc_path, html_path=None, zscale=1.0):
    """Write the viewer HTML for ``nc_path``; returns the HTML path."""
    nc_path = Path(nc_path)
    html_path = Path(html_path) if html_path else nc_path.with_name(nc_path.stem + '_cct_view.html')
    payload = mesh_payload(str(nc_path))
    payload['zscale'] = float(zscale)
    # the mesh arrays compress well; the page unpacks them with the browser's
    # DecompressionStream, which keeps even large meshes to a few MB
    packed = base64.b64encode(gzip.compress(json.dumps(payload).encode('utf-8'))).decode('ascii')
    html = (_TEMPLATE.replace('__THREE__', THREE_JS).replace('__ORBIT__', ORBIT_JS)
            .replace('__TITLE__', payload['title']).replace('__DATA__', packed))
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding='utf-8')
    return html_path


def main(argv=None):
    ap = argparse.ArgumentParser(description='3-D HTML view of the CCT mesh of a PALM static driver')
    ap.add_argument('driver', help='static driver NetCDF written by cct_driver')
    ap.add_argument('-o', '--output', help='HTML file (default: <driver>_cct_view.html)')
    ap.add_argument('--zscale', type=float, default=1.0, help='vertical exaggeration (default 1)')
    args = ap.parse_args(argv)
    out = write_viewer(args.driver, args.output, args.zscale)
    print(out)


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CCT view: __TITLE__</title>
<style>
  :root { --bg:#f4f5f7; --panel:#ffffff; --text:#1d2330; --muted:#5d6678; --line:#d9dde5; --err:#c62828; --warn:#b26a00; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#14171c; --panel:#1d2128; --text:#e6e9ef; --muted:#9aa3b2; --line:#2e343e; --err:#ff6b6b; --warn:#ffb74d; }
  }
  html, body { margin:0; height:100%; background:var(--bg); color:var(--text);
               font:13px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
  #app { display:flex; height:100%; }
  #view { flex:1; position:relative; min-width:0; }
  #panel { width:320px; overflow:auto; background:var(--panel); border-left:1px solid var(--line);
           padding:12px 14px; box-sizing:border-box; }
  h1 { font-size:15px; margin:0 0 2px; }
  h2 { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin:16px 0 6px; }
  .sub { color:var(--muted); margin-bottom:8px; }
  label { display:block; margin:3px 0; cursor:pointer; }
  select { width:100%; padding:4px; background:var(--bg); color:var(--text); border:1px solid var(--line); border-radius:4px; }
  table { width:100%; border-collapse:collapse; }
  td { padding:2px 0; border-bottom:1px solid var(--line); }
  td:last-child { text-align:right; font-variant-numeric:tabular-nums; }
  .finding { padding:4px 6px; margin:4px 0; border-radius:4px; border-left:3px solid; background:var(--bg); }
  .finding.error { border-color:var(--err); } .finding.warning { border-color:var(--warn); }
  .ok { color:#2e7d32; font-weight:600; }
  #legend div { display:flex; align-items:center; gap:6px; margin:2px 0; }
  #legend span.sw { width:14px; height:10px; border-radius:2px; display:inline-block; }
  #pick { white-space:pre; font-family:ui-monospace, Consolas, monospace; font-size:12px; }
  .spot { display:block; width:100%; text-align:left; margin:3px 0; padding:4px 6px; cursor:pointer;
          background:var(--bg); color:var(--text); border:1px solid var(--line); border-radius:4px; font:inherit; }
  .spot:hover { border-color:var(--muted); } .spot small { color:var(--muted); }
  #hint { position:absolute; left:10px; bottom:8px; color:var(--muted); font-size:12px; pointer-events:none; }
  @media (max-width: 700px) { #app { flex-direction:column; } #panel { width:100%; height:45%; border-left:none; border-top:1px solid var(--line); } }
</style>
</head>
<body>
<div id="app">
  <div id="view"><div id="hint">drag: rotate · right-drag: pan · wheel: zoom · click: inspect face</div></div>
  <div id="panel">
    <h1>Cut-cell topography</h1>
    <div class="sub" id="sub"></div>
    <h2>Colour</h2>
    <select id="mode">
      <option value="type">surface type</option>
      <option value="lsm">land class (vegetation / pavement / water)</option>
      <option value="building">building id</option>
      <option value="nz">normal n_z</option>
      <option value="problems">validation findings</option>
    </select>
    <div id="legend"></div>
    <h2>Layers</h2>
    <label><input type="checkbox" id="l0" checked> land</label>
    <label><input type="checkbox" id="l1" checked> walls</label>
    <label><input type="checkbox" id="l2" checked> roofs</label>
    <label><input type="checkbox" id="edges"> face edges</label>
    <label>vertical scale <input type="range" id="zs" min="1" max="5" step="0.5" value="1"> <span id="zsv"></span></label>
    <h2>Selected face</h2>
    <div id="pick">click a face</div>
    <h2>Validation</h2>
    <div id="findings"></div>
    <h2>Problem spots</h2>
    <div id="spots"></div>
    <h2>Mesh</h2>
    <table id="stats"></table>
  </div>
</div>
<script src="__THREE__"></script>
<script src="__ORBIT__"></script>
<script>
const PACKED = '__DATA__';
async function unpack(b64) {
  const bin = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const stream = new Blob([bin]).stream().pipeThrough(new DecompressionStream('gzip'));
  return JSON.parse(await new Response(stream).text());
}
unpack(PACKED).then(D => {
function dec(b64, T) { const s = atob(b64), u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return new T(u.buffer); }
const vpos = dec(D.vpos, Float32Array), triIdx = dec(D.tri_idx, Uint32Array), triFace = dec(D.tri_face, Uint32Array);
const edgeIdx = dec(D.edge_idx, Uint32Array);
const triPos = new Float32Array(triIdx.length * 3);
triIdx.forEach((v, n) => triPos.set(vpos.subarray(v * 3, v * 3 + 3), n * 3));
const edgePos = new Float32Array(edgeIdx.length * 3);
edgeIdx.forEach((v, n) => edgePos.set(vpos.subarray(v * 3, v * 3 + 3), n * 3));
const stype = dec(D.stype, Uint8Array), flags = dec(D.flags, Uint8Array), lsm = dec(D.lsm, Uint8Array);
const lsmType = dec(D.lsm_type, Int32Array), btype = dec(D.btype, Int32Array), bid = dec(D.bid, Int32Array);
const area = dec(D.area, Float32Array), nz = dec(D.nz, Float32Array), kji = dec(D.kji, Int32Array);

document.getElementById('sub').textContent = `${D.title} · ${D.nx}×${D.ny} cells · dx ${D.dx} m · dz ${D.dz} m · ${D.nfaces} faces`;

const view = document.getElementById('view');
const renderer = new THREE.WebGLRenderer({antialias: true});
renderer.setPixelRatio(window.devicePixelRatio);
view.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const dark = matchMedia('(prefers-color-scheme: dark)').matches;
scene.background = new THREE.Color(dark ? 0x14171c : 0xf4f5f7);
const cx = D.nx * D.dx / 2, cz = -D.ny * D.dx / 2, span = Math.max(D.nx, D.ny) * D.dx;
const camera = new THREE.PerspectiveCamera(45, 1, span / 1000, span * 20);
camera.position.set(cx - span * 0.7, span * 0.6, cz + span * 0.9);
const controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.target.set(cx, 0, cz); controls.update();
scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 0.75));
const sun = new THREE.DirectionalLight(0xffffff, 0.65); sun.position.set(-1, 2, 1.2); scene.add(sun);

// one mesh per surface type (layers), non-indexed so each triangle carries its face colour
const layers = [], group = new THREE.Group(); scene.add(group);
for (let t = 0; t < 3; t++) {
  const tris = []; for (let n = 0; n < triFace.length; n++) if (stype[triFace[n]] === t) tris.push(n);
  const pos = new Float32Array(tris.length * 9), col = new Float32Array(tris.length * 9);
  tris.forEach((n, q) => pos.set(triPos.subarray(n * 9, n * 9 + 9), q * 9));
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  g.computeVertexNormals();
  const mesh = new THREE.Mesh(g, new THREE.MeshLambertMaterial({vertexColors: true, side: THREE.DoubleSide}));
  mesh.userData.tris = tris; group.add(mesh); layers.push(mesh);
}
const eg = new THREE.BufferGeometry(); eg.setAttribute('position', new THREE.BufferAttribute(edgePos, 3));
const edgeLines = new THREE.LineSegments(eg, new THREE.LineBasicMaterial({color: dark ? 0x000000 : 0x333333, transparent: true, opacity: 0.35}));
edgeLines.visible = false; group.add(edgeLines);

const C = h => new THREE.Color(h);
const palettes = {
  type: {items: [['land', '#7cb26b'], ['wall', '#b9bec7'], ['roof', '#c0644e']], f: f => [C('#7cb26b'), C('#b9bec7'), C('#c0644e')][stype[f]] || C('#888')},
  lsm: {items: [['vegetation', '#5f9e4f'], ['pavement', '#8d8f94'], ['water', '#3f7fcf'], ['none / building', '#d0d3d9']],
        f: f => stype[f] ? C('#d0d3d9') : [C('#d0d3d9'), C('#5f9e4f'), C('#8d8f94'), C('#3f7fcf')][lsm[f]]},
  building: {items: [['colour per building id', '#9c6ade'], ['land', '#d0d3d9']],
             f: f => stype[f] && bid[f] >= 0 ? new THREE.Color().setHSL(((bid[f] * 0.61803) % 1), 0.55, 0.55) : C('#d0d3d9')},
  nz: {items: [['n_z = 1 (up)', '#2c7bb6'], ['n_z = 0 (vertical)', '#ffffbf'], ['n_z = -1 (down)', '#d7191c']],
       f: f => { const v = nz[f]; return v >= 0 ? C('#ffffbf').lerp(C('#2c7bb6'), v) : C('#ffffbf').lerp(C('#d7191c'), -v); }},
  problems: {items: [['error', '#e53935'], ['open edge', '#fb8c00'], ['repeated vertex', '#d81b60'], ['column not covered once', '#fdd835'], ['off the stair-step grid', '#8e24aa'], ['ok', '#c9ced6']],
             f: f => { const b = flags[f]; return b & 1 ? C('#e53935') : b & 2 ? C('#fb8c00') : b & 4 ? C('#d81b60') : b & 8 ? C('#fdd835') : b & 16 ? C('#8e24aa') : C('#c9ced6'); }},
};
function recolour() {
  const p = palettes[document.getElementById('mode').value];
  for (const mesh of layers) {
    const col = mesh.geometry.attributes.color.array, tris = mesh.userData.tris;
    tris.forEach((n, q) => { const c = p.f(triFace[n]); for (let v = 0; v < 3; v++) col.set([c.r, c.g, c.b], q * 9 + v * 3); });
    mesh.geometry.attributes.color.needsUpdate = true;
  }
  document.getElementById('legend').innerHTML = p.items.map(([n, c]) => `<div><span class="sw" style="background:${c}"></span>${n}</div>`).join('');
}
document.getElementById('mode').onchange = recolour;
[0, 1, 2].forEach(t => document.getElementById('l' + t).onchange = e => { layers[t].visible = e.target.checked; });
document.getElementById('edges').onchange = e => { edgeLines.visible = e.target.checked; };
const zs = document.getElementById('zs');
function setZ() { group.scale.y = +zs.value; document.getElementById('zsv').textContent = '×' + zs.value; }
zs.oninput = setZ; zs.value = D.zscale; setZ();
if (D.findings.some(f => f.level === 'error')) document.getElementById('mode').value = 'problems';
recolour();

// findings and stats
const fd = document.getElementById('findings');
fd.innerHTML = D.findings.length ? D.findings.map(f => `<div class="finding ${f.level}">${f.message.replace(/^CCT: /, '')}</div>`).join('')
                                 : '<span class="ok">no findings: mesh is consistent and watertight</span>';
const S = D.stats, fmt = (v, d = 0) => typeof v === 'number' ? v.toLocaleString(undefined, {maximumFractionDigits: d}) : v;
const rows = [['faces land / wall / roof', `${S.faces_land} / ${S.faces_wall} / ${S.faces_roof}`],
  ['area land / wall / roof (m²)', `${fmt(S.area_land)} / ${fmt(S.area_wall)} / ${fmt(S.area_roof)}`],
  ['vertices', fmt(S.vertices)], ['columns covered once', (100 * S.columns_covered_once).toFixed(2) + ' %'],
  ['projected area / domain', fmt(S.projected_area_ratio, 4)], ['open interior edges', S.open_interior_edges],
  ['edges in > 2 faces', S.nonmanifold_edges], ['split vertices', S.split_vertices], ['corner vertex aliases', S.corner_vertex_aliases],
  ['unused vertices', S.unused_vertices], ['columns off the stair-step grid', S.stairstep_columns]];
document.getElementById('stats').innerHTML = rows.map(([a, b]) => `<tr><td>${a}</td><td>${b}</td></tr>`).join('');

// problem spots: faces with a finding, grouped into touching 10 m tiles; a click flies the camera there
const fc = new Map();
for (let n = 0; n < triFace.length; n++) {
  const f = triFace[n]; if (!flags[f]) continue;
  let e = fc.get(f); if (!e) fc.set(f, e = [0, 0, 0, 0]);
  for (let v = 0; v < 3; v++) for (let a = 0; a < 3; a++) e[a] += triPos[n * 9 + v * 3 + a];
  e[3] += 3;
}
const tiles = new Map(), T = 10;
fc.forEach((e, f) => {
  const p = [e[0] / e[3], e[1] / e[3], e[2] / e[3]], key = `${Math.floor(p[0] / T)},${Math.floor(p[2] / T)}`;
  (tiles.get(key) || tiles.set(key, []).get(key)).push([f, p]);
});
const spots = [], seen = new Set();
tiles.forEach((_, key) => {
  if (seen.has(key)) return;
  const s = {x: 0, y: 0, z: 0, n: 0, flags: 0, bids: new Set()}, todo = [key]; seen.add(key);
  while (todo.length) {
    const k = todo.pop(), [ti, tj] = k.split(',').map(Number);
    for (const [f, p] of tiles.get(k)) {
      s.x += p[0]; s.y += p[1]; s.z += p[2]; s.n++; s.flags |= flags[f];
      if (stype[f] && bid[f] >= 0) s.bids.add(bid[f]);
    }
    for (let di = -1; di <= 1; di++) for (let dj = -1; dj <= 1; dj++) {
      const nk = `${ti + di},${tj + dj}`;
      if (tiles.has(nk) && !seen.has(nk)) { seen.add(nk); todo.push(nk); }
    }
  }
  s.x /= s.n; s.y /= s.n; s.z /= s.n; spots.push(s);
});
spots.sort((a, b) => b.n - a.n);
const kinds = b => [[1, 'error'], [2, 'open edge'], [4, 'repeated vertex'], [8, 'coverage'], [16, 'stair-step']]
  .filter(([m]) => b & m).map(([, t]) => t).join(', ');
function flyTo(s) {
  const y = s.y * group.scale.y;
  controls.target.set(s.x, y, s.z); camera.position.set(s.x - 25, y + 60, s.z + 40); controls.update();
  document.getElementById('mode').value = 'problems'; recolour();
}
const sd = document.getElementById('spots');
if (!spots.length) sd.innerHTML = '<span class="ok">none</span>';
spots.slice(0, 30).forEach(s => {
  const b = document.createElement('button'); b.className = 'spot';
  const i = Math.floor(s.x / D.dx), j = Math.floor(-s.z / D.dx);
  b.innerHTML = `i ${i}, j ${j} · ${s.n} face${s.n > 1 ? 's' : ''}<br><small>${kinds(s.flags)}` +
                `${s.bids.size ? ' · building ' + [...s.bids].join(', ') : ''}</small>`;
  b.onclick = () => flyTo(s); sd.appendChild(b);
});
if (spots.length > 30) sd.insertAdjacentHTML('beforeend', `<small>${spots.length - 30} more not listed</small>`);
const home = document.createElement('button'); home.className = 'spot'; home.textContent = 'overview';
home.onclick = () => { camera.position.set(cx - span * 0.7, span * 0.6, cz + span * 0.9); controls.target.set(cx, 0, cz); controls.update(); };
sd.appendChild(home);

// picking
const ray = new THREE.Raycaster(), mouse = new THREE.Vector2(); let down = null;
renderer.domElement.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener('pointerup', e => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
  const r = renderer.domElement.getBoundingClientRect();
  mouse.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
  ray.setFromCamera(mouse, camera);
  const hit = ray.intersectObjects(layers.filter(l => l.visible))[0];
  if (!hit) return;
  const f = triFace[hit.object.userData.tris[hit.faceIndex]];
  const names = ['land', 'wall', 'roof'], fl = flags[f], probs = [];
  if (fl & 1) probs.push('error'); if (fl & 2) probs.push('open edge'); if (fl & 4) probs.push('repeated vertex'); if (fl & 8) probs.push('column coverage'); if (fl & 16) probs.push('off the stair-step grid');
  document.getElementById('pick').textContent =
    `face      ${f}\ntype      ${names[stype[f]]}\n[k,j,i]   [${kji[3 * f]}, ${kji[3 * f + 1]}, ${kji[3 * f + 2]}]\n` +
    `area      ${area[f].toFixed(3)} m²\nn_z       ${nz[f].toFixed(3)}\n` +
    (stype[f] ? `building  id ${bid[f]}, type ${btype[f]}\n` : `lsm type  ${['-', 'vegetation', 'pavement', 'water'][lsm[f]]} ${lsmType[f]}\n`) +
    `findings  ${probs.length ? probs.join(', ') : 'none'}`;
});

function resize() { const w = view.clientWidth, h = view.clientHeight; renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); }
addEventListener('resize', resize); resize();
(function loop() { requestAnimationFrame(loop); renderer.render(scene, camera); })();
});
</script>
</body>
</html>
"""

if __name__ == '__main__':
    main()
