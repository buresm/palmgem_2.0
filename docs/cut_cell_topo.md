# Cut Cell Topography - Slanted surface PALM extension

A more comprehensive model description is currently under preparation and will be publicly available as a peer-reviewed journal article in the future.
## Surface representation
The implementation of a cut-cell topography into PALM is primarily motivated in terms of an accurate representation of the surface energy balance. This compasses geometrical information about the surface such as the coordinates of the mass center (*cct_face_center*), the normal vector (*cct_face_normal_vector*), the surface area per grid cell (*cct_face_area*), the vertices cutting the edges of a grid box (*cct_vertices_per_face*) as well as the corresponding grid indices in the numerical grid where the cut-cell surface is located (*cct_3d_grid_indices*, ordered $k,j,i$). Further on, for each cut-cell surface its general classification is required given by *cct_surface_type_classification* (natural-type: 0, building wall: 1, building roof: 2, default-type: 3). To further classify the cut-cell surface, information about its *cct_vegetation_type_classification*, *cct_water_type_classification*, *cct_pavement_type_classification*, *cct_building_type_classification* and its *cct_building_id_classification* needs to be given.\

The algorithm slightly modifies building and surface polygons to meet the condition “one cut cell per grid cell” and assures a watertight surface envelope. Essential properties are calculated such as the polygon center, normalized normal vector, area, coordinate system for radiation module and indexed coordinates of vertices. Since not all polygon vertices do lie in plane and curved surfaces can occur, the area and normal vector are calculated using a tessellation approach. The cut-cell surface area is the sum of all triangles and the normal vector is an area weighted average from the triangle normal vector.\
In the last step all polygons are checked for their “water-tight” property.

Illustration of the topography representation in a Cartesian framework. The thick black line indicates the step-like approximation of the topography surface in the Cartesian framework. The gray squares indicate the grid point center, while the red dots indicate the location of the surface. \
<img src="figures/normal_vector2.png" alt="image" width="300" height="auto">

Example visualization of cut cell topology representation of Reichtag, Berlin. 256m x 256m in 1m resolution. \
<img src="figures/reichstag.png" alt="image" width="600" height="auto">

## Data processing
Detailed description of data processing can be found in the upcoming publication.

## Running it

Cut-cell topography is a variant of the static driver: the `cct_*` mesh variables are written into the
static driver file together with the usual variables, so run `cct_driver` **instead of** `static_driver`.

```yaml
do_cct: True
run_tasks:
  - initialize_domain
  - lad            # only if the case has trees
  - cct_driver     # writes output/<case>_static.nc including the cct_* variables
```

`cct_processing` builds only the slanted-face tables. It is optional: use it to split a long run into
stages. `cct_driver` reuses its result when it finished on the current case schema (the table
`slanted_faces` carries a completion mark) and otherwise builds the geometry itself.

What it needs and what it changes:

- a DEM and a **building-height raster** (`tables.buildings_height`, height above ground; 0 outside
  buildings) next to the landcover with building polygons (types 900–999);
- building outlines are merged (`slanted_pars.max_dist`), simplified and corner-smoothed
  (`slanted_pars.corner_passes` passes, each cutting corners back by about one
  `edge_segment_length`), the landcover is rebuilt from them and small enclosed courtyards are filled; each merged outline keeps the building type of the original polygon
  it overlaps most;
- **no LOD2 or 3-D buildings**: with `do_cct` the walls/roofs parametrisation (`lod2`) and the 3-D
  extras are switched off, even when those inputs exist. Wall and roof properties then come from the
  building type;
- the terrain next to walls is raised within `slanted_pars.dist2edge` and roof edges are lowered to
  `floor(height)` within `slanted_pars.roofs_dist2edge`, so the result does not reproduce the input
  areas exactly;
- the rebuilt landcover polygons are cleaned of zero-width spikes and slits (a 1 mm opening and
  closing); a spike on a building outline would make the wall line cross a cell several times and
  the wall there would be lost;
- a vertex that ends up on no grid edge (a fold of the terrain inside a cell face) is moved onto the
  nearest edge, keeping the coordinate furthest from a grid line; it then matches its integer
  description;
- the stair-step grid follows the cut surface: before the static variables are written, the top
  land/roof face of every column sets its solid top (`zt` + `buildings_2d`), so that face lies in the
  topmost solid cell or the first air cell. Roof-edge columns the building covers only partly become
  building columns (building id and type of the nearest building cell, no vegetation/pavement/water
  type), building columns whose roof was cut away become ground, and `zt` follows the raised terrain
  next to walls;
