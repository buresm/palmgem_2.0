"""Unit tests for the CCT mesh validator (src/utils/cct_validation.py).

The base case is the cut-cell description of flat terrain at z = 0.5 m over a
2 x 2 grid of 1 m cells: 9 vertices, each 0.5 dz above its corner (dir 0 = +z),
and 4 square land faces in cell layer k = 1. Every test breaks one thing.
"""
import netCDF4
import numpy as np
import pytest

from src.utils.cct_validation import check_cct_geometry, has_cct

NX = NY = 2
DX = 1.0
Z0 = 0.5


def _flat_mesh():
    verts, vcoord, vshift = [], [], []
    vid = {}
    for j in range(NY + 1):
        for i in range(NX + 1):
            vid[(j, i)] = len(verts) + 1            # 1-based, as written by the driver
            verts.append((Z0, j * DX, i * DX))
            vcoord.append((0, j, i, 0))
            vshift.append(Z0 / DX)
    faces, centers, kji = [], [], []
    for j in range(NY):
        for i in range(NX):
            faces.append([vid[(j, i)], vid[(j, i + 1)], vid[(j + 1, i + 1)], vid[(j + 1, i)], -1, -1, -1])
            centers.append((Z0, (j + 0.5) * DX, (i + 0.5) * DX))
            kji.append((1, j, i))
    nf = len(faces)
    return {
        'cct_vertices': np.array(verts).T, 'cct_vertex_coords': np.array(vcoord).T,
        'cct_vertex_shifts': np.array(vshift)[None, :],
        'cct_vertices_per_face': np.array(faces).T, 'cct_num_vertices_per_face': np.full(nf, 4),
        'cct_face_center': np.array(centers).T, 'cct_face_normal_vector': np.tile([[1.0], [0.0], [0.0]], nf),
        'cct_face_area': np.full(nf, DX * DX), 'cct_3d_grid_indices': np.array(kji).T,
        'cct_surface_type_classification': np.zeros(nf, dtype=int),
        'cct_vegetation_type_classification': np.full(nf, 3),
        'cct_pavement_type_classification': np.full(nf, -9999),
        'cct_water_type_classification': np.full(nf, -9999),
    }


DIMS = {
    'cct_vertices': ('dim_3d', 'cct_num_vert'), 'cct_vertex_coords': ('cct_dim_vertex_coords', 'cct_num_vert'),
    'cct_vertex_shifts': ('cct_dim_vertex_shifts', 'cct_num_vert'),
    'cct_vertices_per_face': ('cct_max_num_vertices_per_face', 'cct_num_faces'),
    'cct_num_vertices_per_face': ('cct_num_faces',), 'cct_face_center': ('dim_3d', 'cct_num_faces'),
    'cct_face_normal_vector': ('dim_3d', 'cct_num_faces'), 'cct_face_area': ('cct_num_faces',),
    'cct_3d_grid_indices': ('dim_3d', 'cct_num_faces'), 'cct_surface_type_classification': ('cct_num_faces',),
    'cct_vegetation_type_classification': ('cct_num_faces',), 'cct_pavement_type_classification': ('cct_num_faces',),
    'cct_water_type_classification': ('cct_num_faces',),
}


def _write(path, mesh):
    with netCDF4.Dataset(path, 'w') as ds:
        ds.setncattr('cct_dz', DX)
        ds.createDimension('x', NX)
        ds.createDimension('y', NY)
        ds.createVariable('x', 'f4', ('x',))[:] = (np.arange(NX) + 0.5) * DX
        ds.createVariable('y', 'f4', ('y',))[:] = (np.arange(NY) + 0.5) * DX
        ds.createDimension('dim_3d', 3)
        ds.createDimension('cct_dim_vertex_coords', 4)
        ds.createDimension('cct_dim_vertex_shifts', 1)
        ds.createDimension('cct_max_num_vertices_per_face', 7)
        ds.createDimension('cct_num_vert', mesh['cct_vertices'].shape[1])
        ds.createDimension('cct_num_faces', mesh['cct_face_area'].size)
        for vn in ('zt', 'buildings_2d'):                 # optional stair-step topography
            if vn in mesh:
                ds.createVariable(vn, 'f4', ('y', 'x'), fill_value=-9999.0)[:] = mesh[vn]
        for vn, dims in DIMS.items():
            a = np.asarray(mesh[vn])
            kind = 'f8' if a.dtype.kind == 'f' else 'i4'
            fill = -9999 if vn.endswith('type_classification') and vn != 'cct_surface_type_classification' else None
            ds.createVariable(vn, kind, dims, fill_value=fill)[:] = a


