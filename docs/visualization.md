# Visualization, QGIS
The interactive visualization of GIS inputs, processed static driver grid and parameterization can be done using QGIS tool (https://qgis.org/en/site/). To connect QGIS with PostgreSQL please use following steps: \
* Layer > Add Layer > Add PostGIS Layer > New
* Data Source Manager (on the toolbar) > PostgreSQL > New
* Browser panel >> PostgreSQL (Right Click) > New Connection
* Fill name, host, port and database > connect
* Select schema and add layer.

# PALM static driver visualization
For visualization of classical netCDF4 static driver use standard tools for viewing netCDF4 files (such as ncview, Panoply).