- resolution: the method is built for grids that resolve the buildings (about 1–2 m). At 10 m the
  driver is still written, but the mesh validation reports errors where outlines and raster heights do
  not fit the grid (see below).

## Validating the result

Every driver with a `cct_num_faces` dimension is checked by `src/utils/cct_validation.py`, as part of
the PIDS check after writing and in the `pids_check` task. With `pids.strict: True` an error aborts the
run. The log summarises the mesh:

```
CCT mesh: 23121 faces (14940 land, 4674 wall, 3507 roof), 23761 vertices; columns covered once 100.0%, projected area / domain 1.000
```

Errors mean the driver is not usable as it is:

- missing or mis-shaped `cct_*` variables, vertex indices out of range, faces with fewer than 3 vertices;
- NaN values, normals not of unit length, areas not positive;
- a face centre outside its `(i, j, k)` cell (cell `k` spans `((k-1)·dz, k·dz]`);
- more than one face in a grid cell (the method puts one cut face per cell);
- a vertex that does not match its integer description (corner `k, j, i` plus `len` grid spacings
  along `dir`), or `len` outside [0, 1];
- surface types outside 0/1/2, land faces without exactly one vegetation/pavement/water type,
  wall/roof faces without building type and id, building ids missing from `building_id`;
- a column whose top land/roof face is more than one cell off the stair-step topography
  `zt + buildings_2d`, from which PALM builds its solid grid (the surface and the solid cells would
  disagree, e.g. a roof edge over a cell counted as open ground).

Warnings describe how watertight the surface is:

- vertex indices sharing a position away from a grid corner (on a grid corner a vertex is listed once
  per edge direction; those aliases are part of the format and only counted);
- faces repeating a vertex; interior edges belonging to one face only, or to more than two;
- grid columns not covered exactly once by the upward-facing surface (the footprint of each face
  polygon, signed by its normal). For a closed surface every column is covered once;
- vertices that no face uses.

The existing `check_cct_consistency` and `cct_continuity_check` (corner solid/air consistency) still run
when the driver is written.

## 3-D view

`cct_driver` writes `visual_check/<case>/<case>_cct_view.html` when `visual_check.enabled` is on. For any
driver file:

```bash
python -m src.utils.cct_viewer output/<case>_static.nc -o cct_view.html
```

The page (three.js, data embedded, opens in a browser) shows land, wall and roof faces as layers and
colours them by surface type, land class, building, normal direction or by the validation findings
(errors, open edges, repeated vertices, columns not covered once, columns off the stair-step grid). Clicking a face shows its cell, area,
normal, building and findings. The *problem spots* list groups the faces with a finding by location (touching 10 m tiles), largest
first, and a click on a spot flies the camera there. Large pages (several MB) open best from a local web server, e.g.
`python -m http.server --directory visual_check`. `slanted_pars.do_vtk` still writes the VTK file for
ParaView.

## Tests

- `tests/unit/test_cct_validation.py`, `tests/unit/test_cct_viewer.py`: the validator and the viewer on a
  hand-built mesh, one injected defect per test.
- `tests/unit/test_cct_merge.py`: the wall/terrain merge of a wall-foot cell next to plain walls and
  next to merged cells.
- `tests/integration/test_cct_pipeline.py`: a synthetic 10 × 10 × 10 m building on flat ground
  (`tests/utils/cct_box_case.py`, about 20 s) must give a watertight mesh with no finding, the roof at the
  building height and the building ids of `building_id`; a driver-only rerun must reuse the geometry. A
  64 × 64 m patch of the Prague LOD2 example runs as a slow smoke test when `inputs_prague_lod2` is
  imported.

## Known limitations

- Coarse grids (about 5 m and more): outlines and raster heights that do not fit the grid lead to
  singular vertices (kept on their nearest corner and reported), wall/terrain cells that cannot be
  merged (left unmerged and reported) and validation errors.
- Where a wall stands on sloping ground, the cell holding the wall foot merges terrain and wall into
  one face that rises to the wall top. Next to a cell that keeps a plain vertical wall the merged face
  climbs the wall at the shared cell face instead, but only while the face stays within 6 vertices;
  beyond that, and along diagonal walls where the terrain level changes from cell to cell, the two
  faces can still miss each other. The validation reports these as open edges (a few spots in the
  Prague example, well under 0.1 % of the faces).
- A few geometry fix-ups rely on heuristics rather than exact construction (terrain raised next to
  walls, roof edges lowered, corner correction).
- Polygon splitting for mixed-height walls (z1 ≠ z2) and for faces with several top points is incomplete.
- No LOD2 wall/roof material parametrisation.

None of these affect the default (non-CCT) static-driver workflow. A full model description and
validation will accompany the upcoming peer-reviewed publication.
