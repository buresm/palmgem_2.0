#!/bin/bash

# Copyright 2018-2024 Institute of Computer Science of the Czech Academy of
# Sciences, Prague, Czech Republic. Authors: Martin Bures, Jaroslav Resler.
#
# This file is part of PALM-GeM.
#
# PALM-GeM is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# PALM-GeM is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# PALM-GeM. If not, see <https://www.gnu.org/licenses/>.

db=name_of_database
schema=name_of_schema
owner=palm
base_path=path_2_working_dir
log_file=${base_path}/import_process.log
export PGUSER=your_pg_user
export PGPASSWORD=your_pg_password
export PGHOST=localhost
export PGPORT=5432
export PGDATABASE=$db
export QUIET=1

echo "Importing data to database: ${db}, schema: ${schema}, under schema owner: ${owner}" > ${log_file} 2>&1

psql -d $db -c "create schema if not exists \"$schema\"" >> ${log_file} 2>&1
psql -d $db -c "alter schema \"$schema\" owner to ${owner}" >> ${log_file} 2>&1

# vector layers
vshapes=('landcover.shp' 'roofs.shp' 'walls.shp' 'trees.shp' 'extras_shp.shp')
vlayers=('landcover' 'roofs' 'walls' 'trees' 'extras_shp')

# raster layers
rshapes=('buildings.tif' 'dem.tif' 'extras.tif')
rlayers=('buildings' 'dem' 'extras')

# surface params
surface_params='surface_params.csv'
sp_key='code'
sp_values=('albedo' 'emissivity' 'roughness' 'roughness_h' 'capacity_surf' 'conductivity_surf' 'thicknes' 'capacity_volume' 'conductivity_volume')
sp_desc=('surface' 'storage')
sp_header=true

# copy vector layers
for i in ${!vlayers[*]}; do
  echo $i, ${vshapes[i]}, ${vlayers[i]} >> ${log_file} 2>&1

  sql="drop table if exists \"$schema\".\"${vlayers[i]}\" cascade"
  psql -d $db -c "$sql" >> ${log_file} 2>&1

  ogr2ogr -nln ${vlayers[i]} -nlt PROMOTE_TO_MULTI -lco GEOMETRY_NAME=geom -lco SCHEMA=$schema -lco FID=gid -lco PRECISION=NO -overwrite Pg:"dbname=$db host=$PGHOST user=$PGUSER port=$PGPORT" $base_path/${vshapes[i]} >> ${log_file} 2>&1
  psql -d $db -c "alter table \"$schema\".\"${vlayers[i]}\" owner to ${owner}" >> ${log_file} 2>&1

done

# copy raster layers
for i in ${!rlayers[*]}; do
  echo $i, ${rshapes[i]}, ${rlayers[i]} >> ${log_file} 2>&1

  sql="drop table if exists \"$schema\".\"${rlayers[i]}\" cascade"
  psql -d $db -c "$sql" >> ${log_file} 2>&1

  raster2pgsql -I -C -M -t auto $base_path/${rshapes[i]} -q $schema.${rlayers[i]} | psql -q -b -d $db >> ${log_file} 2>&1
  psql -d $db -c "alter table \"$schema\".\"${rlayers[i]}\" owner to ${owner}" >> ${log_file} 2>&1

done

# create params table and copy data from csv
#
# NOTE (legacy/optional): PALM-GeM now ships surface params as
# config/surface_params.csv and the initialize_domain task builds the
# surface_params table for you (override via the surface_params_file config
# key). This block is no longer required and is kept only for reference / for
# users who prefer to pre-load surface_params into the input schema manually.
if [ -e ${base_path}/${surface_params} ]
then
	echo "Surface params table exist, data are loaded" >> ${log_file} 2>&1
	psql -d $db -c "drop table if exists \"$schema\".surface_params"  >> ${log_file} 2>&1
	psql -d $db -c "create table if not exists \"$schema\".surface_params ($sp_key integer, primary key ($sp_key))" >> ${log_file} 2>&1
	for i in ${!sp_values[*]}; do
	  psql -d $db -c "alter table \"$schema\".surface_params add if not exists ${sp_values[i]} double precision" >> ${log_file} 2>&1
	done
	for i in ${!sp_desc[*]}; do
	  psql -d $db -c "alter table \"$schema\".surface_params add if not exists ${sp_desc[i]} text" >> ${log_file} 2>&1
	done
	psql -d $db -c "\copy \"$schema\".surface_params FROM '$sp' delimiter ',' csv " >> ${log_file} 2>&1
	psql -d $db -c "alter table \"$schema\".surface_params owner to ${owner}" >> ${log_file} 2>&1

	# copy csv tables
	if $sp_header
	then
		psql -d $db -c "\copy \"$schema\".\"surface_params\" FROM '${base_path}/$surface_params' delimiter ',' csv header" >> ${log_file} 2>&1
	else
		psql -d $db -c "\copy \"$schema\".\"surface_params\" FROM '${base_path}/$surface_params' delimiter ','" >> ${log_file} 2>&1
	fi
else
	echo "Surface params does not exists, skip" >> ${log_file} 2>&1
fi