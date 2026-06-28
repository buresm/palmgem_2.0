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

/************************
* Generation of the the complete LAD structure of all trees (crown, branches, and trunk)
*************************/
create or replace function palm_tree_grid(
    case_schema text,
    tree_table text,
    tree_grid_table text,
    grid_table text,
    buildings_table text,
    dz double precision,
    nhv integer,
	nump integer,
    lad_reduction double precision,
    bad_coef double precision,
    ext_coef double precision,
    -- debug
    debug_level integer
    )
  returns boolean as
$$
declare
    ret boolean;
    sqltext text;
    text1 text;
    text2 text;
    nx integer;
    ny integer;
    geom_tc geometry;
    tcx double precision;
    tcy double precision;
    geom_cir geometry;
	tid integer;
    th double precision;
    tb double precision;
    tr double precision;
    tt double precision;
    ts double precision;
    tc integer;
    tl double precision;
    lad_red double precision;
    tx double precision;
    ty double precision;
    --maxheight double precision;
    --nlad integer;
    --nbad integer;
    l integer;
    ihv integer;
    hv double precision[];
    h double precision;
    r double precision;
    a double precision;
    x double precision;
    gid integer;
    i integer;
    j integer;
    xcen double precision;
    ycen double precision;
    gr double precision;
    tvc double precision;
    coef double precision;
    ed double precision;
    tlij double precision;
    lad_real double precision;
    max_lad_ji double precision;
    max_bad_ji double precision;
    --tree tree;
    nbad integer;
    nlad integer;
    -- fields of table trees
    tree_id text;
    tree_height text;
    tree_trunk_height text;
    tree_crown_radius text;
    tree_trunk_radius text;
    tree_crown_shape text;
    tree_coniferous text;
    tree_lad text;
    tree_lad_exists boolean;
