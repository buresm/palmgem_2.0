# Configuration

## Shared configuration

| Configuration Item | Default value | Description |
|:------------------|:---------------|:---------------|
| **database.host** | localhost | PostgreSQL host name or IP |
| **database.port** | 5432 | PostgreSQL port number |
| **database.user** | unknown | PostgreSQL user name |
| **database.password** | unknown | PostgreSQL password |
| **database.database** | palm_static | PostgreSQL database name |
| **pg_owner** | palm | PostgreSQL owner/group role |
| **ogr2ogr_path** | ogr2ogr | ogr2ogr executable used by `gis_import` for vector files; a bare name is looked up on PATH, otherwise give the full path |
| **raster2psql_path** | raster2pgsql | raster2pgsql executable used by `gis_import` for GeoTIFF rasters |
| **psql_path** | psql | psql executable; `gis_import` pipes the raster2pgsql output into it |
| **run_tasks** | [setup] | Ordered list of task keys to execute (`setup` and `finalize` always run first/last). Available: `gis_import`, `urban_atlas_osm`, `urban_atlas_dem_buildings`, `prepare_slurb`, `initialize_domain`, `lad`, `lai`, `cct_processing`, `static_driver`, `slurb_driver`, `cct_driver`, `pids_check`, `qa_report`, `qgis_export`; see [tasks.md](tasks.md) |
| **data_imports** | see YAML | Files imported by `gis_import`. Each entry under `vectors:` or `rasters:` has `path` (file), `table` (target table in **input_schema**) and `srid`. A user value replaces the defaults wholesale |
| **logs.level** | 25 | Logging verbosity level. See [logging docs](general.md). Values: 5=EXTRA_VERBOSE, 10=DEBUG, 15=VERBOSE, 25=PROGRESS, 30=WARNING, 40=ERROR |
| **logs.level_trees** | -1 | Log level of the tree gridding SQL function (`palm_tree_grid_2`); -1 = same as **logs.level** |
| **logs.level_buildings** | -1 | Per-area log level; -1 = same as **logs.level**. Reserved: no code reads it at present |
| **logs.level_landcover** | -1 | Per-area log level, reserved (see **logs.level_buildings**) |
| **logs.level_build_walls** | -1 | Per-area log level, reserved (see **logs.level_buildings**) |
| **logs.level_check_consistency** | -1 | Per-area log level, reserved (see **logs.level_buildings**) |
| **visual_check.enabled** | False | Write PNG images of every driver variable to `visual_check/` after the static driver is written |
| **visual_check.show_plots** | False | Show plots interactively during generation |
| **srid** | 32632 | SRID of the preprocessing (fishnet, envelope) tables |
| **srid_input** | 32632 | SRID assumed for input layers that carry none |
| **srid_palm** | 32632 | SRID of the PALM grid and the case schema (`domain.cent_x/cent_y` are in this SRID) |
| **dem_srid** | 3035 | SRID of the imported DEM raster (`urban_atlas_dem_buildings`) |
| **srid_utm** | 32632 | SRID of the UTM zone (fishnet/envelope tasks) |
| **srid_wgs84** | 4326 | SRID of WGS84 (origin lat/lon) |

> **The SRID defaults are UTM zone 32N (EPSG:32632).** For a domain in another zone, set `srid`, `srid_input`, `srid_palm` and `srid_utm` together in your user config (e.g. 32633 for the Czech Republic or Berlin). If only some are set, or none, the grid is built in zone 32 and no input data intersects it; the run then fails with missing tables or empty rasters.



## Preprocessor tool
| Configuration Item | Default value | Description |
|:------------------|:---------------|:---------------|
| **domain.name** | input_general | name of case |
| **domain.scenario** | '' | name of case scenario, `<domain.name>_<domain.scenario>` (or the name alone) is the case schema and the base of all output file names |
| **domain.xl** | -1e10 | x lower coordinate of cropping domain |
| **domain.xh** | +1e10 | x top coordinate of cropping domain |
| **domain.yl** | -1e10 | y lower coordinate of cropping domain |
| **domain.yh** | +1e10 | y top coordinate of cropping domain |
| **domain.crop_domain** | False | Option that will crop originally uploaded datasets |
| **domain.fill_boundary** | True | Filling missing places, e.g., sea, ocean |
| **fishnet.dx** | 500.0 | m; cell width of the fishnet that `urban_atlas_osm` uses to split large landcover polygons |
| **fishnet.dy** | 500.0 | m; cell height of that fishnet |
| **tables.im_landcover_or** | imported_landcover | table name in `input_schema` (preprocessing tasks) |
| **tables.im_landcover** | landcover | table name in `input_schema` (preprocessing tasks) |
| **tables.streetmaps_or** | imported_streetmap | table name in `input_schema` (preprocessing tasks) |
| **tables.streetmaps** | streetmap | table name in `input_schema` (preprocessing tasks) |
| **tables.buildings_or** | imported_buildings | table name in `input_schema` (preprocessing tasks) |
| **tables.buildings** | buildings | table name in `input_schema` (preprocessing tasks) |
| **tables.dem_or** | imported_dem | table name in `input_schema` (preprocessing tasks) |
| **tables.dem** | dem | table name in `input_schema` (preprocessing tasks) |
| **tables.fishnet** | fishnet | table name in `input_schema` (preprocessing tasks) |
| **rast_tr.tilewidth** | 32 | Raster tile width in pixels. Not read by the current code: the DEM and building rasters are mosaicked and reprojected without re-tiling |
| **rast_tr.tileheight** | 32 | Raster tile height in pixels (not read by the current code, see **rast_tr.tilewidth**) |
| **rast_tr.scalex** | 25 | Raster pixel size in x (not read by the current code) |
| **rast_tr.scaley** | -25 | Raster pixel size in y, negative = north-up (not read by the current code) |
| **rast_tr.skewx** | 0 | Raster skew in x (not read by the current code) |
| **rast_tr.skewy** | 0 | Raster skew in y (not read by the current code) |
| **max_stl_area** | 50 | Minimum footprint area in m² (despite the name): streetmap/footprint polygons up to this size are dropped before the merge (e.g. sheds and garages below half a 10 m cell) |
| **max_fishnet_split_area** | 5000.0 | m²; landcover polygons larger than this are cut along the fishnet in `urban_atlas_osm`, smaller ones are kept whole |
| **process_streetmaps** | False | Merge OSM/footprint polygons (**tables.streetmaps_or**) into the landcover in the `urban_atlas_osm` task |
| **landcover_has_types** | False | The imported landcover already carries final PALM types in a `type` column (LSM classes only). `urban_atlas_osm` keeps the types as-is instead of mapping UrbanAtlas codes through **mt**; polygons merged via **process_streetmaps** become building polygons with **default_building_type** |
| **default_building_type** | 901 | PALM building type assigned to merged streetmap/footprint polygons when **landcover_has_types** is enabled |
| **mt_default** | 103 | Default type that fills places in case of **domain.fill_boundary**. See Types in [docs](general.md) |
| **clean_up** | False | Delete unused table when they are no longer needed. Use carefully. |
| **mt** | see `default_config_preproc.yaml` | List of `[UrbanAtlas code, PALM type for landcover, PALM type for merged streetmap polygons]`; maps UrbanAtlas and OpenStreetMap classes to PALM types. Table in [mt table](general.md) |



