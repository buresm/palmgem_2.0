"""Geometric validation of the cut-cell topography (CCT) part of a static driver.

The CCT surfaces are a polygon mesh: ``cct_vertices`` (z, y, x relative to the
domain origin), faces listing 1-based vertex indices in ``cct_vertices_per_face``
and per-face area, normal, centre and grid cell. PALM needs this mesh to be
consistent and, ideally, watertight. The checks below are split by how bad a
violation is:

errors (the driver is not usable as it is)
    - required CCT variables / dimensions missing or of inconsistent size
    - vertex indices out of range, empty slots inside a face, fewer than 3 vertices
    - NaN in vertices, centres, normals or areas
    - normals not of unit length, areas not positive
    - face centre outside its (i, j, k) cell (cell k spans ((k-1)*dz, k*dz])
    - more than one face in a grid cell (the method puts one cut face per cell)
    - a column whose top land/roof face is more than one cell off the stair-step
      topography (zt + buildings_2d) PALM builds its solid grid from (the
      cct_driver aligns the two, see align_stairstep_with_cct)
    - a vertex that does not match its integer description: corner (k, j, i)
      plus ``len`` grid spacings along ``dir`` (0 +z, 1 -z, 2 +y, 3 -y, 4 +x,
      5 -x), or ``len`` outside [0, 1]
    - surface type outside {0 land, 1 wall, 2 roof}; a land face without exactly
      one of vegetation/pavement/water type; a wall/roof face without building
      type and id; a building id that the 2-D ``building_id`` does not contain

warnings (mesh quality; watertightness)
    - vertices sharing a position under different indices away from a grid
      corner (the mesh is not connected there). On a grid corner (shift 0 or 1)
      a vertex is listed once per edge direction; such aliases are counted in
      the stats only, and vertices are identified by position for the edge test
    - faces repeating a vertex
    - interior edges used by one face only (open) or by more than two
    - grid columns whose upward-projected surface (the footprint of each face
      polygon, signed by its normal) is not one cell area; for a closed surface
      every column is covered exactly once
    - vertices that no face uses

Spacing: dx/dy come from the x/y coordinates; dz from the ``cct_dz`` global
attribute the writer stores (dz = dx when it is missing).
"""
from collections import Counter, defaultdict

import numpy as np

ERROR = 'error'
WARNING = 'warning'

REQUIRED = {
    'cct_vertices': ('dim_3d', 'cct_num_vert'),
    'cct_vertex_coords': ('cct_dim_vertex_coords', 'cct_num_vert'),
    'cct_vertex_shifts': ('cct_dim_vertex_shifts', 'cct_num_vert'),
    'cct_vertices_per_face': ('cct_max_num_vertices_per_face', 'cct_num_faces'),
    'cct_num_vertices_per_face': ('cct_num_faces',),
    'cct_face_center': ('dim_3d', 'cct_num_faces'),
    'cct_face_normal_vector': ('dim_3d', 'cct_num_faces'),
    'cct_face_area': ('cct_num_faces',),
    'cct_3d_grid_indices': ('dim_3d', 'cct_num_faces'),
    'cct_surface_type_classification': ('cct_num_faces',),
}
# direction of the vertex shift from its corner, in (z, y, x) order
DIRS = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]])
MAX_LISTED = 5


def has_cct(ds):
    return 'cct_num_faces' in ds.dimensions


def _arr(ds, name, dtype=float):
    return np.ma.filled(ds.variables[name][:].astype(dtype), np.nan if dtype is float else -1)


def _listed(idx):
    idx = list(idx)
    s = ', '.join(str(int(i)) for i in idx[:MAX_LISTED])
    return s + (' ...' if len(idx) > MAX_LISTED else '')