begin
    ret = false;
    -- name of the fiels in tree table
    tree_id = 'gid';  -- tid
    tree_height = 'treeh'; -- th
    tree_trunk_height = 'trunkh'; -- tb
    tree_crown_radius = 'crownr'; -- tr
    tree_trunk_radius = 'trunkr'; -- tt
    tree_crown_shape = 'crownshp'; -- ts
    tree_coniferous = 'tree_type'; -- tc
    tree_lad = 'ladens'; -- tl

    -- allocate lad array and hv array
    hv = array_fill(0.0::double precision, array[nhv]);

    -- calculate grid properties ("grid radius")
    sqltext = format('select sqrt((xma-xmi)^2 + (yma-ymi)^2 + $1^2)/2. from %I.%I limit 1', case_schema, grid_table); --TODO before loop
    execute sqltext using dz into gr;

    -- check LAD column in tree table
    sqltext = 'SELECT EXISTS(SELECT * FROM information_schema.columns '
              ' WHERE table_schema=$1 AND table_name=$2 AND column_name=$3)';
    execute sqltext using case_schema, tree_table, tree_lad into tree_lad_exists;

    -- read tree properties
    -- formula for calculation of defaults for coniferous and broad-leved trees
    if tree_lad_exists then
	    text1 = format('%I', tree_lad);
	else
        text1 = format('case when %I  = 1 :: varchar then ''1.6'' else ''1.0'' end', tree_coniferous);
	end if;
    -- formula for calculation of lad reduction - leaf and coniferous tree
    text2 = format('case when %I = ''0'' then %s else 1.0 end', tree_coniferous, lad_reduction);
    -- tree information select
    sqltext = format('select %I, %I, %I, %I, %I, ' || text1 || ', ' || text2 ||
                     ', (ST_Dump(geom)).geom, ST_X((ST_Dump(geom)).geom), ST_Y((ST_Dump(geom)).geom) ' ||
                     ' from %I.%I' ||
                     ' where %I > 0 and %I > 0 ',
                     tree_id, tree_height, tree_trunk_height, tree_crown_radius, tree_crown_shape,
					      case_schema, tree_table,
					      tree_height, tree_crown_radius);
	if debug_level < 3 then
        raise notice 'sqltext: %', sqltext;
    end if;
	-- loop over trees
    for tid, th, tb, tr, ts, tl, lad_red, geom_tc, tcx, tcy in execute sqltext loop
        --!!!
        if debug_level < 2 then
            raise notice 'tid, th, tb, tr, ts, tl, lad_redt, cx, tcy = %, %, %, %, %, %, %, %, %',
                          tid, th, tb, tr, ts, tl, lad_red, tcx, tcy;
        end if;

        max_lad_ji = tl * lad_red;
        max_bad_ji = tl * coef * bad_coef;

        -- calculate min and max layer of the tree crown and trunk
        nbad = cast(floor(tb/dz) as integer);
        nlad = cast(ceil(th/dz) as integer);
        --!!!
        if debug_level < 2 then
            raise notice 'nbad, nlad = %, %', nbad, nlad;
        end if;

        -- process individual layers of the tree
        for l in nbad .. nlad loop
            -- calculate tree shapes in layer l and height h (centre of the layer)
            h = (l::double precision+0.5)*dz;
            if debug_level < 2 then
                raise notice '  calculate tree shapes in layer l=% at height % from %..%', l, h, nbad, nlad;
            end if;
            -- discretize tree shape in layer l by nhv sub-layers
            -- first, pre-calculate center of the sublayer
            for ihv in 1 .. nhv loop
                hv[ihv] = (l+(ihv::double precision-0.5)/nhv)*dz;  -- ihv is indexed from 1 !!!
            end loop;
            --!!!
            if debug_level < 2 then
                raise notice 'l, hv = %, %', l, hv;
            end if;
            -- calculate average radius of the tree crown in the layer l
            if ts = 4 then
                -- conic shape
                r = 0;
                for ihv in 1 .. nhv loop
                    r = r + tr * (th-hv[ihv]) / (th-tb);
                end loop;
                r = r / nhv;
                --!!!
                if debug_level < 2 then
                    raise notice 'ts, r = %, %', ts, r;
                end if;
            else
                -- all other shapes are temporary treated as elliptic shape: TODO supply calculation of other shapes
                tvc = (th + tb)/2.0;  -- vertical centre of the tree crown
                a = (th - tb)/2.0 ;    -- vertical half-axis of the tree crown
                r = 0;
                for ihv in 1 .. nhv loop
                    x = abs(hv[ihv]-tvc);
                    --!!!
                    if debug_level < 2 then
                        raise notice 'a, hv[ihv], tvc, x = %, %, %, %', a, hv[ihv], tvc, x;
                    end if;
                    r = r + tr/a * sqrt(greatest(0.0,a*a-x*x));
                end loop;
                r = r / nhv;
                --!!!
                if debug_level < 2 then
                    raise notice 'ts, tvc, a, x, r = %, %, %, %, %', ts, tvc, a, x, r;
                end if;
            end if;
            -- test if we got a real circle
            if r <= 0 then
                if debug_level < 2 then
                    raise notice 'r<=0: true';
                end if;
            else
                if debug_level < 2 then
                    raise notice 'r<=0: false';
                end if;
            end if;
            continue when r <= 0;
            if debug_level < 2 then
                raise notice 'Test';
            end if;
            -- create tree circle geometry for layer l
            sqltext = $mydelim$select ST_Buffer($1, $2, 'quad_segs=10') $mydelim$;
            if debug_level < 3 then
                raise notice 'sqltext: %', sqltext;
            end if;
            execute sqltext using geom_tc, r into geom_cir;

            -- calculate intersection of the circle with affected grid boxes
            sqltext = format('select g.id, g.i, g.j, g.xcen, g.ycen, '||
                             '(ST_Area(ST_Intersection(g.geom, $1))/ST_Area(g.geom))::double precision '||
                             ' from %I.%I g left outer join %I.%I b on b.id = g.id '||
                             ' where ST_Intersects(g.geom, $1) and (b.nz is null or b.nz<= $2)',
                             case_schema, grid_table, case_schema, buildings_table);
            if debug_level < 3 then
                raise notice 'sqltext: %', sqltext;
            end if;
            for gid, i, j, xcen, ycen, coef in execute sqltext using geom_cir, l loop
                --!!!
                if debug_level < 2 then
                    raise notice 'i, j, xcen, ycen, coef = %, %, %, %, %', i, j, xcen, ycen, coef;
                end if;
                -- TODO FIXME simple inaccurate hack for distance from tree crown edge
                ed = greatest(least(th-h, r-sqrt((xcen-tcx)^2+(ycen-tcy)^2))-gr,0.);

                -- calculate lad inside treetop in grid i,j
                tlij = tl / (tl * ext_coef * ed + 1.);
                -- update LAD array in appropriate cell of the indexed array
                lad_real = tlij * coef * lad_red;

                text1 = format('lad_%s', l);
                text2 = format('bad_%s', l);
                sqltext = format('update %I.%I set %I = LEAST(%I + $1, $4), %I = LEAST(%I + $2, $5) where id = $3 ',
                                 case_schema, tree_grid_table, text1, text1, text2, text2);
                if debug_level < 3 then
                    raise notice 'sqltext: %', sqltext;
                end if;
                execute sqltext using lad_real, tl * coef * bad_coef, gid, max_lad_ji, max_bad_ji;
            end loop;
        end loop;

    end loop;
    ret = true;
    return ret;
end
$$
language plpgsql volatile
cost 100;