def _check(tmp_path, mesh):
    path = str(tmp_path / 'cct.nc')
    _write(path, mesh)
    with netCDF4.Dataset(path) as ds:
        assert has_cct(ds)
        findings, stats = check_cct_geometry(ds)
    return [m for lvl, m in findings if lvl == 'error'], [m for lvl, m in findings if lvl == 'warning'], stats


def test_flat_terrain_is_clean(tmp_path):
    errors, warnings, stats = _check(tmp_path, _flat_mesh())
    assert errors == [] and warnings == []
    assert stats['faces_land'] == 4
    assert stats['projected_area_ratio'] == pytest.approx(1.0)
    assert stats['columns_covered_once'] == 1.0


@pytest.mark.parametrize('break_it, expected', [
    (lambda m: m['cct_face_normal_vector'].__setitem__((0, 0), np.nan), 'NaN'),
    (lambda m: m['cct_face_normal_vector'].__setitem__((0, 0), 0.5), 'unit length'),
    (lambda m: m['cct_face_area'].__setitem__(1, 0.0), 'zero or negative area'),
    (lambda m: m['cct_vertices_per_face'].__setitem__((2, 0), 99), 'out-of-range vertex index'),
    (lambda m: m['cct_num_vertices_per_face'].__setitem__(0, 2), 'fewer than 3'),
    (lambda m: m['cct_face_center'].__setitem__((2, 0), 1.7), 'outside their (i,j,k) cell'),
    (lambda m: m['cct_vertices'].__setitem__((0, 4), 0.9), 'do not match corner'),
    (lambda m: m['cct_vertex_shifts'].__setitem__((0, 4), 1.5), 'outside [0, 1]'),
    (lambda m: m['cct_surface_type_classification'].__setitem__(0, 5), 'outside 0/1/2'),
    (lambda m: m['cct_pavement_type_classification'].__setitem__(0, 1), 'exactly one vegetation'),
])
def test_each_defect_is_an_error(tmp_path, break_it, expected):
    mesh = _flat_mesh()
    break_it(mesh)
    errors, _, _ = _check(tmp_path, mesh)
    assert any(expected in e for e in errors), errors


def test_wall_without_building_classification_is_error(tmp_path):
    mesh = _flat_mesh()
    mesh['cct_surface_type_classification'][0] = 1
    errors, _, _ = _check(tmp_path, mesh)
    assert any('no building type/id' in e for e in errors), errors


def test_missing_face_opens_the_surface(tmp_path):
    mesh = _flat_mesh()
    mesh['cct_face_area'][3] = 1.0
    mesh['cct_face_normal_vector'][:, 3] = [0.0, 0.0, 1.0]     # face 3 no longer covers its column
    errors, warnings, stats = _check(tmp_path, mesh)
    assert errors == []
    assert any('not covered exactly once' in w for w in warnings)
    assert stats['columns_covered_once'] == 0.75


