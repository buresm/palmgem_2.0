/*
 * Copyright 2018-2024 Institute of Computer Science of the Czech Academy of
 * Sciences, Prague, Czech Republic. Authors: Martin Bures, Jaroslav Resler.
 *
 * This file is part of PALM-GeM.
 *
 * PALM-GeM is free software: you can redistribute it and/or modify it under
 * the terms of the GNU General Public License as published by the Free
 * Software Foundation, either version 3 of the License, or (at your option)
 * any later version.
 *
 * PALM-GeM is distributed in the hope that it will be useful, but WITHOUT ANY
 * WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
 * FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
 * details.
 *
 * You should have received a copy of the GNU General Public License along with
 * PALM-GeM. If not, see <https://www.gnu.org/licenses/>.
 */

CREATE SEQUENCE IF NOT EXISTS spatial_ref_sys_srid_seq MINVALUE 100000;

/************************
* It creates grid of name grid_table with size nx,ny.
* The resolution of the grid is dx,dy, center is cx,cy
* and coordinate system srid.
*************************/
drop function if exists palm_create_grid(
    grid_schema text,
    grid_table text,
    nx integer,
    ny integer,
    dx double precision,
    dy double precision,
    grid_xcen double precision,
    grid_ycen double precision,
    srid_palm integer,
    srid_wgs84 integer,
    srid_utm integer,
    pg_owner text,
    debug_level integer);

create or replace function palm_create_grid(
    grid_schema text,
    grid_table text,
    nx integer,
    ny integer,
    dx double precision,
    dy double precision,
    grid_xcen double precision,
    grid_ycen double precision,
    srid_palm integer,
    srid_wgs84 integer,
    srid_utm integer,
    pg_owner text,
    debug_level integer)
  returns boolean as
$$
declare
    ret boolean;
    res text;
    sqltext text;
    sqlinsert text;
    i integer;
    j integer;
    xmin double precision;
    xmax double precision;
    ymin double precision;
    ymax double precision;
    xcen double precision;
    ycen double precision;
    lon double precision;
    lat double precision;
    east double precision;
    north double precision;
    geomtext text;
    geomgrid geometry;
    xorig double precision;
    yorig double precision;
begin
    ret = false;
    sqltext = format('drop table if exists %I.%I ', grid_schema, grid_table);
    execute sqltext;
    -- create new grid table
    sqltext = format('create table %I.%I ( ' ||
        'id serial, ' ||
        'i integer, ' ||
        'j integer, ' ||
        'xmi double precision, ' ||
        'xma double precision, ' ||
        'ymi double precision, ' ||
        'yma double precision,  ' ||
        'xcen double precision, ' ||
        'ycen double precision,  ' ||
        'lon double precision, ' ||
        'lat double precision, ' ||
        '"E_UTM" double precision, ' ||
        '"N_UTM" double precision  ' ||
        ' )', grid_schema, grid_table);
    execute sqltext;
    sqltext = format('ALTER TABLE %I.%I OWNER TO %I', grid_schema, grid_table, pg_owner);
    execute sqltext;
    sqltext = format('alter table %I.%I add primary key (id)', grid_schema, grid_table);
    execute sqltext;
    -- create geometry column
    perform AddGeometryColumn(grid_schema, grid_table, 'geom', srid_palm, 'POLYGON', 2);

    -- calculate bottom left corner of the domain
    xorig = grid_xcen - dx * nx / 2.0;
    yorig = grid_ycen - dy * ny / 2.0;

    -- create particular gridboxes and intersect them with timezones
    sqlinsert = format('insert into %I.%I (' ||
              'i, j, xmi, xma, ymi, yma, xcen, ycen, geom) values (' ||
              '$1, $2, $3, $4, $5, $6, $7, $8, $9 )', grid_schema, grid_table);
    if debug_level < 3 then
        raise notice 'sqlinsert = %', sqlinsert;
    end if;
    for i in 0 .. nx-1 loop
        for j in 0 .. ny-1 loop
        if debug_level < 2 then
            raise notice 'Add gridbox i,j = %,%', i, j;
        end if;
            xmin = xorig+dx*i;
            xmax = xorig+dx*(i+1);
            ymin = yorig+dy*j;
            ymax = yorig+dy*(j+1);
			xcen = (xmin+xmax)/2;
			ycen = (ymin+ymax)/2;
            geomtext = format('POLYGON((%s %s, %s %s, %s %s, %s %s, %s %s))',
                       xmin, ymin, xmax, ymin, xmax, ymax, xmin, ymax, xmin, ymin);
            --raise notice 'geomtext=%', geomtext;
            geomgrid = ST_GeometryFromText(geomtext,srid_palm);
            execute sqlinsert using i, j, xmin, xmax, ymin, ymax, xcen, ycen, geomgrid;
        end loop;
    end loop;

    -- calculate lon,lat and E_UTM and N_UTM
    sqltext = format('update %I.%I set ' ||
              'lon = ST_X(ST_Transform(ST_SetSRID(ST_Point(xcen,ycen),%s),%s)), ' ||
              'lat = ST_Y(ST_Transform(ST_SetSRID(ST_Point(xcen,ycen),%s),%s)), ' ||
              '"E_UTM" = ST_X(ST_Transform(ST_SetSRID(ST_Point(xcen,ycen),%s),%s)), ' ||
              '"N_UTM" = ST_Y(ST_Transform(ST_SetSRID(ST_Point(xcen,ycen),%s),%s))',
               grid_schema, grid_table,
               srid_palm, srid_wgs84, srid_palm, srid_wgs84,
               srid_palm, srid_utm, srid_palm, srid_utm);
    execute sqltext;

    if debug_level < 3 then
        raise notice 'sqltext = %', sqltext;
    end if;

    -- create geometry index
    execute format('create index if not exists %I on %I.%I using gist(geom)',  grid_table||'_geom', grid_schema, grid_table);
    execute format('create index if not exists %I on %I.%I (i,j)',  grid_table||'_i_j', grid_schema, grid_table);

    -- recompile statistics
    sqltext = format('analyze %I.%I', grid_schema, grid_table);
    execute sqltext;

    ret = true;
    return ret;
end
$$
language plpgsql volatile
cost 100;