## Static driver preprocessor
| Configuration Item                      | Default value                | Describtion                                                                                                               |
|:----------------------------------------|:-----------------------------|:--------------------------------------------------------------------------------------------------------------------------|
| **input_schema** | inputs_prague | PostGIS schema for the raw imported GIS data (`gis_import`) and the preprocessing results; `initialize_domain` builds the case schema from it |
| **domain.name** | input_general | Name of the case (effective default; `default_config_preproc.yaml` overrides `case_name` from `default_config.yaml`). Always set it |
| **domain.scenario** | '' | Scenario name; the case schema is `<name>_<scenario>`, or just `<name>` when empty |
| **domain.parent_domain_schema** | '' | Name of parent domain schema, in case of nesting setup |
| **domain.dx** | 10.0 | Resolution in x-direction |
| **domain.dy** | 10.0 | Resolution in y-direction |
| **domain.dz** | -1.0 | Resolution in z-direction; -1 = same as **domain.dx** |
| **domain.nx** | 128 | Number of grid cells in x-direction |
| **domain.ny** | 128 | Number of grid cells in y-direction |
| **domain.cent_x** | 459180 | Centre of the domain in **srid_palm**, x-coordinate |
| **domain.cent_y** | 5547800 | Centre of the domain in **srid_palm**, y-coordinate |
| **domain.origin_z** | -1 | m; height of the domain origin written to the driver. -1 = lowest terrain height in the domain. Set it explicitly for nested domains so parent and child share one reference |
| **default_height.0** | 16 | m; height of building type 0 (PIDS building types: 1–3 residential, 4–6 office, by age) where the building-height raster has no value or 0. Types without an entry get dz |
| **default_height.1** | 16 | m; height of building type 1 (PIDS building types: 1–3 residential, 4–6 office, by age) where the building-height raster has no value or 0. Types without an entry get dz |
| **default_height.2** | 16 | m; height of building type 2 (PIDS building types: 1–3 residential, 4–6 office, by age) where the building-height raster has no value or 0. Types without an entry get dz |
| **default_height.3** | 16 | m; height of building type 3 (PIDS building types: 1–3 residential, 4–6 office, by age) where the building-height raster has no value or 0. Types without an entry get dz |
| **default_height.4** | 16 | m; height of building type 4 (PIDS building types: 1–3 residential, 4–6 office, by age) where the building-height raster has no value or 0. Types without an entry get dz |
| **default_height.5** | 16 | m; height of building type 5 (PIDS building types: 1–3 residential, 4–6 office, by age) where the building-height raster has no value or 0. Types without an entry get dz |
| **default_height.6** | 16 | m; height of building type 6 (PIDS building types: 1–3 residential, 4–6 office, by age) where the building-height raster has no value or 0. Types without an entry get dz |
| **tables.grid** | grid | Name of grid table |
| **tables.dem** | dem | Name of DEM table |
| **tables.buildings_height** | buildings | Name of buildings height raster |
| **tables.buildings_grid** | buildings_grid | Name of buildings grid table |
| **tables.landcover** | landcover | Name of landcover table |
| **tables.buildings_offset** | buildings_offset | Name of buildings offset, for filtration routines |
| **tables.aspect** | buildings_aspect_deg | Name of Buldingss aspect table |
| **tables.slope** | buildings_slope_deg | Name of Buildingss slope table |
| **tables.slanted_wall** | slanted_wall | Name of slanted wall table |
| **tables.slanted_roof** | slanted_roof | Name of slanted roof table |
| **tables.slanted_terr_wall** | slanted_terr_wall | Name of slanted terrain wall table |
| **tables.slanted_terrain** | slanted_terrain | Name of slanted terrain table |
| **tables.slanted_wall_gridded_temp** | slanted_wall_gridded_temp | Name of slanted temporal gridded wall table |
| **tables.slanted_wall_gridded** | slanted_wall_gridded | Name of slanted gridded wall table |
| **tables.slanted_roof_gridded_temp** | slanted_roof_gridded_temp | Name of slanted temporal gridded roof table |
| **tables.slanted_roof_gridded** | slanted_roof_gridded | Name of slanted gridded roof table |
| **tables.slanted_terrain_gridded_temp** | slanted_terrain_gridded_temp | Name of slanted temporal gridded terrain table |
| **tables.slanted_terrain_gridded** | slanted_terrain_gridded | Name of slanted gridded terrain table |
| **tables.walls_outer** | walls_outer | Name of outer walls table |
| **tables.slanted_faces** | slanted_faces | Name of slanted faces table |
| **tables.vertices** | vertices | Name of vertices table |
| **tables.land_build** | landcover_buildings | Name of landcover only buildings terrain |
| **tables.build_new** | buildings_new | Name of new buildings table |
| **tables.height_corrected** | building_height_correct | Name of buildings height corrections table |
| **tables.height_terr_corrected** | terrain_height_correct | Name of terrains height corrections table |
| **tables.slanted_wall_points** | slanted_wall_points | Name of slanted points in wall table |
| **tables.extras** | extras | Table for buildings 3d landcover |
| **tables.extras_shp** | extras_shp | Table for buildinds 3d raster |
| **tables.surface_params** | surface_params | Table with physical constant for specific surfaces |
| **tables.building_walls** | building_walls | Table for building wall, parameters feed into building_pars |
| **tables.surfaces** | surfaces | Table for PALM orthogonal building_surface_params |
| **tables.walls** | walls | LOD2 wall lines (input vector, copied into the case schema) |
| **tables.roofs** | roofs | LOD2 roof polygons (input vector) |
| **tables.trees** | trees | Tree input (points with crown and trunk attributes) |
| **tables.trees_grid** | trees_grid | Gridded tree LAD/BAD built by the `lad` task |
| **tables.lai** | lai | Leaf area index raster (input, used with **canopy.using_lai**) |
| **tables.canopy_height** | canopy_height | Canopy height raster (input, used with **canopy.using_lai**) |
| **tables.impervious** | impervious | Impervious-surface raster (input, optional vegetation → pavement correction) |
| **tables.grid_slurb** | grid_slurb | SLURB grid table in the case schema (`slurb_driver`) |
| **tables.centerline** | centerline | Street centre lines derived from the road polygons (`prepare_slurb`) |
| **tables.centerline_simplified** | centerline_simplified | Simplified street centre lines (`prepare_slurb`) |
| **tables.centerline_segments** | centerline_simplified_segments | Centre lines cut into short segments; the SLURB driver also uses them for the canyon-coherence check |
| **tables.centerline_hairy** | centerline_simplified_segments_hairy | Probe lines perpendicular to the street, used to find the buildings on both sides (`prepare_slurb`) |
| **tables.centerline_intersections** | centerline_simplified_intersections | Points where the probe lines meet buildings (`prepare_slurb`) |
| **tables.centerline_results** | centerline_results | Canyon samples: width, building heights on both sides and street orientation (`prepare_slurb`) |
| **tables.outer_wall** | outer_wall | Building outer walls cut into short pieces, each with a building height (`prepare_slurb`) |
| **tables.building_area** | building_area | Wall (façade) and roof area per building (`prepare_slurb`, frontal area fraction) |
| **tables.build_pixel** | build_pixel | Building-height raster pixels as points; temporary (`prepare_slurb`) |
| **idx.landcover** | lid | Landcover unique index |
| **idx.walls** | wid | Walls unique index |
| **idx.roofs** | rid | Roofs unique index |
| **idx.buildings_depth_shp** | gid | Index for buildings depth index |
| **idx.extras_shp** | gid | Index for buildings shape index |
| **idx.trees** | sid | Unique id column of the trees table |
| **idx.centerline** | gid | Unique id column of the centre line table |
| **idx.centerline_segments** | sid | Unique id column of the centre line segments |
| **idx.building_area** | id | Unique id column of the building area table |
| **idx.imported_landcover** | lid | Primary-key column `gis_import` creates for the table `imported_landcover` (in general, `idx.<table>` is the key column of an imported table) |
| **idx.imported_streetmap** | gid | Primary-key column `gis_import` creates for the table `imported_streetmap` |
| **build_3d.bridge_width** | 2.0 | Width of bridge |
| **build_3d.bridge** | bridge | Name for buildings 3d for bridge |
| **build_3d.passage** | passage | Name for buildings 3d for bridge |
| **build_3d.overhanging** | overhang | Name for buildings 3d for bridge |
| **origin_time** | 1970-01-01 00:00:00 | Origin time of simulation |
| **maxbuildingdisance** | 5 | Distance to search in neighbors in case of missing height in buildings grid cell |
| **fill_missing_holes** | True | A switch for filling missing one grid holes in domain. A mimic function for build-in PALM inner function |
| **cortyard_fill.apply** | False | Fill small enclosed courtyards (size counted in grid cells) |
| **cortyard_fill.count** | 30 | Courtyards smaller than this number of grid cells are filled |
| **cortyard_fill.apply_polygon** | False | Fill small enclosed courtyards using the building polygons (size in m²) |
| **cortyard_fill.polygon_area** | 100.0 | m²; with **cortyard_fill.apply_polygon**, enclosed courtyards smaller than this are filled |
| **topo_fill_v2.apply** | False | Fill enclosed air pockets in each vertical level, the way PALM filters topography internally |
| **topo_fill_v2.count** | 9 | Maximum size in grid cells of an enclosed air pocket in one level that **topo_fill_v2** fills |
| **topo_fill_label** | True | Fill isolated air pockets found by connected-component labelling, as PALM does internally (up to 20 passes) |
| **topo_fill_corners** | True | Fill grid cells surrounded by three or more higher neighbours (iterative) |
| **flat_terrain.force** | False | Force flat terrain, not DEM needed. |
| **flat_terrain.height** | 0.0 | Height of the terrain in force dem |
| **force_lsm_only** | False | Option to force static driver into land surface only |
| **force_cyclic** | False | Option to force static driver to cyclic boundary condition |
| **force_cyclic_nc** | 4 | Number of boundary cell to apply cyclic boundary condition |
| **force_building_boundary** | True | Option to delete buildings that are close to domain boarder |
| **force_building_boundary_dist** | 3 | Distance in grid cells for **force_building_boundary**; real distance = value × dx |
| **crop_small_buildings** | False | Crop small buildings, especially in case of slanted faces |
| **small_buildings_area** | 20 | Area in grid points for cropped building if enables |
| **do_cct** | False | Cut-cell topography: slanted terrain, wall and roof faces, written into the static driver by `cct_driver` (run it instead of `static_driver`). Needs a DEM and a building-height raster; switches LOD2 and 3-D buildings off. Experimental, see [cut_cell_topo.md](cut_cell_topo.md) |
| **slanted_pars.max_dist** | 2.0 | m; (CCT) building polygons closer than this are merged |
| **slanted_pars.simplify_dist** | 3.0 | m; (CCT) tolerance for simplifying the merged building outlines |
| **slanted_pars.min_seg** | 2.0 | m; (CCT) outline segments shorter than twice this are corrected |
| **slanted_pars.edge_segment_length** | 1.0 | m; (CCT) building outlines are densified to this spacing before the edge correction |
| **slanted_pars.edge_angle_min** | 105.0 | deg; (CCT) outline vertices with an angle between edge_angle_min and edge_angle_max are candidates for the edge correction |
| **slanted_pars.edge_angle_max** | 245.0 | deg; (CCT) upper limit, see **slanted_pars.edge_angle_min** |
| **slanted_pars.edge_2_edge_distance** | 1.7 | m; (CCT) a vertex is corrected only when its two neighbours are farther apart than this |
| **slanted_pars.corner_passes** | 5 | (CCT) passes of the building corner smoothing; each pass cuts the remaining corners back by about **slanted_pars.edge_segment_length** (a 10 × 10 m building keeps ~98 % of its footprint after 1 pass, ~71 % after 5) |
| **slanted_pars.max_wall_terrain_step** | 0 | dz per dx; (CCT) largest terrain height step next to walls. The wall foot is raised to the terrain beside the wall, which can put a step of several grid levels inside one grid column there; such steps can leave the cut surface inconsistent (corner full/free conflicts, open edges). With a value > 0 (e.g. 1) the lower terrain is raised so the height falls by at most this many levels per grid spacing away from the walls: the step becomes a ramp over the neighbouring cells (terrain changes only next to such steps, rounded up to whole levels). 0 = off |
| **slanted_pars.dist2edge** | 3.0 | m; (CCT) terrain points within twice this distance of a wall are height-corrected |
| **slanted_pars.dist2edge_filter** | 0.6 | m; (CCT) search distance when correcting terrain heights inside buildings |
| **slanted_pars.roofs_dist2edge** | 2.0 | m; (CCT) roof points within this distance of the roof edge are set to floor(height) |
| **slanted_pars.wall_build_height_max_dist** | 2.0 | m; (CCT) search distance for the top and bottom heights of slanted walls in the building-height raster |
| **slanted_pars.off_dist** | 4 | grid cells; (CCT) search limit for the nearest grid point of a slanted face |
| **slanted_pars.empty_vert** | -1 | (CCT) fill value for unused vertex slots of a slanted face |
| **slanted_pars.do_vtk** | True | (CCT) write a VTK file of the slanted faces for inspection, e.g. in ParaView |
| **slanted_pars.clean_up** | True | (CCT) drop the intermediate cut-cell tables when done |
| **building_min_nz** | 1 | Minimum vertical levels of a building cell; heights below dz/2 would otherwise round to 0 and leave zero-height buildings (0 = plain rounding) |
| **boundary_fill_1** | True | Raise the outermost row/column of grid cells to the height of their inner neighbour when that neighbour is higher, so no canyon opens onto the domain boundary |
| **boundary_fill_2** | False | Same as **boundary_fill_1**, for the two outermost rows/columns |
| **vacuum_analyze** | True | `VACUUM (ANALYZE)` the schema a task wrote after every task, and the heavily rewritten tables inside `initialize_domain` and `cct_processing`. The many whole-table UPDATEs otherwise leave the tables and indexes bloated and freshly built tables without planner statistics (autovacuum comes too late). False = rely on autovacuum |
| **landcover.surface_fractions** | False | Compute surface fractions per grid cell. They are not written to the driver (not supported by PALM yet) |
| **landcover.min_fraction** | 0.05 | Minimum fraction of a surface type to be used when **landcover.surface_fractions** is on |
| **zlib** | False | Option that compresses static driver netcdf file |
| **complevel** | 4 | Compression level |
| **fill_values.b** | -127 | Fill value for netCDF file, byte |
| **fill_values.i** | -9999 | Fill value for netCDF file, integer |
| **fill_values.i4** | -9999 | Fill value for netCDF file, integer |
| **fill_values.f4** | -9999.0 | Fill value for netCDF file, float |
| **fill_values.f8** | -9999.0 | Fill value for netCDF file, float8 |
| **ncprops.acronym** | ICS | Global attribute `acronym`: acronym of the institution |
| **ncprops.author** | Jaroslav Resler, resler@cs.cas.cz | Global attribute `author`: name and e-mail of the person who created the file |
| **ncprops.campaign** | '' | Name of campaign |
| **ncprops.comment** | '' | Comment |
| **ncprops.contact_person** | '' | Global attribute `contact_person` |
| **ncprops.data_content** | '' | Global attribute `data_content`: short description of the content |
| **ncprops.dependencies** | '' | Global attribute `dependencies`: files this driver depends on |
| **ncprops.institution** | ICS Prague | Global attribute `institution` |
| **ncprops.keywords** | '' | Global attribute `keywords` |
| **ncprops.location** | '' | Global attribute `location`: place of the domain |
| **ncprops.palm_version** | 6.0 | Global attribute `palm_version`: PALM version the driver is made for |
| **ncprops.references** | '' | Global attribute `references` |
| **ncprops.rotation_angle** | 0.0 | Global attribute `rotation_angle` (deg). PALM-GeM grids are not rotated, keep 0 |
| **ncprops.site** | domain | Global attribute `site`: name of the simulated site |
| **ncprops.source** | '' | Global attribute `source`: input data sources |
| **ncprops.version** | '' | Global attribute `version` of the driver file |
| **ndims.nwater_pars** | 7 | Number of elements in water_pars |
| **ndims.cct_max_num_vertices_per_face** | 7 | Maximum number of vertices of a slanted (cut-cell) face |
| **ndims.dim_3d** | 3 | Number of spatial coordinates of a vertex (cut-cell driver) |
| **ndims.cct_dim_vertex_coords** | 4 | Size of the vertex coordinate dimension of the cut-cell driver |
| **ndims.cct_dim_vertex_shifts** | 1 | Size of the vertex shift dimension of the cut-cell driver |
| **ndims.nalbedo_pars** | 7 | number of elements in albedo_pars |
| **ndims.npavement_pars** | 4 | number of elements in pavement_pars |
| **ndims.npavement_subsurface_pars** | 2 | number of elements in pavement_subsurface_pars |
| **ndims.nsoil_pars** | 8 | number of elements in soil_pars |
| **ndims.nvegetation_pars** | 12 | number of elements in vegetation_pars |
| **ndims.nbuilding_pars** | 150 | number of elements in building_pars |
| **ndims.nbuilding_surface_pars** | 28 | number of elements in building_surface_pars |
| **ndims.nsurface_fraction** | 3 | number of elements in surface_fraction |
| **ndims.building_surface_type** | 9 | Size of the surface-type dimension of the deprecated building variables (**buildings_pars_depricated**) |
| **ndims.building_surface_layer** | 4 | Size of the layer dimension of the deprecated building variables |
| **ndims.building_surface_level** | 3 | Size of the level dimension of the deprecated building variables |
| **ndims.building_general_par** | 2 | Size of the general-parameter dimension of the deprecated building variables |
| **ndims.building_indoor_par** | 19 | Size of the indoor-parameter dimension; not read by the current code |
| **ground.nzsoil** | 8 | number of layers of soil (pavements,...) |
| **ground.nzsoil_surface** | 2 | number of layers of soil (pavements,...) considered as surface layers (filled from capacity_surf, conductivity_surf,...) |
| **ground.soil_type_default** | 3 | Default soil type medium-fine in terms of porosity |
| **ground.dz_soil** | [0.01, 0.02, 0.04, 0.06, 0.14, 0.26, 0.54, 1.86] | default soil layer thickness configuration from PALM |
| **ground.nzwall** | 4 | number of wall layers (fixed to 4 for in PIDS so far) |
| **ground.zwall_norm** | [0.0242, 0.0969, 0.346, 1.0] | Normalised positions of the wall layers (positions, not thicknesses, are read by PALM) |
| **ground.zwindow_norm** | [0.25, 0.5, 0.75, 1.0] | not used so far the thickness of the window fraction cannot be set by PID building_pars |
| **ground.zgreen_norm** | [0.25, 0.5, 0.75, 1.0] | not used so far the thickness of the green fraction cannot be set by PID building_pars |
| **ground.ground_floor_height** | 3 | height of the pedestrian zone (m) (properties of walls are given for low and upper zone) |
| **type_range.vegetation_min** | 100 | First landcover code of vegetation types; code − vegetation_min = PALM `vegetation_type`. See [Types](general.md) |
| **type_range.vegetation_max** | 199 | Last landcover code of vegetation types |
| **type_range.pavement_min** | 200 | First landcover code of pavement types; code − pavement_min = PALM `pavement_type` |
| **type_range.pavement_max** | 299 | Last landcover code of pavement types |
| **type_range.water_min** | 300 | First landcover code of water types; code − water_min = PALM `water_type` |
| **type_range.water_max** | 399 | Last landcover code of water types |
| **type_range.building_min** | 900 | First landcover code of building types; code − building_min = PALM `building_type` |
| **type_range.building_max** | 999 | Last landcover code of building types |
| **type_range.bridge** | 907 | Building type code of bridges (3-D structures) |
| **trees.lad_reduction** | 1.0 | coefficient for reduction of LAD in winter |
| **trees.bad_coef** | 0.1 | coefficient for reduction of BAD from LAD to account branches |
| **trees.nhv** | 10 | number of discretization layers for calculation of tree vertical shapes |
| **trees.nump** | 10 | number of polygon edges for interpolation of cycles for treetops and tree trunks |
| **trees.ext_coef** | 0.6 | Extinction coefficient (same as in PALM code) for tree crown transmissivity |
| **trees.constant_lad** | False | Replace the computed LAD by a constant value in every grid cell that has leaves (whole tree volume); BAD becomes `bad_coef` × that value |
| **trees.constant_lad_val** | 1.6 | The constant LAD [m²/m³] used when `trees.constant_lad` is on |
| **walls.wall_directions** | [[0, 1], [1, 0], [0, -1], [-1, 0]] | wall directions (North, East, South, West) direction = [1, 2, 3, 4] |
| **walls.wall_azimuth** | [0, 90, 180, 270] | wall azimuth (North, East, South, West) |
| **walls.roof_directions** | [1, -1] | roof directions (Up, Down) direction = [0, 5] |
| **walls.roof_zenith** | [0, 180] | roof zenith (Up, Down) |
| **insulation.enabled** | False | Switch to enable insulation |
| **insulation.fields** | [zatepd, zateph] | names of fields in walls table carrying information about insulation (ground, upper) |
| **insulation.building_pars** | [6, 7, 9, 10, 26, 27, 29, 30] | index of parameter in building_pars_wall |
| **insulation.pars_fields** | [1, 1, 1, 1, 0, 0, 0, 0] | index of information field |
| **insulation.pars_items** | [0, 0, 1, 1, 0, 0, 1, 1] | index of replacement value in parameters |
| **insulation.building_surface_pars** | [5, 6, 8, 9] | index of parameter in building_surface_pars |
| **insulation.surface_pars_items** | [0, 0, 1, 1] | Index of the replacement value in **insulation.values** for each **insulation.building_surface_pars** entry |
| **insulation.values** | [39000, 0.035, 30] | capacity: J/kg/K (= 1300 J/kg/K * 30 kg/m3), conductivity: W/m/K, density: kg/m3 |
| **landcover_params_var** | katland | Name of the landcover column with the surface material code. Not set in the defaults; only disabled (commented-out) code reads it |
| **multipolygon** | True | False, multipolygons are splitted into polygons |
| **surf_range.land_min** | 0 | First code of land surface materials in `surface_params` |
| **surf_range.land_max** | 100 | Last code of land surface materials |
| **surf_range.wall_min** | 100 | First code of wall materials |
| **surf_range.wall_max** | 200 | Last code of wall materials |
| **surf_range.roof_min** | 200 | First code of roof materials; added to the roof `material` value to find its row in `surface_params` |
| **surf_range.roof_max** | 300 | Last code of roof materials |
| **minroofthick** | 0.3 | minimal thickness of roofs |
| **minwallthick** | 0.3 | minimal thickness of walls |
| **wintrans** | 0.8 | window transmission (common for all windows for now) |
| **temperatures_indoor.indoor** | 297 | temperatures for indoor buildings |
| **temperatures_indoor.outdoor** | 295 | temperatures for outdoor buildings |
| **water_pars_temp.1** | 283.15 | Water body temperature for type 1 |
| **water_pars_temp.2** | 283.15 | Water body temperature for type 2 |
| **water_pars_temp.3** | 283.15 | Water body temperature for type 3 |
| **water_pars_temp.4** | 283.15 | Water body temperature for type 4 |
| **water_pars_temp.5** | 283.15 | Water body temperature for type 5 |
| **water_pars_temp.6** | 283.15 | Water body temperature for type 6 |
| **water_pars.0** | Not Implemented | water temperature, taken from water_pars_temp according to type |
| **water_pars.1** | Not Implemented | Roughness length for momentum |
| **water_pars.2** | Not Implemented | Roughness length for heat |
| **water_pars.3** | Not Implemented | Heat conductivity between skin layer and water (stable conditions) |
| **water_pars.4** | Not Implemented | Heat conductivity between skin layer and water (unstable conditions) |
| **water_pars.5** | 0 | albedo_type |
| **water_pars.6** | p.emissivity | Surface emissivity |
| **pavement_pars.0** | p.roughness | roughness length for momentum (m) |
| **pavement_pars.1** | p.roughness_h | roughness length for heat (m) |
| **pavement_pars.2** | 0 | albedo type set to 0 = albedo will be supplied in albedo_props |
| **pavement_pars.3** | p.emissivity | emissivity (0-1) |
| **vegetation_pars.0** | Not Implemented | fixme complete Minimum canopy resistance |
| **vegetation_pars.1** | Not Implemented | Leaf area index |
| **vegetation_pars.2** | Not Implemented | Vegetation coverage |
| **vegetation_pars.3** | Not Implemented | Canopy resistance coefficient |
| **vegetation_pars.4** | p.roughness | Roughness length for momentum |
| **vegetation_pars.5** | p.roughness_h | Roughness length for heat |
| **vegetation_pars.6** | Not Implemented | Skin lacer heat conductivity (stable conditions) |
| **vegetation_pars.7** | Not Implemented | Skin layer heat conductivity (unstable conditions) |
| **vegetation_pars.8** | Not Implemented | Fraction of incoming shortwave radiation transmitted directly to the soil (not implemented yet) |
| **vegetation_pars.9** | Not Implemented | Heat capacity of the surface |
| **vegetation_pars.10** | 0 | albedo_type |
| **vegetation_pars.11** | p.emissivity | Surface emissivity |
| **pavement_subsurface_pars.0** | [p.conductivity_surf, p.conductivity_volume] | Thermal conductivity of the respective soil layer (W/m/K) |
| **pavement_subsurface_pars.1** | [p.capacity_surf, p.capacity_volume] | Volumetric heat capacity of the respective soil layer (J/m³/K) |
| **albedo_pars.0** | [l.albedo, coalesce(nullif(r.albedo, 0), pr.albedo), w.albedou] | Broadband albedo (wall fraction in case of building) at (y,x). |
| **albedo_pars.1** | [1-l.emissivity, 1-pr.emissivity, 1-pw.emissivity] | Only for buildings. Longwave albedo of wall fraction at (y,x). |
| **albedo_pars.2** | [l.albedo, coalesce(nullif(r.albedo, 0), pr.albedo), w.albedou] | Only for buildings. Shortwave albedo of wall fraction at (y,x). |
| **albedo_pars.3** | [1-l.emissivity, 1-pr.emissivity, 1-pw.emissivity] | Only for buildings. Longwave albedo of green fraction at (y,x). |
| **albedo_pars.4** | [l.albedo, coalesce(nullif(r.albedo, 0), pr.albedo), w.albedou] | Only for buildings. Shortwave albedo of green fraction at (y,x). |
| **albedo_pars.5** | [1-l.emissivity, 1-pr.emissivity, 1-pw.emissivity] | Only for buildings. Longwave albedo of window fraction at (y,x). |
| **albedo_pars.6** | [l.albedo, coalesce(nullif(r.albedo, 0), pr.albedo), w.albedou] | Only for buildings. Shortwave albedo of window fraction at (y,x). |
| **building_pars.0** | w.wallfracu | Wall fraction above the ground floor level (0-1) |
| **building_pars.1** | w.winfracu | Window fraction above the ground floor level (0-1) |
| **building_pars.2** | 0 | Green fraction on wall above the ground floor level (0-1) |
| **building_pars.3** | 0 | Green fraction on roof (0-1) #NOTE set 0.9 for roof type 4 (lawn) and 0.5 for roof type 5 (ornamental garden) (set according building_pars_repl) |
| **building_pars.4** | 0 | Leaf area index of green fraction on roof (m²/m²) NOTE set 1.4 for roof type 4 (lawn) and 0.4 for roof type 5 (ornamental garden) (set according building_pars_repl) |
| **building_pars.5** | 0 | Leaf area index of green fraction on wall above the ground floor level (m²/m²) |
| **building_pars.6** | pu.capacity_surf | Heat capacity of wall layer 1 above the ground floor level (J/m²/K) |
| **building_pars.7** | pu.capacity_surf | Heat capacity of wall layer 2 above the ground floor level (J/m²/K) |
| **building_pars.8** | pu.capacity_volume | Heat capacity of wall layer 3 above the ground floor level (J/m²/K) |
| **building_pars.9** | pu.conductivity_surf | Thermal conductivity of wall layer 1 above the ground floor level (W/m/K) |
| **building_pars.10** | pu.conductivity_surf | Thermal conductivity of wall layer 2 above the ground floor level (W/m/K) |
| **building_pars.11** | pu.conductivity_volume | Thermal conductivity of wall layer 3 above the ground floor level (W/m/K) |
| **building_pars.12** | 297 | Indoor target summer temperature (K) |
| **building_pars.13** | 295 | Indoor target winter temperature (K) |
| **building_pars.14** | pu.emissivity | Emissivity of wall fraction above the ground floor level (0-1) |
| **building_pars.15** | pu.emissivity | Emissivity of green fraction above the ground floor level (0-1) |
| **building_pars.16** | pu.emissivity | Emissivity of window fraction above the ground floor level (0-1) |
| **building_pars.17** | 0.8 | Transmissivity of window fraction above the ground floor level (0-1) |
| **building_pars.18** | pu.roughness | Roughness length for momentum above the ground floor level (m) |
| **building_pars.19** | pu.roughness_h | Roughness length for heat above the ground floor level (m) |
| **building_pars.20** | 3 | Ground floor height (m) |
| **building_pars.21** | w.wallfracd | Ground floor wall fraction (0-1) |
| **building_pars.22** | w.winfracd | Ground floor window fraction (0-1) |
| **building_pars.23** | 0 | Ground floor green fraction on wall (0-1) |
| **building_pars.24** | 0 | Ground floor green fraction on roof  (0-1) |
| **building_pars.25** | 0 | Ground floor leaf area index of green fraction (wall) (m²/m²) |
| **building_pars.26** | pg.capacity_surf | Ground floor heat capacity of wall layer 1 (J/m²/K) |
| **building_pars.27** | pg.capacity_surf | Ground floor heat capacity of wall layer 2 (J/m²/K) |
| **building_pars.28** | pg.capacity_volume | Ground floor heat capacity of wall layer 3 (J/m²/K) |
| **building_pars.29** | pg.conductivity_surf | Ground floor thermal conductivity of wall layer 1 (W/m/K) |
| **building_pars.30** | pg.conductivity_surf | Ground floor thermal conductivity of wall layer 2 (W/m/K) |
| **building_pars.31** | pg.conductivity_volume | Ground floor thermal conductivity of wall layer 3 (W/m/K) |
| **building_pars.32** | pg.emissivity | Ground floor emissivity of wall fraction (0-1) |
| **building_pars.33** | pg.emissivity | Ground floor emissivity of green fraction (0-1) |
| **building_pars.34** | pg.emissivity | Ground floor emissivity of window fraction (0-1) |
| **building_pars.35** | 0.8 | Ground floor transmissivity of window fraction (0-1) |
| **building_pars.36** | pg.roughness | Ground floor roughness length for momentum (m) |
| **building_pars.37** | pg.roughness_h | Ground floor roughness length for heat (m) |
| **building_pars.38** | 0 | albedo_type of wall fraction, albedo_type = 0 albedo will be supplied by albedo_props |
| **building_pars.39** | 0 | albedo_type of green fraction, albedo_type = 0 albedo will be supplied by albedo_props |
| **building_pars.40** | 0 | albedo_type of window fraction, albedo_type = 0 albedo will be supplied by albedo_props |
| **building_pars.41** | p.thicknes*0.0242 | Wall thickness of layer 1 (m) |
| **building_pars.42** | p.thicknes*0.0969 | Wall thickness of layer 2 (m) |
| **building_pars.43** | p.thicknes*0.346 | Wall thickness of layer 3 (m) |
| **building_pars.44** | p.thicknes*1.0 | Wall thickness of layer 4 (m) |
| **building_pars.45** | pu.capacity_surf | Surface wall heat capacity (J/m²/K) |
| **building_pars.46** | pu.conductivity_surf | Surface wall conductivity (W/m²/K) |
| **building_pars.47** | Not Implemented | Heat capacity of window surface (J/m²/K) |
| **building_pars.48** | Not Implemented | Heat capacity of green surface (J/m²/K) |
| **building_pars.49** | Not Implemented | Thermal conductivity of window surface (W/m/K) |
| **building_pars.50** | Not Implemented | Thermal conductivity of green surface (W/m/K) |
| **building_pars.51** | Not Implemented | Wall fraction ground plate (1) |
| **building_pars.52** | Not Implemented | Thickness of ground plate wall layer 1 (m) |
| **building_pars.53** | Not Implemented | Thickness of ground plate wall layer 2 (m) |
| **building_pars.54** | Not Implemented | Thickness of ground plate wall layer 3 (m) |
| **building_pars.55** | Not Implemented | Thickness of ground plate wall layer 4 (m) |
| **building_pars.56** | Not Implemented | Heat capacity of ground plate wall layers 1 (J/m²/K) |
| **building_pars.57** | Not Implemented | Heat capacity of ground plate wall layer 2 (J/m²/K) |
| **building_pars.58** | Not Implemented | Heat capacity of ground plate wall layer 3 (J/m²/K) |
| **building_pars.59** | Not Implemented | Thermal conductivity of ground plate wall layers 1 (W/m/K) |
| **building_pars.60** | Not Implemented | Thermal conductivity of ground plate wall layer 2 (W/m/K) |
| **building_pars.61** | Not Implemented | Thermal conductivity of ground plate wall layer 3 (W/m/K) |
| **building_pars.62** | p.thicknes*0.0242 | Thickness of first floor wall layer 1 (m) |
| **building_pars.63** | p.thicknes*0.0969 | Thickness of first floor wall layer 2 (m) |
| **building_pars.64** | p.thicknes*0.346 | Thickness of first floor wall layer 3 (m) |
| **building_pars.65** | p.thicknes*1.0 | Thickness of first floor wall layer 4 (m) |
| **building_pars.66** | 0 | Albedo of ground floor wall (1) |
| **building_pars.67** | Not Implemented | Thickness of first floor window layer 1 (m) |
| **building_pars.68** | Not Implemented | Thickness of first floor window layer 2 (m) |
| **building_pars.69** | Not Implemented | Thickness of first floor window layer 3 (m) |
| **building_pars.70** | Not Implemented | Thickness of first floor window layer 4 (m) |
| **building_pars.71** | Not Implemented | Heat capacity of first floor window layers 1 (J/m²/K) |
| **building_pars.72** | Not Implemented | Heat capacity of first floor window layer 2 (J/m²/K) |
| **building_pars.73** | Not Implemented | Heat capacity of first floor window layer 3 (J/m²/K) |
| **building_pars.74** | Not Implemented | Thermal conductivity of first floor window layers 1 (W/m/K) |
| **building_pars.75** | Not Implemented | Thermal conductivity of first floor window layer 2 (W/m/K) |
| **building_pars.76** | Not Implemented | Thermal conductivity of first floor window layer 3 (W/m/K) |
| **building_pars.77** | Not Implemented | Albedo of first floor window (1) |
| **building_pars.78** | Not Implemented | Albedo of first floor green surface (1) |
| **building_pars.79** | Not Implemented | Thickness of standard floor window layer 1 (m) |
| **building_pars.80** | Not Implemented | Thickness of standard floor window layer 2 (m) |
| **building_pars.81** | Not Implemented | Thickness of standard floor window layer 3 (m) |
| **building_pars.82** | Not Implemented | Thickness of standard floor window layer 4 (m) |
| **building_pars.83** | pu.capacity_surf | Heat capacity of standard floor wall layers 1 (J/m²/K) |
| **building_pars.84** | pu.capacity_surf | Heat capacity of standard floor wall layer 2 (J/m²/K) |
| **building_pars.85** | pu.capacity_surf | Heat capacity of standard floor wall layer 3 (J/m²/K) |
| **building_pars.86** | pu.conductivity_surf | Thermal conductivity of standard floor wall layers 1 (W/m/K) |
| **building_pars.87** | pu.conductivity_surf | Thermal conductivity of standard floor wall layer 2 (W/m/K) |
| **building_pars.88** | pu.conductivity_volume | Thermal conductivity of standard floor wall layer 3 (W/m/K) |
| **building_pars.89** | 1.0 | Wall fraction of roof (1) |
| **building_pars.90** | r.thickness*0.01*0.0242 |  |
| **building_pars.91** | r.thickness*0.01*0.0969 |  |
| **building_pars.92** | r.thickness*0.01*0.346 |  |
| **building_pars.93** | r.thickness*0.01*1.0 |  |
| **building_pars.94** | p.capacity_surf | Heat capacity of roof layers 1 (J/m²/K) |
| **building_pars.95** | p.capacity_surf | Heat capacity of roof layer 2 (J/m²/K) |
| **building_pars.96** | p.capacity_volume | Heat capacity of roof layer 3 (J/m²/K) |
| **building_pars.97** | p.conductivity_surf | Thermal conductivity of roof layers 1 (W/m/K) |
| **building_pars.98** | p.conductivity_surf | Thermal conductivity of roof layer 2 (W/m/K) |
| **building_pars.99** | p.conductivity_volume | Thermal conductivity of roof layer 3 (W/m/K) |
| **building_pars.100** | pr.emissivity | Emissivity of roof (1) |
| **building_pars.101** | 0 | Albedo of roof (1) albedo_type = 0 albedo will be supplied by albedo_props |
| **building_pars.102** | 0 | Window fraction of roof (1) |
| **building_pars.103** | Not Implemented | Thickness of roof window layer 1 (m) |
| **building_pars.104** | Not Implemented | Thickness of roof window layer 2 (m) |
| **building_pars.105** | 0.0 | Thickness of roof window layer 3 (m) |
| **building_pars.106** | Not Implemented | Thickness of roof window layer 4 (m) |
| **building_pars.107** | Not Implemented | Heat capacity of window layers 1 (J/m²/K) |
| **building_pars.108** | Not Implemented | Heat capacity of window layer 2 (J/m²/K) |
| **building_pars.109** | Not Implemented | Heat capacity of window layer 3 (J/m²/K) |
| **building_pars.110** | Not Implemented | Thermal conductivity of window layers 1 (W/m/K) |
| **building_pars.111** | Not Implemented | Thermal conductivity of window layer 2 (W/m/K) |
| **building_pars.112** | Not Implemented | Thermal conductivity of window layer 3 (W/m/K) |
| **building_pars.113** | Not Implemented | Emissivity of roof window (1) |
| **building_pars.114** | Not Implemented | Transmissivity of roof window (1) |
| **building_pars.115** | Not Implemented | Albedo of roof window (1) |
| **building_pars.116** | Not Implemented | Emissivity of roof green surface (1) |
| **building_pars.117** | Not Implemented | Albedo of roof green surface (1) |
| **building_pars.118** | Not Implemented | Type of green roof (=1 extensive, =2 intensive)) (1) |
| **building_pars.119** | Not Implemented | Shading factor (1) |
| **building_pars.120** | Not Implemented | Window g-value (1) |
| **building_pars.121** | Not Implemented | Window u-value (W/m²/K) |
| **building_pars.122** | Not Implemented | Basic air flow without occupancy of room (1/h) |
| **building_pars.123** | Not Implemented | Additional air flow during occupancy of room (1/h) |
| **building_pars.124** | Not Implemented | Heat recovery efficiency (1) |
| **building_pars.125** | Not Implemented | Factor for mass specific active surface (1) |
| **building_pars.126** | Not Implemented | Factor for inner heat storage of building zone (J/m²/K) |
| **building_pars.127** | Not Implemented | Ratio of internal surface to floor area (1) |
| **building_pars.128** | Not Implemented | Maximum heating capacity (W) |
| **building_pars.129** | Not Implemented | Maximum cooling capacity (W) |
| **building_pars.130** | Not Implemented | Additional internal heat gains during occupancy of room |
| **building_pars.131** | Not Implemented | Basic internal heat gains without occupancy of room |
| **building_pars.132** | Not Implemented | Storey height (m) |
| **building_pars.133** | Not Implemented | Ceiling construction height  (m) |
| **building_pars.134** | Not Implemented | Technology heating factor for anthropogenic heat losses (1) |
| **building_pars.135** | Not Implemented | Technology cooling factor for anthropogenic heat losses (1) |
| **building_pars.136** | pu.capacity_volume | Heat capacity of wall layer 4 above the ground floor level (J/m²/K) |
| **building_pars.137** | pu.conductivity_volume | Thermal conductivity of wall layer 4 above the ground floor level (W/m/K) |
| **building_pars.138** | pg.capacity_volume | Heat capacity of wall layer 4 at the ground floor level (J/m²/K) |
| **building_pars.139** | pg.conductivity_volume | Thermal conductivity of wall layer 4 at the ground floor level (W/m/K) |
| **building_pars.140** | Not Implemented | Heat capacity of wall layer 4 at ground plate (J/m²/K) |
| **building_pars.141** | Not Implemented | Thermal conductivity of wall layer 4 at ground plate (W/m/K) |
| **building_pars.142** | Not Implemented | Heat capacity of window layer 4 at the ground floor level (J/m²/K) |
| **building_pars.143** | Not Implemented | Thermal conductivity of window layer 4 at the ground floor level (W/m/K) |
| **building_pars.144** | Not Implemented | Heat capacity of window layer 4 above the ground floor level (J/m²/K) |
| **building_pars.145** | Not Implemented | Thermal conductivity of window layer 4 above the ground floor level (W/m/K) |
| **building_pars.146** | p.capacity_surf | Heat capacity of wall layer 4 at roof (J/m²/K) |
| **building_pars.147** | p.conductivity_surf | Thermal conductivity of wall layer 4 at roof (W/m/K) |
| **building_pars.148** | Not Implemented | Heat capacity of window layer 4 at roof (J/m²/K) |
| **building_pars.149** | Not Implemented | Thermal conductivity of window layer 4 at roof  (W/m/K) |
| **building_surface_pars.0** | [1, w.wallfracd, w.wallfracu, 1, 1] | wall fraction (0-1) (set according building_pars_repl) |
| **building_surface_pars.1** | [0, w.winfracd, w.winfracu, 0, 0] | window fraction (0-1)                                                                                                                                                |   no data for window fraction on roofs, set to zero TODO**  | not used so far |
| **building_surface_pars.2** | 0 | green fraction on wall (0-1) not in use set to zero so far TODO |
| **building_surface_pars.3** | 0 | green fraction on roof (0-1) set 0.9 for roof type 4 (lawn) and 0.5 for roof type 5 (ornamental garden) (set according building_pars_repl) |
| **building_surface_pars.4** | 0 | leaf area index of green fraction (roof) set 1.4 for roof type 4 (lawn) and 0.4 for roof type 5 (ornamental garden) (set according building_pars_repl) |
| **building_surface_pars.5** | [pr.capacity_surf, pg.capacity_surf, pu.capacity_surf, pd.capacity_surf, b.capacity_surf] | heat capacity of wall layer 1 |
| **building_surface_pars.6** | [pr.capacity_surf, pg.capacity_surf, pu.capacity_surf, pd.capacity_surf, b.capacity_surf] | heat capacity of wall layer 2 |
| **building_surface_pars.7** | [pr.capacity_volume, pg.capacity_volume, pu.capacity_volume, pd.capacity_volume, b.capacity_volume] | heat capacity of wall layer 3 |
| **building_surface_pars.8** | [pr.conductivity_surf, pg.conductivity_surf, pu.conductivity_surf, pd.conductivity_surf, b.conductivity_surf] | thermal conductivity of wall layer 1 |
| **building_surface_pars.9** | [pr.conductivity_surf, pg.conductivity_surf, pu.conductivity_surf, pd.conductivity_surf, b.conductivity_surf] | thermal conductivity of wall layer 2 |
| **building_surface_pars.10** | [pr.conductivity_volume, pg.conductivity_volume, pu.conductivity_volume, pd.conductivity_volume, b.conductivity_volume] | thermal conductivity of wall layer 3 |
| **building_surface_pars.11** | 297 | indoor target summer temperature (K) |
| **building_surface_pars.12** | 295 | indoor target winter temperature (K) |
| **building_surface_pars.13** | [pr.emissivity, pg.emissivity, pu.emissivity, pd.emissivity, b.emissivity] | [r.emisivita, w.emisivitad, w.emisivitah, pd.emissivity]                                                                                                             |   emissivity of wall fraction (0-1) |
| **building_surface_pars.14** | [pr.emissivity, pg.emissivity, pu.emissivity, pd.emissivity, b.emissivity] | [r.emisivita, w.emisivitad, w.emisivitah, pd.emissivity]                                                                                                             |   emissivity of green fraction (0-1) |
| **building_surface_pars.15** | [pr.emissivity, pg.emissivity, pu.emissivity, pd.emissivity, b.emissivity] | [r.emisivita, w.emisivitad, w.emisivitah, pd.emissivity]                                                                                                             |   emissivity of window fraction (0-1) |
| **building_surface_pars.16** | 0.8 | transmissivity of window fraction (0-1) TODO temporary transmissivity of window set to fixed parameter wintrans |
| **building_surface_pars.17** | [pr.roughness, pg.roughness, pu.roughness, pd.roughness, b.roughness] | roughness length for momentum (m) [0.021, 0.022, 0.023]                                                                                                              | |
| **building_surface_pars.18** | [pr.roughness_h, pg.roughness_h, pu.roughness_h, pd.roughness_h, b.roughness_h] | roughness length for heat (m) |
| **building_surface_pars.19** | [coalesce(nullif(r.albedo, 0), pr.albedo), w.albedod, w.albedou, pd.albedo, b.albedo] | Broadband albedo of wall fraction |
| **building_surface_pars.20** | [1-pr.emissivity, 1-pg.emissivity, 1-pu.emissivity, 1-pd.emissivity, 1-b.emissivity] | [1-r.emisivita, 1-w.emisivitad, 1-w.emisivitah, 1-pd.emissivity]                                                                                                     |   Longwave albedo | of wall fraction |
| **building_surface_pars.21** | [coalesce(nullif(r.albedo, 0), pr.albedo), w.albedod, w.albedou, pd.albedo, b.albedo] | Shortwave albedo of wall fraction |
| **building_surface_pars.22** | [coalesce(nullif(r.albedo, 0), pr.albedo), w.albedod, w.albedou, pd.albedo, b.albedo] | Broadband albedo of window fraction |
| **building_surface_pars.23** | [1-pr.emissivity, 1-pg.emissivity, 1-pu.emissivity, 1-pd.emissivity, 1-b.emissivity] | [1-r.emisivita, 1-w.emisivitad, 1-w.emisivitah, 1-pd.emissivity]                                                                                                     |   Longwave albedo of window fraction |
| **building_surface_pars.24** | [coalesce(nullif(r.albedo, 0), pr.albedo), w.albedod, w.albedou, pd.albedo, b.albedo] | Shortwave albedo of window fraction |
| **building_surface_pars.25** | [coalesce(nullif(r.albedo, 0), pr.albedo), w.albedod, w.albedou, pd.albedo, b.albedo] | Broadband albedo of green fraction |
| **building_surface_pars.26** | [1-pr.emissivity, 1-pg.emissivity, 1-pu.emissivity, 1-pd.emissivity, 1-b.emissivity] | [1-r.emisivita, 1-w.emisivitad, 1-w.emisivitah, 1-pd.emissivity]                                                                                                     |   Longwave albedo of green fraction |
| **building_surface_pars.27** | [coalesce(nullif(r.albedo, 0), pr.albedo), w.albedod, w.albedou, pd.albedo, b.albedo] | Shortwave albedo of green fraction |
| **soil_moisture_adjust.35** | 1.0 | Prepared, not implemented (missing in the PALM code) |
| **soil_moisture_adjust.36** | 1.0 | Prepared, not yet implemented, missing in PALM code |
| **building_pars_repl.#** | [ [ 99999, 0.5 ], [ 99999, 0.5 ] ] | List of specific replacements in building pars, more info in docs |
| **building_surface_pars_repl.#** | [ [ 99999, 0.5 ], [ 99999, 0.5 ] ] | List of specific replacement in building surface pars, more info in docs |
| **surface_params_file** | surface_params.csv | CSV with the physical parameters of each surface material code (albedo, emissivity, roughness, heat capacity, conductivity, thickness). Loaded into the case schema for LOD2 runs; a relative path resolves against `config/` |
| **buildings_pars_depricated** | False | Write the building parameters in the old per-variable layout (building_albedo_type, building_emissivity, building_fraction, building_heat_capacity, …) instead of `building_pars` |
| **building_albedo_type** | see YAML | Formulas of the deprecated `building_albedo_type` variable, one per surface type (only with **buildings_pars_depricated**) |
| **building_emissivity** | see YAML | Formulas of the deprecated `building_emissivity` variable (only with **buildings_pars_depricated**) |
| **building_fraction** | see YAML | Formulas of the deprecated `building_fraction` variable (only with **buildings_pars_depricated**) |
| **building_general_pars** | see YAML | Values of the deprecated `building_general_pars` variable (only with **buildings_pars_depricated**) |
| **building_heat_capacity** | see YAML | Formulas per surface type and layer of the deprecated `building_heat_capacity` variable |
| **building_heat_conductivity** | see YAML | Formulas per surface type and layer of the deprecated `building_heat_conductivity` variable |
| **building_thickness** | see YAML | Formulas per surface type and layer of the deprecated `building_thickness` variable |
| **building_roughness_length** | see YAML | Formulas per level of the deprecated `building_roughness_length` variable |
| **building_roughness_length_qh** | see YAML | Formulas per level of the deprecated `building_roughness_length_qh` variable |
| **building_transmissivity** | see YAML | Window transmissivity per level of the deprecated `building_transmissivity` variable |
| ****                                    |                                                                                                                         |                                                                                                                                                                      |

