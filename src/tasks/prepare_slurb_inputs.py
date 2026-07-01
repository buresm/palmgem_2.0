import pandas as pd
import geopandas as gpd
from shapely import wkb
from centerline.geometry import Centerline
from .base import BaseTask
from src.logger import debug, progress, verbose, warning, error, sql_debug, sql_verbose


class PrepareSlurbInputs(BaseTask):
    def run(self):
        self.create_centerlines()
        self.process_centerlines()
        self.calculate_canyon_geometry()
        self.calculate_centerline_results()
        self.calculate_building_front_area()
        self.cleanup()

    def create_centerlines(self):
        progress('creating centerline from landcover')

        # ensure fresh start
        self.execute(f'drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline}"')

        debug('reading landcover parcels from database')
        sql = f"""
            select geom as geom from "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}"
            where type in (201,202,203)
        """
        parcels = pd.read_sql(sql, self.db.engine)
        # Check if there are some parcels, return error and end session
        if parcels.empty:
            error('no landcover parcels found. check that the landcover table is populated and contains type 202 parcels.')
            raise ValueError('no landcover parcels found. check that the landcover table is populated and contains type 202 parcels.')


        # wkb.loads handles a single geometry, not a Series — decode element-wise
        debug('creating centerline from landcover')
        parcels.geom = parcels.geom.apply(lambda g: wkb.loads(g, hex=True))

        centerlines = []
        for index, row in parcels.iterrows():
            try:
                c_line = Centerline(row['geom'])
                centerlines.append(c_line.geometry)
            except Exception as e:
                verbose(f"skipping parcel {index} due to geometry error: {e}")

        debug('uploading centerline to postgis')
        gdf = gpd.GeoDataFrame(geometry=centerlines)
        gdf = gdf.set_crs(f"EPSG:{self.cfg.srid}")
        gdf.to_postgis(
            name=self.cfg.tables.centerline,
            schema=self.cfg.domain.case_schema,
            con=self.db.engine,
            index=False
        )

    def process_centerlines(self):
        progress('processing and simplifying centerline')

        # simplify and merge
        sql_simplify = f"""
            drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline_simplified}";
            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline_simplified}" as
            select
                geometry as geom_original,
                st_simplify(st_linemerge(geometry), 0.5) as geom
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline}";
        """
        self.execute(sql_simplify)
        self.set_table_owner(self.cfg.domain.case_schema, self.cfg.tables.centerline_simplified)

        # cut into segments
        debug('cutting centerline into segments')
        sql_segments = f"""
            drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline_segments}";
            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline_segments}" as
            select (st_dump(geom)).* from "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline_simplified}";
        """
        self.execute(sql_segments)
        self.set_table_owner(self.cfg.domain.case_schema, self.cfg.tables.centerline_segments)

    def calculate_canyon_geometry(self):
        progress('calculating street canyon width and orientation')

        # create 'hairy' perpendicular segments
        sql_hairy = f"""
            drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline_hairy}";
            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline_hairy}" as
            with
                geodata as (select row_number() over() as id, geom from "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline_segments}" where st_length(geom)>40),
                linecut as (select id, st_linesubstring(d.geom, substart, case when subend > 1 then 1 else subend end) geom
                            from (select id, geom, st_length(((geom)::geometry)) len, 15 sublen from geodata) as d
                                cross join lateral (select i, (sublen * i)/len as substart, (sublen * (i+1))/len as subend
                                                    from generate_series(0, floor( d.len / sublen)::integer) as t(i)
                                                    where (sublen * i)/len <> 1.0) as d2),
                rotate as (select id, (st_rotate(st_collect(geom), -pi()/2, st_centroid(geom))) geom from linecut group by id, geom),
                tbld as (select id, (st_dump(geom)).geom geom from rotate),
                bl as (select (st_dump(st_makeline(st_startpoint(geom), st_endpoint(geom)))).geom as geom from tbld)
            select st_makeline(st_translate(a, sin(az2) * len, cos(az2) * len), st_centroid(st_collect(a, b))) as geom_1,
                   st_makeline(st_centroid(st_collect(a, b)), st_translate(b,sin(az1) * len, cos(az1) * len)) as geom_2,
                   st_centroid(st_collect(a, b)) as geom_center
            from (
                select a, b, st_azimuth(a,b) as az1, st_azimuth(b, a) as az2, 50 as len
                from (select st_startpoint(geom) as a, st_endpoint(geom) as b from bl) as sub
            ) as sub2;

            create index if not exists hairy_g1_idx on "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline_hairy}" using gist(geom_1);
            create index if not exists hairy_g2_idx on "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline_hairy}" using gist(geom_2);
            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline_hairy}" add column if not exists gid serial;
        """
        self.execute(sql_hairy)
        self.set_table_owner(self.cfg.domain.case_schema, self.cfg.tables.centerline_hairy)

        # calculate intersections with buildings
        debug('finding building intersection points')
        sql_intersections = f"""
            drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline_intersections}";
            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline_intersections}" as
            select
                cs.*, l_1.point_1, l_2.point_2,
                st_distance(l_1.point_1, l_2.point_2),
                st_collect(array[cs.geom_center, cs.geom_1, cs.geom_2, l_1.point_1, l_2.point_2]) as geom_col
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.centerline_hairy}" cs
                join lateral (select (st_dump(st_intersection(cs.geom_1, st_boundary(l.geom)))).geom as point_1
                              from "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l
                              where l.type between {self.cfg.type_range.building_min} and {self.cfg.type_range.building_max} and st_intersects(cs.geom_1, l.geom)
                              order by st_distance(cs.geom_center, l.geom) asc limit 1) as l_1 on true
                join lateral (select (st_dump(st_intersection(cs.geom_2, st_boundary(l.geom)))).geom as point_2
                              from "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l
                              where l.type between {self.cfg.type_range.building_min} and {self.cfg.type_range.building_max} and st_intersects(cs.geom_2, l.geom)
                              order by st_distance(cs.geom_center, l.geom) asc limit 1) as l_2 on true;
        """
        self.execute(sql_intersections)
        self.set_table_owner(self.cfg.domain.case_schema, self.cfg.tables.centerline_intersections)

    def calculate_centerline_results(self):
        progress('computing canyon orientation, width and building heights')
        schema = self.cfg.domain.case_schema

        # pixel-centre table from buildings raster — used for height lookups here and in building front area
        debug('creating build_pixel from buildings raster')
        sql_pixel = f"""
            drop table if exists "{schema}"."{self.cfg.tables.build_pixel}";
            create table "{schema}"."{self.cfg.tables.build_pixel}" as
            select (st_pixelaspoints(b.rast)).geom as geom,
                   (st_pixelaspoints(b.rast)).val  as val
            from "{schema}"."{self.cfg.tables.buildings_height}" b;
        """
        self.execute(sql_pixel)
        self.set_table_owner(schema, self.cfg.tables.build_pixel)

        debug('computing canyon orientation and width from intersections')
        sql_results = f"""
            drop table if exists "{schema}"."{self.cfg.tables.centerline_results}";
            create table "{schema}"."{self.cfg.tables.centerline_results}" as
            select
                gid,
                degrees(st_azimuth(point_1, point_2)) + 90.0 as orientation,
                st_distance(point_1, point_2)                      as width,
                b1.val                                             as val_1,
                b2.val                                             as val_2,
                geom_center                                        as geom
            from "{schema}"."{self.cfg.tables.centerline_intersections}"
                left join lateral (
                    select bp.val
                    from "{schema}"."{self.cfg.tables.build_pixel}" bp
                    where st_dwithin(bp.geom, point_1, 100.0)
                    order by st_distance(bp.geom, point_1) asc limit 1
                ) b1 on true
                left join lateral (
                    select bp.val
                    from "{schema}"."{self.cfg.tables.build_pixel}" bp
                    where st_dwithin(bp.geom, point_2, 100.0)
                    order by st_distance(bp.geom, point_2) asc limit 1
                ) b2 on true;
        """
        self.execute(sql_results)

        debug('replacing centerline table with results')
        sql_replace = f"""
            drop table if exists "{schema}"."{self.cfg.tables.centerline}";
            create table "{schema}"."{self.cfg.tables.centerline}" as
                select * from "{schema}"."{self.cfg.tables.centerline_results}";
            drop table "{schema}"."{self.cfg.tables.centerline_results}";
        """
        self.execute(sql_replace)
        self.set_table_owner(schema, self.cfg.tables.centerline)

    def calculate_building_front_area(self):
        progress('calculating building front areas')
        schema = self.cfg.domain.case_schema

        sql_wall = f"""
            drop table if exists outer_wall_full;
            create temp table outer_wall_full as
            select st_forcerhr((st_dump(st_union(st_buffer(l.geom, 0.001)))).geom) as geom
            from "{schema}"."{self.cfg.tables.landcover}" as l
            where l.type between {self.cfg.type_range.building_min} and {self.cfg.type_range.building_max};
            alter table outer_wall_full add column id serial;

            drop table if exists "{schema}"."{self.cfg.tables.outer_wall}";
            create table "{schema}"."{self.cfg.tables.outer_wall}" as
            with outer_wall as (select id, st_boundary(geom) as geom from outer_wall_full)
            select
                id,
                st_linesubstring(d.geom, substart, case when subend > 1 then 1 else subend end) as geom,
                st_centroid(st_linesubstring(d.geom, substart, case when subend > 1 then 1 else subend end)) as point,
                null::numeric as building_height
            from (select id, geom, st_length(geom) len, 15 sublen from outer_wall) as d
                cross join lateral (select i, (sublen * i)/len as substart, (sublen * (i+1))/len as subend
                                     from generate_series(0, floor(d.len / sublen)::integer) as t(i)
                                     where (sublen * i)/len <> 1.0) as d2;

            -- primary: direct raster nearest value
            update "{schema}"."{self.cfg.tables.outer_wall}" ow
            set building_height = (
                select st_nearestvalue(st_transform(b.rast, {self.cfg.srid}), ow.point)
                from "{schema}"."{self.cfg.tables.buildings_height}" b
                where st_intersects(st_transform(b.rast, {self.cfg.srid}), ow.point)
                limit 1
            );

            -- fallback: nearest build_pixel within 100 m
            update "{schema}"."{self.cfg.tables.outer_wall}" ow
            set building_height = (
                select bp.val from "{schema}"."{self.cfg.tables.build_pixel}" bp
                where st_dwithin(bp.geom, ow.point, 100.0)
                order by st_distance(bp.geom, ow.point) asc limit 1
            )
            where building_height is null;

            -- default where raster coverage is missing
            update "{schema}"."{self.cfg.tables.outer_wall}"
            set building_height = {self.cfg.default_building_height}
            where building_height is null;
        """
        self.execute(sql_wall)
        self.set_table_owner(schema, self.cfg.tables.outer_wall)

        debug('aggregating wall and roof areas per building polygon')
        sql_area = f"""
            drop table if exists "{schema}"."{self.cfg.tables.building_area}";
            create table "{schema}"."{self.cfg.tables.building_area}" as
            select
                id,
                sum(building_height * st_length(geom)) as wall_area,
                null::numeric                           as roof_area,
                null::geometry                          as geom
            from "{schema}"."{self.cfg.tables.outer_wall}"
            group by id;
            alter table "{schema}"."{self.cfg.tables.building_area}" add primary key (id);

            update "{schema}"."{self.cfg.tables.building_area}" ba
            set (roof_area, geom) = (
                select st_area(geom), geom
                from outer_wall_full owf
                where ba.id = owf.id
            );
        """
        self.execute(sql_area)
        self.set_table_owner(schema, self.cfg.tables.building_area)

    def cleanup(self):
        if self.cfg.clean_up:
            debug('cleaning up temporary spatial structures')
            schema = self.cfg.domain.case_schema
            for table in [self.cfg.tables.centerline_hairy, self.cfg.tables.build_pixel]:
                self.execute(f'drop table if exists "{schema}"."{table}" cascade')