def load_mesh(ds):
    """Read the CCT mesh into plain numpy arrays (vertex indices 0-based,
    -1 for an empty slot)."""
    x, y = ds.variables['x'][:], ds.variables['y'][:]
    dx = float(x[1] - x[0]) if len(x) > 1 else 1.0
    dy = float(y[1] - y[0]) if len(y) > 1 else dx
    dz = float(ds.getncattr('cct_dz')) if 'cct_dz' in ds.ncattrs() else dx
    faces = _arr(ds, 'cct_vertices_per_face', int)
    m = {
        'dx': dx, 'dy': dy, 'dz': dz, 'nx': len(x), 'ny': len(y),
        'vert': _arr(ds, 'cct_vertices'),                       # (3, nv): z, y, x
        'vcoord': _arr(ds, 'cct_vertex_coords', int),           # (4, nv): k, j, i, dir
        'vshift': _arr(ds, 'cct_vertex_shifts').reshape(-1),    # (nv,)
        'faces': np.where(faces > 0, faces - 1, -1),            # (7, nf), 0-based
        'nvert': _arr(ds, 'cct_num_vertices_per_face', int),
        'center': _arr(ds, 'cct_face_center'),                  # (3, nf): z, y, x
        'normal': _arr(ds, 'cct_face_normal_vector'),           # (3, nf): z, y, x
        'area': _arr(ds, 'cct_face_area'),
        'kji': _arr(ds, 'cct_3d_grid_indices', int),            # (3, nf)
        'stype': _arr(ds, 'cct_surface_type_classification', int),
    }
    for vn in ('vegetation', 'pavement', 'water', 'building'):
        key = f'cct_{vn}_type_classification'
        m[vn] = _arr(ds, key, int) if key in ds.variables else None
    m['bid'] = _arr(ds, 'cct_building_id_classification', int) \
        if 'cct_building_id_classification' in ds.variables else None
    return m