| **attribute_mapping.\<table\>.\<standard\>** | `<standard>` (identity) | Per-table column-name map: standard column name → the column name in *your* source file. One name, not a list. Defined in `config/default_attribute_mapping.yaml`; override a value in your user config if your data uses a different name (e.g. `attribute_mapping.trees.treeh: vysstr`). Renaming happens during import. See [Attribute mapping](#attribute-mapping) below. |
| **attribute_spec.\<table\>** |  | Per-table lists of `necessary` and `optional` standard attributes; a missing necessary one aborts the import (developer setting, see [Attribute mapping](#attribute-mapping)) |
| **canopy.using_lai** | False | Use LAI raster instead of point tree data for canopy |
| **canopy.lai_mod** | 1.0 | Multiplier applied to the LAI raster — use for scenario generation |
| **canopy.canopy_height_mod** | 1.0 | Multiplier applied to the canopy height raster — use for scenario generation |
| **prepare_albedo_type** | False | Populate albedo_pars from vegetation/pavement/water type albedo tables instead of the default calculation |
| **vegetation_type_albedos.N.broadband** | varies | Broadband albedo for PALM vegetation type N |
| **vegetation_type_albedos.N.shortwave** | varies | Shortwave albedo for PALM vegetation type N |
| **vegetation_type_albedos.N.longwave** | varies | Longwave albedo for PALM vegetation type N |
| **pavement_type_albedos.N.broadband** | 0.17 | Broadband albedo for PALM pavement type N |
| **water_type_albedos.N.broadband** | 0.06 | Broadband albedo for PALM water type N |
| **building_type_albedos.N.wall.broadband** | varies | Broadband wall albedo for building type N |
| **building_type_albedos.N.roof.broadband** | varies | Broadband roof albedo for building type N |

---

## SLURB (single-layer urban model) driver

Settings in `config/default_slurb.yaml`; enable with `slurb: True` and run `prepare_slurb` → `initialize_domain` → `static_driver` / `slurb_driver` (see [tasks.md](tasks.md)). Variables follow the PALM [SLUrb driver (PIDS_SLURB)](https://docs.palm-model.com/25.10.1/Reference/LES_Model/IO-Files/PIDS_SLURB/) reference.

| Configuration Item | Default value | Description |
|:------------------|:---------------|:---------------|
| **slurb** | False | Produce a SLURB driver and treat building cells as SLUrb cells in the static driver |
| **min_plan_area** | 0.2 | Building plan fraction from which a cell is a SLUrb cell; below it the cell stays pure LSM. With a reference window it is applied to the windowed fraction, identically in the static and SLURB drivers |
| **slurb_clip_margin** | 300.0 | m; `prepare_slurb` processes only the domain plus this margin: street polygons are cut to the box, buildings and building-height raster tiles touching it are taken whole. Keep it above the canyon probe (50 m) + `canyon_search_radius`. 0 = the whole input schema (slow when the input is much larger than the domain; the result then serves any domain inside it) |
| **slurb_centerline_interpolation** | 0.5 | m; point spacing the street outlines are densified to for the Voronoi centre lines in `prepare_slurb`. Larger is faster and gives coarser centre lines |
| **slurb_reference_size** | 100.0 | m; plan/urban/frontal fractions and building height (plan-weighted) are averaged over a sliding window centred on each cell, because the SLUrb guide states the morphology is "well-defined only for reference areas of at least 100×100 m²". The window spans the smallest odd number of cells ≥ the size (11 cells = 110 m at dx = 10 m) and is clipped at the domain edge. The static driver takes the dominant non-urban type over the same window. 0 (or ≤ dx) = per grid cell |
| **slurb_vars_done** | [building_frontal_area_fraction, building_height, building_plan_area_fraction, building_type, street_canyon_aspect_ratio, street_canyon_orientation, urban_fraction] | Variables written to the SLURB driver (only input-derived ones; constant placeholders are commented out) |
| **canyon_search_radius** | 50.0 | m; each SLUrb cell takes its street canyon aspect ratio/orientation from canyon samples within this distance (the samples lie on street centre lines, outside the urban cells) |
| **canyon_neighbours** | 3 | Maximum number of nearest canyon samples averaged per cell (orientation as an axial mean, 0–180°, 0 = south–north) |
| **canyon_orientation_min_coherence** | 0.4 | Keep `street_canyon_orientation` only where the street centrelines within `canyon_search_radius` share a direction: coherence R = length-weighted mean of the doubled street bearings (0 = all directions, 1 = parallel). Below the threshold the orientation is written as fill value, which PALM-SLUrb treats as an isotropic canyon (the aspect ratio is kept). On Kopisty the kept cells match the real streets to a median of 5°. 0 = keep all |
| **frontal_area_factor** | 0.31831 | `building_frontal_area_fraction` = façade area × factor / cell area. Default 1/π: frontal area averaged over all wind directions for convex buildings (mean projected width = perimeter/π). 0.25 = wind normal to one face of a square building; 1.0 = full façade-to-plan ratio |
| **slurb_lsm_bare_soil** | False | Legacy behaviour: turn every non-building landcover type into 101 (bare soil). Off by default because PALM-LSM must keep modelling vegetation, water and open pavement next to SLUrb |
| **slurb_lsm_default_type** | 103 | Landcover type given to the LSM part of a SLUrb cell that contains no vegetation or water (103 = short grass, as the SLUrb guide suggests) |
| **default_building_height** | 20.0 | m; building height for outer-wall pieces with no raster height nearby (`prepare_slurb`) and the starting value of `building_height` in the SLURB grid |
| **slurb_vars** | see YAML | Definition of every SLURB variable (NetCDF type `vt`, `long_name`, `units`, `dims`); only those listed in **slurb_vars_done** are written |
| **ndims_slurb.nroad_3d** | 4 | Number of road layers of the multi-layer SLURB variables (`c_road`, `lambda_road`, `dz_road`). Those variables are not written at present |
| **ndims_slurb.nroof_3d** | 4 | Number of roof layers (see **ndims_slurb.nroad_3d**) |
| **ndims_slurb.nwall_3d** | 4 | Number of wall layers (see **ndims_slurb.nroad_3d**) |
| **ndims_slurb.nwin_3d** | 4 | Number of window layers (see **ndims_slurb.nroad_3d**) |
| **slurb_vars_defaults** | see YAML | Constant albedo, emissivity and roughness per facet (road, roof, wall, window) and heat capacity `c`, conductivity `lambda` and layer thicknesses `dz` per layer stack. Kept for the disabled multi-layer block; not written at present |
| **deep_soil_temperature_default** | 275.0 | K; not used: `deep_soil_temperature` is not written (it would be a constant, not derived from data) |
| **building_indoor_temperature_default** | 300 | K; not used: `building_indoor_temperature` is not written |
| **center_line_length** | 15.0 | m; not read by the current code |
| **building_outer_wall_lenght** | 15.0 | m; not read by the current code (`prepare_slurb` cuts outer walls into 15 m pieces) |

After the SLURB driver is written, the PIDS check (`pids.enabled`) also runs the SLURB consistency rules (`consistency_checks: slurb` in `config/pids_spec.yaml`, taken from PIDS_SLURB and the SLUrb guide). **Errors:** `urban_fraction` with the fill value in any cell (PALM range-checks it in every cell and aborts with SLU0032, so the driver writes 0 for non-urban cells), plan fraction above urban fraction, plan/urban/window fraction outside [0, 1], negative frontal fraction, building height or aspect ratio ≤ 0, orientation outside [0, 360) (fill = isotropic is fine). **Warnings:** a SLUrb cell (urban_fraction ≥ 1 %) without plan fraction, height or aspect ratio (PALM uses the namelist value there), buildings above 60 m (SLUrb "does not perform very well" for deep canopies), values in cells SLUrb ignores (urban_fraction < 1 %).

In SLURB mode the static driver has no buildings (`buildings_2d`, `building_id`, `building_type`): SLUrb models them. Run PALM with the land surface model and SLUrb but without the urban surface model (no `&urban_surface_parameters`): with USM on, PALM requires `building_type` in the static driver and stops with DRV0011 ("minimum requirement for surface classification is not fulfilled").

How the two drivers share a cell: PALM-SLUrb models `urban_fraction` (buildings + streets) and PALM-LSM the rest, which the static driver describes with the cell's dominant non-urban type. Outside SLUrb cells the static driver keeps the real LSM types. Cells without any canyon sample within the radius get no aspect ratio; PALM then falls back to the namelist `street_canyon_aspect_ratio` for exactly those cells.

---

## QA, validation and export tools

| Configuration Item | Default value | Description |
|:------------------|:---------------|:---------------|
| **pids.enabled** | True | Validate each driver NetCDF against the PALM Input Data Standard right after it is written (findings are logged; see `config/pids_spec.yaml`) |
| **pids.strict** | False | Abort the pipeline when the PIDS check reports errors |
| **pids.spec_file** | pids_spec.yaml | PIDS spec file; relative paths resolve against `config/` |
| **qa_report.report_file** | '' | Output path of the `qa_report` HTML; empty means `output/<case_schema>_qa_report.html` |
| **qgis_export.gpkg_file** | '' | Output path of the `qgis_export` GeoPackage; empty means `output/<case_schema>.gpkg` |

## Shortcuts used in building_pars / building_surface_pars formulas

| Shortcut | Meaning |
|:---------|:--------|
| `l` | landcover surface |
| `r` | building roof |
| `w` | building wall (above ground floor level) |
| `pr` | roof surface parameters |
| `pg` | ground floor wall parameters |
| `pu` | upper floor wall parameters |
| `pd` | downward-facing surface |
| `b` | bridge |
| `p` | pavement/general surface |

---

## Attribute mapping

PALM-GeM standardizes the column names of the imported vector layers during the
`initialize_domain` task. The mapping is split across two files:

- **`config/default_attribute_mapping.yaml`** (user-facing). For each input
  table it maps the **standard** column name to the name used in *your* source
  file — one name, not a list. The default is identity (your data already uses
  the standard name). To use your own column name, override just the value in
  your user config:

  ```yaml
  attribute_mapping:
    trees:
      treeh: vysstr        # your file calls tree height "vysstr"
    walls:
      wallcatd: stenakatd
  ```

  During import, any source column that is present is renamed to its standard
  name. Tables are keyed by their logical name from the `tables:` section
  (`landcover`, `walls`, `roofs`, `trees`).

- **`config/default_attribute_spec.yaml`** (developer-facing). For each table it
  lists which standard attributes are `necessary` versus `optional`:

  - a **necessary** attribute that cannot be found (neither the standard nor the
    mapped source column exists) **aborts the import** with an error;
  - any other (optional) missing attribute only logs a **warning** and the run
    continues.

  The check runs only for tables that were actually imported, so level-of-detail
  layers that are simply absent never cause a failure. Surface-property lookup
  columns (emissivity, albedo, roughness, …) live in the user-provided
  `surface_params` table with a fixed schema and are **not** part of this
  per-table renaming — see [LOD2](lod2.md).