def test_split_vertex_is_reported(tmp_path):
    mesh = _flat_mesh()
    # give face 0 its own copy of the centre vertex (index 5): same position,
    # new index -> the mesh is no longer connected there
    mesh['cct_vertices'] = np.hstack([mesh['cct_vertices'], mesh['cct_vertices'][:, 4:5]])
    mesh['cct_vertex_coords'] = np.hstack([mesh['cct_vertex_coords'], mesh['cct_vertex_coords'][:, 4:5]])
    mesh['cct_vertex_shifts'] = np.hstack([mesh['cct_vertex_shifts'], mesh['cct_vertex_shifts'][:, 4:5]])
    mesh['cct_vertices_per_face'][2, 0] = 10
    errors, warnings, stats = _check(tmp_path, mesh)
    assert errors == []
    assert stats['split_vertices'] == 1
    assert any('away from a grid corner' in w for w in warnings)


def test_corner_aliases_are_not_a_defect(tmp_path):
    """A vertex on a grid corner may be listed once per edge direction; the
    copies share a position and must not count as a split or open the mesh."""
    mesh = _flat_mesh()
    # terrain exactly on the corner level: shift 0 everywhere, z = 0 ... move
    # the whole mesh to z = 1 (corner of layer k = 1) and alias vertex 5
    mesh['cct_vertices'][0, :] = 1.0
    mesh['cct_vertex_coords'][0, :] = 1
    mesh['cct_vertex_shifts'][:] = 0.0
    mesh['cct_face_center'][0, :] = 1.0
    mesh['cct_vertices'] = np.hstack([mesh['cct_vertices'], mesh['cct_vertices'][:, 4:5]])
    alias = mesh['cct_vertex_coords'][:, 4:5].copy()
    alias[3, 0] = 4                                  # same corner, listed along +x
    mesh['cct_vertex_coords'] = np.hstack([mesh['cct_vertex_coords'], alias])
    mesh['cct_vertex_shifts'] = np.hstack([mesh['cct_vertex_shifts'], [[0.0]]])
    mesh['cct_vertices_per_face'][2, 0] = 10
    errors, warnings, stats = _check(tmp_path, mesh)
    assert errors == [] and warnings == []
    assert stats['corner_vertex_aliases'] == 1
    assert stats['open_interior_edges'] == 0


def test_two_faces_in_one_cell_is_error(tmp_path):
    mesh = _flat_mesh()
    mesh['cct_3d_grid_indices'][:, 1] = mesh['cct_3d_grid_indices'][:, 0]
    mesh['cct_face_center'][:, 1] = mesh['cct_face_center'][:, 0]
    errors, _, _ = _check(tmp_path, mesh)
    assert any('more than one face' in e for e in errors), errors


def test_surface_matching_the_stair_step_grid_is_clean(tmp_path):
    mesh = _flat_mesh()
    mesh['zt'] = np.full((NY, NX), Z0)          # ground at 0.5 m: faces in layer k = 1
    errors, warnings, stats = _check(tmp_path, mesh)
    assert errors == [] and warnings == [] and stats['stairstep_columns'] == 0


def test_surface_off_the_stair_step_grid_is_reported(tmp_path):
    mesh = _flat_mesh()
    mesh['zt'] = np.full((NY, NX), Z0)
    mesh['buildings_2d'] = np.array([[6.0, -9999.0], [-9999.0, -9999.0]])  # a building the mesh does not show
    errors, warnings, stats = _check(tmp_path, mesh)
    assert stats['stairstep_columns'] == 1
    assert any('stair-step' in e for e in errors), errors


def test_unused_vertex_is_reported(tmp_path):
    mesh = _flat_mesh()
    mesh['cct_vertices'] = np.hstack([mesh['cct_vertices'], [[Z0], [0.5], [0.0]]])
    mesh['cct_vertex_coords'] = np.hstack([mesh['cct_vertex_coords'], [[0], [0], [0], [2]]])
    mesh['cct_vertex_shifts'] = np.hstack([mesh['cct_vertex_shifts'], [[0.5]]])
    mesh['cct_vertices'][0, -1] = 0.0                # on the edge from corner (0,0,0) along +y
    errors, warnings, stats = _check(tmp_path, mesh)
    assert errors == [] and stats['unused_vertices'] == 1
