# LOD2 description
More advanced parametrization is available using lod2 switch. It has several mandatory extensions in inputs data. Items bellow show all mandatory items. Furthermore, we include description for all items. Moreover, there is a small example of input data from Prague simulation domain, a brief [description](../examples/prague_lod2/prague_lod2.md). 
### Surface parameters
Table containing physical parameters of user defined surfaces. These ship with PALM-GeM as a material-properties lookup CSV at `config/surface_params.csv` (keyed by integer `code`), and the `initialize_domain` task builds the PostGIS `surface_params` table from it automatically — no separate import step is needed. Point the `surface_params_file` config key at your own CSV (absolute, or relative to `config/`) to override the defaults. The table is only built, and LOD2 surface params only applied, when the input landcover carries a `catland` column referencing these codes. Attributes with brief description is: 
* code: unique index
* albedo: surface albedo
* emissivity: emissivity of surface layer
* roughness: roughness for momentum
* roughness_h: roughness for heat transfer
* capacity_surf: surface layer capacity
* thickness: thickness of surface layer
* capacity_volume: capacity of bulk volume
* conductivity_volume: conductivity of bulk volume (e.g., wall under surface layer)
* surface: text description of surface type
More detailed description of those parameters can be found in PALM documentation website.

### wall
A line shape defining detailed parametrization of vertical walls. In data, we distinguish between lower and upper levels. 
* wid: unique index
* stenakatd: index referring to surface_params table code, physical parameters for lower wall levels 
* stenakath: index referring to surface_params table code, physical parameters for upper wall levels  
* albedod: albedo of lower wall levels
* albedoh: albedo of upper wall levels
* winfracd: window fraction of lower levels
* winfrach: window fraction of upper levels
* wallfracd: wall fraction of lower levels
* wallfrach: wall fraction of upper leves
* zatep: insulation, boolean (integer 0, 1) switch
* geom: line geometry


### roofs
A shape file which defines footprint of buildings roofs with their parameterization. Description of attributes is:
* rid: unique index
* katroof: index referring to surface_params table code, physical parameters for surface related parameters
* material: index referring to surface_params table code, physical parameters for bulk related parameters
* tloustka: thickness of roof
* geom: gis geometry column

### landcover
In case of lod2, landcover is extended with katland index (refers to surface_params code). See [examples/prague_lod2](../examples/prague_lod2/prague_lod2.md) for a working example.

## Workflow
During the whole workflow, the existence of walls, roofs, landcover (katland index) and surface_params is checked. Furthermore, input data are clipped to domain extend (same as in case of lod1). In case of landcover, only standard spatial join between landcover and grid is performed. In case of roofs, spatial join with buldings_grid table is performed. In case of vertical roofs, building_walls table is created. Based on building height in buildings_grid, vertical walls are created with bottom height (0 in case of 2d building, nz_min in case of 3d) and top height. Also, roof vertical walls are created and marked as roof walls (for further parametrization as roof surfaces). Based on the fact, that only orthogonal surfaces are possible (lod2 is not compatible with cut cell topography), each surface has exactly defined position and orientation (westward, eastward, northward, southward facing). In next steps, horizontal surfaces are created and marked as roof surface with upward orientation. In case of 3D building, also downward faces are generated (with extra vertical walls inside passages, hallways etc.). These surfaces are then spatially joined with appropriate tables, vertical walls with walls table and roof walls with roofs table (buildings 3D join is with extra_shp table). Bridges (type 907 in landcover notation, 7 in PALM notation) are generated with respect to terrain following procedures (more info in PALM docs). \
In final steps, during data downloading into netcdf static driver tables are joined altogether with surface_params. For example in case of building_pars 14 ("Emissivity of wall fraction above the ground floor level (0-1)") emissivity from surface_params table is assigned to given (j,i) gridcell. Detailed parametrization of building_pars is found in default_config.yaml.