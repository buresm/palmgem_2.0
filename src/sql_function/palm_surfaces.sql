CREATE SEQUENCE IF NOT EXISTS spatial_ref_sys_srid_seq MINVALUE 100000;

/************************
* Create table of surfaces
*************************/
drop function if exists palm_vertical_surfaces(
    case_schema text,
    surfaces_table text,
    building_walls_table text,
    dz double precision,
    debug_level integer);

create or replace function palm_vertical_surfaces(
    case_schema text,
    surfaces_table text,
    building_walls_table text,
    dz double precision,
    debug_level integer)
  returns boolean as
$$
declare
    ret boolean;
    sqltext text;
    sqlinsert text;
    sid integer;
    gid integer;
    direction integer;
	azimuth double precision;
	zenith double precision;
    xs double precision;
    ys double precision;
    zs double precision;
    nz_min integer;
    nz_max integer;
	isroof boolean;
	rid integer;
	wid integer;
    nz integer;
begin
    ret = false;

	-- next insert vertical roof surfaces
    raise notice 'Insert vertical surfaces ';
    sqltext = format('select max(sid) from %I.%I', case_schema, surfaces_table);
    execute sqltext into sid;
    if debug_level < 3 then
        raise notice 'sid: %', sid;
    end if;
    sqltext = format('select id, direction, azimuth, zenith, xs, ys, nz_min, nz_max, isroof, rid, wid ' ||
                     'from %I.%I', case_schema, building_walls_table);
    if debug_level < 3 then
        raise notice 'sqltext: %', sqltext;
    end if;
    sqlinsert = format('insert into %I.%I ' ||
                       '(sid, direction, azimuth, zenith, xs, ys, zs, ishorizontal, isroof, gid, rid, wid) ' ||
                       ' values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)',
                       case_schema, surfaces_table);
    if debug_level < 3 then
        raise notice 'sqlinsert: %', sqlinsert;
    end if;

	for gid, direction, azimuth, zenith, xs, ys, nz_min, nz_max, isroof, rid, wid in execute sqltext loop
	    nz = nz_min;
	    while nz <= nz_max-1 loop
	    	sid = sid + 1;
	        zs = dz * (nz + 0.5);
	        execute sqlinsert using sid, direction, azimuth, zenith, xs, ys, zs, false, isroof, gid, rid, wid;
			nz = nz + 1;
			if debug_level < 2 then
                raise notice 'insert: % % % % % % % % % % % %', sid, direction, azimuth, zenith, xs, ys, zs, false, isroof, gid, rid, wid;
	        end if;
	    end loop;
	end loop;

	ret = true;
	return ret;
end
$$
language plpgsql volatile
cost 100;