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

db="name of database"
schema=inputs_berlin
owner=palm
base_path=downloads
log_file=import_process.log
export PGUSER="postresql user"
export PGPASSWORD="user's password"
export PGHOST=localhost
export PGPORT=5432
export PGDATABASE=$db
export QUIET=1

echo "Importing data to database: ${db}, schema: ${schema}, under schema owner: ${owner}" > ${log_file} 2>&1

psql -d $db -c "create schema if not exists \"$schema\"" >> ${log_file} 2>&1
psql -d $db -c "alter schema \"$schema\" owner to ${owner}" >> ${log_file} 2>&1

# vector layers
vshapes=('ua_clipped.shp' 'osm_clipped.shp')
vlayers=('imported_landcover' 'imported_streetmap')

# raster layers
rshapes=('buildings.tif' 'dem.tif')
rlayers=('imported_buildings' 'imported_dem')

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