def check_cct_geometry(ds, problems=None):
    """Validate the CCT mesh of an open netCDF4 Dataset.
    Returns (findings, stats): findings is a list of (level, message).
    When ``problems`` is a dict, it receives the face indices behind the
    findings ('error', 'open_edge', 'repeat', 'coverage'), e.g. for the viewer."""
    findings = []
    face_err = set()
    err = lambda msg: findings.append((ERROR, 'CCT: ' + msg))
    warn = lambda msg: findings.append((WARNING, 'CCT: ' + msg))

    # 1. structure
    missing = [v for v in REQUIRED if v not in ds.variables]
    if missing:
        err(f'missing variables {missing}')
        return findings, {}
    for vn, dims in REQUIRED.items():
        if tuple(ds.variables[vn].dimensions) != dims:
            err(f'{vn} has dims {ds.variables[vn].dimensions}, expected {dims}')
    if any(f[0] == ERROR for f in findings):
        return findings, {}

    m = load_mesh(ds)
    dx, dy, dz = m['dx'], m['dy'], m['dz']
    nv, nf = m['vert'].shape[1], m['area'].size
    faces, nvert = m['faces'], m['nvert']
    tol = 1e-6 * min(dx, dy, dz)

    # 2. face topology
    slot = np.arange(faces.shape[0])[:, None]
    inside = slot < nvert[None, :]
    bad_n = np.where((nvert < 3) | (nvert > faces.shape[0]))[0]
    if bad_n.size:
        err(f'{bad_n.size} face(s) with fewer than 3 or more than {faces.shape[0]} vertices: {_listed(bad_n)}')
        face_err.update(bad_n.tolist())
    bad_idx = np.where(np.any(inside & ((faces < 0) | (faces >= nv)), axis=0))[0]
    if bad_idx.size:
        err(f'{bad_idx.size} face(s) with an empty or out-of-range vertex index: {_listed(bad_idx)}')
        face_err.update(bad_idx.tolist())
    extra = np.where(np.any(~inside & (faces >= 0), axis=0))[0]
    if extra.size:
        warn(f'{extra.size} face(s) list vertices beyond cct_num_vertices_per_face: {_listed(extra)}')

    # 3. numbers
    for name, a in (('cct_vertices', m['vert']), ('cct_face_center', m['center']),
                    ('cct_face_normal_vector', m['normal']), ('cct_face_area', m['area'])):
        n_nan = int(np.isnan(a).sum())
        if n_nan:
            err(f'{name} contains {n_nan} NaN value(s)')
    norm = np.sqrt((m['normal'] ** 2).sum(axis=0))
    bad = np.where(np.abs(norm - 1.0) > 1e-6)[0]
    if bad.size:
        err(f'{bad.size} normal(s) not of unit length: faces {_listed(bad)}')
        face_err.update(bad.tolist())
    bad = np.where(~(m['area'] > 0))[0]
    if bad.size:
        err(f'{bad.size} face(s) with zero or negative area: {_listed(bad)}')
        face_err.update(bad.tolist())

    # 4. face centre inside its grid cell
    k, j, i = m['kji']
    cz, cy, cx = m['center']
    out = ((cx < i * dx - tol) | (cx > (i + 1) * dx + tol) |
           (cy < j * dy - tol) | (cy > (j + 1) * dy + tol) |
           (cz < (k - 1) * dz - tol) | (cz > k * dz + tol))
    bad = np.where(out)[0]
    if bad.size:
        err(f'{bad.size} face centre(s) outside their (i,j,k) cell: faces {_listed(bad)}')
        face_err.update(bad.tolist())

    # 4b. one cut-cell face per grid cell
    cell_key = (k.astype(np.int64) * (m['ny'] + 1) + j) * (m['nx'] + 1) + i
    keys, first_face, counts = np.unique(cell_key, return_index=True, return_counts=True)
    shared = np.where(np.isin(cell_key, keys[counts > 1]))[0]
    if shared.size:
        err(f'{int((counts > 1).sum())} grid cell(s) hold more than one face (one face per cell expected): '
            f'faces {_listed(shared)}')
        face_err.update(shared.tolist())

    # 5. vertices vs their integer description
    vk, vj, vi, vdir = m['vcoord']
    vlen = m['vshift']
    ok_dir = (vdir >= 0) & (vdir < 6)
    if (~ok_dir).any():
        err(f'{int((~ok_dir).sum())} vertex/vertices with a direction outside 0..5')
    d = DIRS[np.clip(vdir, 0, 5)].T                            # (3, nv)
    spacing = np.array([dz, dy, dx])[:, None]
    rec = np.vstack([vk * dz, vj * dy, vi * dx]) + d * vlen[None, :] * spacing
    resid = np.abs(rec - m['vert']).max(axis=0)
    bad = np.where(ok_dir & (resid > max(tol, 1e-6)))[0]
    if bad.size:
        err(f'{bad.size} vertex/vertices do not match corner + len * dir (max {resid.max():.3g} m): '
            f'{_listed(bad)}')
    bad = np.where((vlen < -1e-9) | (vlen > 1 + 1e-9))[0]
    if bad.size:
        err(f'{bad.size} vertex shift(s) outside [0, 1]: {_listed(bad)}')

    # 6. classification
    st = m['stype']
    bad = np.where(~np.isin(st, (0, 1, 2)))[0]
    if bad.size:
        err(f'{bad.size} face(s) with surface type outside 0/1/2: {_listed(bad)}')
    land = st == 0
    lsm = [m[t] for t in ('vegetation', 'pavement', 'water') if m[t] is not None]
    if lsm:
        n_types = sum((a >= 0).astype(int) for a in lsm)
        bad = np.where(land & (n_types != 1))[0]
        if bad.size:
            err(f'{bad.size} land face(s) without exactly one vegetation/pavement/water type: {_listed(bad)}')
            face_err.update(bad.tolist())
    urban = (st == 1) | (st == 2)
    if urban.any():
        if m['building'] is None or m['bid'] is None:
            err('wall/roof faces present but no building type/id classification')
        else:
            bad = np.where(urban & ((m['building'] < 0) | (m['bid'] < 0)))[0]
            if bad.size:
                err(f'{bad.size} wall/roof face(s) without building type or id: {_listed(bad)}')
                face_err.update(bad.tolist())
            if 'building_id' in ds.variables:
                known = set(np.unique(np.ma.compressed(ds.variables['building_id'][:])).astype(int).tolist())
                ids = set(np.unique(m['bid'][urban & (m['bid'] >= 0)]).tolist())
                unknown = sorted(ids - known)
                if unknown:
                    err(f'{len(unknown)} building id(s) of wall/roof faces not in building_id: {_listed(unknown)}')

    # 7. mesh quality. A vertex lying exactly on a grid corner (shift 0 or 1)
    # is listed once per edge direction it belongs to, so several indices can
    # share one position there; that is part of the format. The mesh checks
    # below therefore identify vertices by position. A shared position that is
    # not a grid corner means the mesh really is split there.
    key = np.round(m['vert'].T / tol).astype(np.int64)
    canon, first = np.empty(nv, dtype=np.int64), {}
    for v in range(nv):
        canon[v] = first.setdefault(tuple(key[v]), v)
    at_corner = (np.abs(vlen) < 1e-9) | (np.abs(vlen - 1) < 1e-9)
    dup = canon != np.arange(nv)
    corner_dup = int((dup & at_corner & at_corner[canon]).sum())
    split = int(dup.sum()) - corner_dup
    if split:
        warn(f'{split} vertex/vertices share a position with another vertex index away from a grid corner '
             f'(mesh not connected there)')
    used = np.zeros(nv, dtype=bool)
    used[faces[(faces >= 0) & (faces < nv)]] = True
    unused = int((~used).sum())
    if unused:
        warn(f'{unused} vertex/vertices not used by any face')

    edges = defaultdict(list)
    repeated_faces = []
    for f in range(nf):
        n = int(nvert[f])
        if n < 3 or n > faces.shape[0]:
            continue
        vs = faces[:n, f].tolist()
        if min(vs) < 0 or max(vs) >= nv:      # already reported as an error
            continue
        if any(a == b for a, b in zip(vs, vs[1:] + vs[:1])):
            repeated_faces.append(f)
        vs = [int(canon[v]) for v in vs]
        for a, b in zip(vs, vs[1:] + vs[:1]):
            if a != b:
                edges[(a, b) if a < b else (b, a)].append(f)
    repeated = len(repeated_faces)
    if repeated:
        warn(f'{repeated} face(s) repeat a vertex')
    vz, vy, vx = m['vert']
    lx, ly = m['nx'] * dx, m['ny'] * dy

    def on_boundary(v):
        return (abs(vx[v]) < tol or abs(vx[v] - lx) < tol or abs(vy[v]) < tol or abs(vy[v] - ly) < tol)

    open_edges = [fs for (a, b), fs in edges.items() if len(fs) == 1 and not (on_boundary(a) and on_boundary(b))]
    open_inner = len(open_edges)
    over = sum(1 for fs in edges.values() if len(fs) > 2)
    if open_inner:
        warn(f'{open_inner} interior edge(s) belong to one face only (surface not closed there)')
    if over:
        warn(f'{over} edge(s) shared by more than two faces')

    # upward-projected area of each face: the exact footprint of its vertex
    # polygon (shoelace), signed by the normal (downward faces subtract).
    # area * n_z is not used: a non-planar face has a tessellated area that is
    # larger than its footprint divided by the mean n_z.
    proj = np.zeros(nf)
    for f in range(nf):
        n = int(nvert[f])
        if n < 3 or n > faces.shape[0]:
            continue
        vs = faces[:n, f]
        if vs.min() < 0 or vs.max() >= nv:
            continue
        px, py = vx[vs], vy[vs]
        shoelace = 0.5 * abs(np.dot(px, np.roll(py, -1)) - np.dot(py, np.roll(px, -1)))
        proj[f] = shoelace * np.sign(m['normal'][0, f])
    cover = defaultdict(float)
    for f in range(nf):
        cover[(int(j[f]), int(i[f]))] += proj[f]
    cell = dx * dy
    ratio = np.array([cover.get((jj, ii), 0.0) / cell for jj in range(m['ny']) for ii in range(m['nx'])])
    off = int((np.abs(ratio - 1.0) > 0.01).sum())
    if off:
        warn(f'{off} of {ratio.size} grid columns are not covered exactly once by upward-facing surface '
             f'(projected face area / cell area outside 1 +- 1 %)')

    # 8. agreement with the stair-step topography PALM builds its grid from:
    # the top land/roof face of a column must lie in the topmost solid cell or
    # the first air cell above it (zt + buildings_2d rounded to dz); the
    # cct_driver aligns the stair-step grid with the cut surface
    stair = []
    stair_cols = 0
    if 'zt' in ds.variables:
        zt = np.ma.filled(ds.variables['zt'][:].astype(float), np.nan)
        b2 = np.zeros_like(zt)
        if 'buildings_2d' in ds.variables:
            b2 = np.nan_to_num(np.ma.filled(ds.variables['buildings_2d'][:].astype(float), np.nan))
        solid_top = np.round((np.nan_to_num(zt) + b2) / dz).astype(np.int64)
        top_face = {}
        for f in np.where(st != 1)[0]:
            c = (int(j[f]), int(i[f]))
            if c not in top_face or k[f] > k[top_face[c]]:
                top_face[c] = f
        stair = [f for c, f in top_face.items()
                 if 0 <= c[0] < solid_top.shape[0] and 0 <= c[1] < solid_top.shape[1]
                 and not 0 <= int(k[f]) - solid_top[c] <= 1]
        stair_cols = len(stair)
        if stair_cols:
            err(f'{stair_cols} grid column(s) whose top land/roof face is more than one cell off the '
                f'stair-step topography zt + buildings_2d (the surface and the solid grid disagree there): '
                f'faces {_listed(stair)}')
            face_err.update(stair)

    if problems is not None:
        bad_cols = {(jj, ii) for jj in range(m['ny']) for ii in range(m['nx'])
                    if abs(cover.get((jj, ii), 0.0) / cell - 1.0) > 0.01}
        problems['error'] = np.array(sorted(face_err), dtype=int)
        problems['open_edge'] = np.array(sorted({fs[0] for fs in open_edges}), dtype=int)
        problems['repeat'] = np.array(repeated_faces, dtype=int)
        problems['coverage'] = np.array([f for f in range(nf) if (int(j[f]), int(i[f])) in bad_cols], dtype=int)
        problems['stairstep'] = np.array(sorted(stair), dtype=int)

    stats = {
        'faces': int(nf), 'vertices': int(nv), 'dx': dx, 'dy': dy, 'dz': dz,
        'faces_land': int(land.sum()), 'faces_wall': int((st == 1).sum()), 'faces_roof': int((st == 2).sum()),
        'area_land': float(m['area'][land].sum()), 'area_wall': float(m['area'][st == 1].sum()),
        'area_roof': float(m['area'][st == 2].sum()),
        'projected_area_ratio': float(proj.sum() / (lx * ly)),
        'columns_covered_once': float((np.abs(ratio - 1.0) <= 0.01).mean()),
        'corner_vertex_aliases': corner_dup, 'split_vertices': split, 'open_interior_edges': int(open_inner),
        'nonmanifold_edges': int(over), 'faces_repeating_vertex': int(repeated),
        'unused_vertices': unused, 'stairstep_columns': stair_cols,
        'faces_per_cell_max': int(counts.max()) if counts.size else 0,
    }
    return findings, stats
