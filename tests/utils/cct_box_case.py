"""Synthetic cut-cell test case: one box building on flat ground.

Builds a throw-away input schema with exactly what ``initialize_domain`` reads:
a landcover polygon table (short grass, type 103, around one building polygon,
type 901), a flat DEM raster and a building-height raster (height above
ground, 0 outside the building). The domain origin is set half a cell below
the ground, so the terrain lies inside the first cell layer and not on a cell
face, and the building is shifted off the grid lines by OFFSET (an outline lying
exactly on a grid line is the degenerate case of a cut-cell mesh: the method
nudges such wall points 1e-3 cells off the corner, which leaves 1 mm slivers).
The analytic surface areas are:

    roof    = BOX * BOX
    walls   = 4 * BOX * HEIGHT
    terrain = (N * DX)^2 - BOX * BOX
"""
from src.config_loader import load_config

SRID = 32633
N = 32               # cells per side
DX = 1.0
BOX = 10.0           # building side (m)
HEIGHT = 10.0        # building height above ground (m)
GROUND = 250.0       # terrain height a.s.l. (m)
CX, CY = 500000.0, 5550000.0
OFFSET = 0.3         # building centre offset from the domain centre (m), keeps walls off grid lines
BX, BY = CX + OFFSET, CY + OFFSET
INPUT_SCHEMA = 'pytest_cct_inputs'
CASE_NAME, CASE_SCENARIO = 'pytest', 'cct_box'
CASE_SCHEMA = f'{CASE_NAME}_{CASE_SCENARIO}'

EXPECTED_AREAS = {
    'roof': BOX * BOX,
    'wall': 4 * BOX * HEIGHT,
    'land': (N * DX) ** 2 - BOX * BOX,
}


def build_inputs(db, schema=INPUT_SCHEMA):
    """(Re)create the input schema of the box case."""
    half = BOX / 2
    margin = 8.0
    ext = N * DX / 2 + margin
    npx = int(2 * ext / DX)
    ulx, uly = CX - ext, CY + ext
    db.execute(f'drop schema if exists "{schema}" cascade; create schema "{schema}"')
    db.execute(f"""
        create table "{schema}".landcover (lid serial primary key, type integer, geom geometry(polygon, {SRID}));
        insert into "{schema}".landcover (type, geom) values
            (901, st_makeenvelope({BX - half}, {BY - half}, {BX + half}, {BY + half}, {SRID})),
            (103, st_difference(st_makeenvelope({CX - ext}, {CY - ext}, {CX + ext}, {CY + ext}, {SRID}),
                                st_makeenvelope({BX - half}, {BY - half}, {BX + half}, {BY + half}, {SRID})));

        create table "{schema}".dem (rid serial primary key, rast raster);
        insert into "{schema}".dem (rast)
        select st_addband(st_makeemptyraster({npx}, {npx}, {ulx}, {uly}, {DX}, {-DX}, 0, 0, {SRID}),
                          '32BF'::text, {GROUND}, -9999);

        create table "{schema}".buildings (rid serial primary key, rast raster);
        insert into "{schema}".buildings (rast)
        select st_setvalues(
                   st_addband(st_makeemptyraster({npx}, {npx}, {ulx}, {uly}, {DX}, {-DX}, 0, 0, {SRID}),
                              '32BF'::text, 0, -3.4028234663852886e+38),
                   1, array[row(st_makeenvelope({BX - half}, {BY - half}, {BX + half}, {BY + half}, {SRID}),
                                {HEIGHT})::geomval]);
    """)


def box_config(static_file, run_tasks=('initialize_domain', 'cct_driver')):
    """Default configuration plus the box case settings."""
    cfg = load_config('')
    cfg.update_setting('input_schema', INPUT_SCHEMA)
    for key in ('srid', 'srid_input', 'srid_palm', 'srid_utm', 'dem_srid'):
        cfg.update_setting(key, SRID)
    d = cfg.domain
    d.update_setting('name', CASE_NAME)
    d.update_setting('scenario', CASE_SCENARIO)
    d.update_setting('case_schema', CASE_SCHEMA)
    d.update_setting('cent_x', CX)
    d.update_setting('cent_y', CY)
    d.update_setting('nx', N)
    d.update_setting('ny', N)
    for key in ('dx', 'dy', 'dz'):
        d.update_setting(key, DX)
    d.update_setting('origin_z', GROUND - DX / 2)
    d.update_setting('static_driver_file', static_file)
    cfg.update_setting('do_cct', True)
    cfg.update_setting('run_tasks', list(run_tasks))
    cfg.visual_check.update_setting('enabled', False)
    cfg.slanted_pars.update_setting('do_vtk', False)
    # one corner-smoothing pass keeps the footprint close to the analytic one
    # (the default 5 passes chamfer a 10 m box to ~71 % of its area)
    cfg.slanted_pars.update_setting('corner_passes', 1)
    return cfg
