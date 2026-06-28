# Processing of trees in PALM-GEM
A brief overview how tree are processed in PALM-GeM into PALM *static driver*. 
## Input data structure
Following table show requirements for input GIS shape file with trees. The "Standard" column is the name PALM-GeM uses internally; the "Legacy example" shows a historical Czech name. If your source data uses a different column name, map it via `attribute_mapping.trees.<standard>: <your column>` in your config (e.g. `attribute_mapping.trees.treeh: vysstr`) — one name per column — and it is renamed during import. See [Attribute mapping](configuration_docs.md#attribute-mapping).
| Attribute | Type  | Values | Desription |
|:----------|:------|:-------|:----------------------|
| gid       | int   | >1     | unique identified for each tree |
| typstr    | int   | 0, 1,  | Type of tree, see below defined tree types, in case of treelad is not defined |
| vysstr    | real  | > 0.0  | Height of the tree |
| vyskmen   | real  | > 0.0  | Height of tree trunk |
| polokor   | real  | > 0.0  | Radius of tree crown |
| polokmen  | real  | > 0.0  | Radius of tree trunk |
| tvarkor   | int   | 0, 1,  | Shape of tree crown, see below defined tree crown types |
| ladens    | real  | > 0.0  | Leaf area density of tree |
| geom      | point | X,Y    | Coordinates of tree location |
** tree types **
* 0 - lad = 1.6
* 1 - lad = 2.8
* else - lad = 1.6

** tree crown types **
* 0 - Elliptic
* 1 - Elliptic
* 2 - Elliptic
* 3 - Elliptic
* 4 - Conic shape
* else - Elliptic

## Preprocessing into gridded structure
All imported tree are in the first step clipped to domain extent. In *palm_tree_grid.sql* function, the sql function is prepared. 
The algorithm loops over all trees. Beforehand empty columns of lad/bad for each k,j,i gridcell are prepared. For each tree the following steps are performed:
* calculate min, max of tree crown and tree trunk. Cast to gridded integer heights,
* loop over all layers,
* calculate center of each layer, and radius of tree in for each vertical layer based on tree type,
* create buffer around tree based on tree radius,
* calculate intersection area between the buffer and grid,
* for each intersection calculate lad inside gridcell,
* update gridded lad for each i,j,k gridcell
* move to next layer
* move to next tree

## Download into lad / bad variable
During last step of tree preprocessor is to download the data from PostgreSQL database into PALM readable format. For each k,j,i gridcell lad/bad information is taken from database into 3D array of lad/bad. Maximum value of lad/bad (mad_lad/max_lad in configuration) is checked due to overlaps gridded trees. Tree lad reduction is used for reduce lad in winter episodes. 