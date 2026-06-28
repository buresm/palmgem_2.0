"""
A task for processing UrbanAtlas files
"""
import os
from .base import BaseTask
from src.logger import debug, progress, verbose, warning, error, sql_debug, sql_verbose
from src.utils.linux_cmds import ShapefileImporter
from src.utils.spatial import compute_envelope


class UrbanAtlasOSM(BaseTask):
    """
    Handles the initial setup: creating PostGIS extensions,
    verifying directories, and importing vector data.
    """

    def run(self):
        self.create_envelope()
        self.transform_urban_atlas()
        # OSM streetmap merge is opt-in: it needs an imported streetmaps table
        # (tables.streetmaps_or) and is enabled via process_streetmaps in config.
        if getattr(self.cfg, 'process_streetmaps', False):
            self.transform_streetmaps()
            self.merge_urban_atlas_streetmaps()

    def create_envelope(self):
        compute_envelope(
            self.cfg, self.db,
            schema=self.cfg.domain.case_schema,
            table=self.cfg.tables.im_landcover_or,
            srid=self.cfg.srid,
        )

    def create_fishnet(self):
        """
        create fishnet: regular grid in defined extent with
        defined number of cells (nx, ny) or cell sizes (dx, dy).
        """
        progress('creating fishnet')

        # access variables using dot-notation from self.cfg
        dx = self.cfg.fishnet.dx
        dy = self.cfg.fishnet.dy
        xl = self.cfg.domain.xl
        xh = self.cfg.domain.xh
        yl = self.cfg.domain.yl
        yh = self.cfg.domain.yh

        # calculate number of cells and adjust bounds
        import numpy as np
        nx = int(np.ceil((xh - xl) / dx))
        ny = int(np.ceil((yh - yl) / dy))

        xh_new = xl + nx * dx
        yh_new = yl + ny * dy

        # calculate center coordinates
        xs = (xl + xh_new) / 2.0
        ys = (yl + yh_new) / 2.0

        debug('creating fishnet using palm_create_grid psql function')

        # using lower case for the psql call
        # note: identifiers like schema and table remain in f-string for structure
        sqltext = "select palm_create_grid(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"

        params = (
            self.cfg.domain.case_schema,
            self.cfg.tables.fishnet,
            nx,
            ny,
            dx,
            dy,
            xs,
            ys,
            self.cfg.srid,
            self.cfg.srid_wgs84,
            self.cfg.srid_utm,
            self.cfg.pg_owner,
            self.cfg.logs.level
        )

        # self.execute handles cursor management, sql_debug, and autocommit
        self.execute(sqltext, params)

        debug('fishnet created')

    def fill_landcover_background(self):
        """
        creates a background polygon (e.g., for sea or empty areas) by
        calculating the difference between the domain envelope and existing landcover.
        """
        debug('processing background to landcover')

        # check for the fill_boundary flag in cfg
        if self.cfg.domain.fill_boundary:

            # 1. obtain union of existing landcover
            verbose('obtaining union of landcover')
            sql_union = f'select st_union(geom) as geom from "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover}"'
            res_union = self.execute(sql_union)
            union = res_union[0][0] if res_union else None

            if not union:
                warning('no landcover geometries found to create background union')
                return

            # 2. create rectangular envelope of the union
            verbose('creating rectangular envelope of union')
            sql_env = 'select st_envelope(%s::geometry)'
            res_env = self.execute(sql_env, (union,))
            envelope_background = res_env[0][0] if res_env else None

            # 3. create background as difference of envelope and landcover
            verbose('creating background as difference of envelope and landcover')
            sql_diff = 'select st_difference(%s::geometry, %s::geometry)'
            res_diff = self.execute(sql_diff, (envelope_background, union))
            background = res_diff[0][0] if res_diff else None

            # 4. insert background into landcover
            if background:
                verbose('inserting background into landcover')
                sql_ins = f'insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover}" (geom) values (%s::geometry)'
                self.execute(sql_ins, (background,))
            else:
                verbose('background geometry is empty, skipping insert')
        else:
            debug('fill_boundary is disabled in config, skipping background creation')

    def transform_urban_atlas(self):
        """ Do a transformation of original shapefile. Intersects with a fishnet for faster spatial join. """
        # refactored landcover clipping logic

        debug('creating fishnet')
        # assuming create_fishnet is now a method of your task or has been updated to use self.cfg
        self.create_fishnet()

        progress('clipping landcover by fishnet')
        debug('creating new clipped landcover table')

        # sql logic using lower case and f-strings for table/schema identifiers
        sql_clip = f"""
            drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover}" cascade;

            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover}" as  
            with f as (select geom as geom from "{self.cfg.domain.case_schema}"."{self.cfg.tables.fishnet}"), 
                 l as (select code_2018, st_transform((st_dump(geom)).geom, %s) as geom 
                        from "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover_or}" 
                        where st_intersects(st_transform(geom, %s), %s::geometry)
                        ) 
            select code_2018, (st_dump(st_intersection(l.geom, f.geom))).geom as geom 
            from l, f 
            where st_intersects(l.geom, f.geom) and st_area(l.geom) > {self.cfg.max_fishnet_split_area} 
            union all 
            select code_2018, l.geom 
            from l, f 
            where st_intersects(l.geom, f.geom) and st_area(l.geom) <= {self.cfg.max_fishnet_split_area};
        """

        # execute using parameterized values for srid and envelope
        self.execute(sql_clip, (self.cfg.srid, self.cfg.srid, self.cfg.envelope))

        # handle cleanup using .get() for safety
        if self.cfg.clean_up:
            debug('drop original landcover table')
            sql_drop = f'drop table "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover_or}" cascade;'
            self.execute(sql_drop)

        # use the helper function for ownership
        self.set_table_owner(self.cfg.domain.case_schema, self.cfg.tables.im_landcover)

        verbose('adding geometry index to landcover table')
        # create gist spatial index using lower case
        sql_idx = f"""
            create index if not exists {self.cfg.tables.im_landcover}_geom_idx 
            on "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover}" 
            using gist(geom);
        """
        self.execute(sql_idx)

        # Fill boundary
        self.fill_landcover_background()

    def transform_streetmaps(self):
        """ Process streetmaps from OSM. """
        progress('processing streetmaps layer')

        # 1. create from import: transform, clip, and filter by area
        debug('creating, clipping and transforming originally streetmap imported table')
        sql_create = f"""
            drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.streetmaps}";

            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.streetmaps}" as 
            select 
                osm_id, 
                st_transform((st_dump(geom)).geom, %s) as geom 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.streetmaps_or}" 
            where 
                (st_area(st_transform(geom, %s)) > %s) and
                st_intersects(st_transform(geom, %s), %s::geometry)
        """
        self.execute(sql_create, (self.cfg.srid, self.cfg.srid, self.cfg.max_stl_area, self.cfg.srid, self.cfg.envelope))

        # 2. change ownership and index
        self.set_table_owner(self.cfg.domain.case_schema, self.cfg.tables.streetmaps)

        verbose('adding geometry index on streetmap table')
        sql_idx = f"""
            create index if not exists {self.cfg.tables.streetmaps}_geom_idx 
            on "{self.cfg.domain.case_schema}"."{self.cfg.tables.streetmaps}" 
            using gist(geom)
        """
        self.execute(sql_idx)

        # 3. add columns for processing
        verbose('add code_2018 attribute into streetmaps table')
        sql_cols = f"""
            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.streetmaps}" 
            add column if not exists code_2018 integer,
            add column if not exists cent geometry("point", %s)
        """
        self.execute(sql_cols, (self.cfg.srid,))

        # 4. calculate centroids to optimize spatial join
        verbose('calculating centroids for spatial join optimization')
        sql_cent = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.streetmaps}" 
            set cent = st_centroid(geom)
        """
        self.execute(sql_cent)

        # 5. join landcover data based on centroid location
        verbose('joining code_2018 from landcover into streetmaps')
        sql_join = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.streetmaps}" as s 
            set code_2018 = (
                select cast(code_2018 as integer) 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover}" as l 
                where st_intersects(l.geom, s.cent) 
                limit 1
            )
        """
        self.execute(sql_join)

        # 6. cleanup original import if enabled
        if self.cfg.clean_up:
            debug('deleting original import streetmap table')
            sql_cleanup = f'drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.streetmaps_or}" cascade'
            self.execute(sql_cleanup)

    def merge_urban_atlas_streetmaps(self):
        """ Create final landcover from urban atlas and open streetmaps. """
        progress('finalizing landcover table')
        joined_streetmaps = 'joined_streetmaps'

        # 1. prepare streetmap union
        debug('preparing streetmap union')
        # Subdivide the unioned streetmaps into small indexed pieces. Differencing
        # against one giant geometry is the classic PostGIS bottleneck; many small
        # pieces let the gist index restrict each difference to nearby geometry.
        sql_union = f"""
            drop table if exists "{self.cfg.domain.case_schema}"."{joined_streetmaps}";
            create table "{self.cfg.domain.case_schema}"."{joined_streetmaps}" as
            select st_subdivide(st_union(geom), 128) as geom from "{self.cfg.domain.case_schema}"."{self.cfg.tables.streetmaps}"
        """
        self.execute(sql_union)

        # 2. update ownership and index
        self.set_table_owner(self.cfg.domain.case_schema, joined_streetmaps)

        debug('adding geom index')
        sql_idx = f"""
            create index if not exists {joined_streetmaps}_geom_idx 
            on "{self.cfg.domain.case_schema}"."{joined_streetmaps}" 
            using gist(geom)
        """
        self.execute(sql_idx)

        # 3. subtract streetmaps from landcover. For each landcover polygon we
        # subtract only the subdivided streetmap pieces that actually intersect it
        # (gist-accelerated); equivalent to differencing the full union but far
        # cheaper. `where exists` skips polygons no streetmap touches.
        progress('creating difference between landcover and unioned streetmaps')
        sql_diff = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover}" as l set
            geom = st_difference(l.geom, (
                select st_union(s.geom)
                from "{self.cfg.domain.case_schema}"."{joined_streetmaps}" s
                where st_intersects(l.geom, s.geom)
            ))
            where exists (
                select 1 from "{self.cfg.domain.case_schema}"."{joined_streetmaps}" s
                where st_intersects(l.geom, s.geom)
            )
        """
        self.execute(sql_diff)

        # 4. restructure landcover columns
        verbose('restructuring landcover table columns')
        sql_alter = f"""
            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover}" 
            rename column code_2018 to code_2018_char;

            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover}" 
            add column if not exists osm_id integer, 
            add column if not exists type integer, 
            add column if not exists code_2018 integer;
        """
        self.execute(sql_alter)

        # 5. cast char codes to integer
        verbose('update code_2018 from char into integer')
        sql_cast = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover}" set 
            code_2018 = cast(code_2018_char as integer)
        """
        self.execute(sql_cast)

        # 6. insert streetmaps into landcover
        debug('inserting streetmaps into landcover')
        sql_ins = f"""
            insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover}" 
            (type, osm_id, code_2018, geom) 
            select null, cast(osm_id as integer), code_2018, geom 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.streetmaps}"
        """
        self.execute(sql_ins)

        # 7. handle primary key and cleanup
        debug('finalizing table keys')
        sql_pk = f"""
            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover}" 
            add column if not exists lid serial primary key
        """
        self.execute(sql_pk)

        if self.cfg.clean_up:
            debug('cleaning up temporary and original tables')
            sql_cleanup = f"""
                drop table if exists "{self.cfg.domain.case_schema}"."{joined_streetmaps}" cascade;
                drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover_or}" cascade;
            """
            self.execute(sql_cleanup)

        # 8. join palm types based on mapping table
        progress('joining user defined class and landcover classes into palm types')
        debug('updating palm type mapping')

        # build the case statement dynamically from the configuration mapping
        case_parts = []
        for m in self.cfg.mt:
            # m[0]: code_2018, m[1]: landcover_palm_type, m[2]: streetmap_palm_type
            case_parts.append(f"when code_2018 = {m[0]} then case when osm_id is null then {m[1]} else {m[2]} end")

        sql_palm = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.im_landcover}" set 
            type = case 
                {" ".join(case_parts)} 
                else {self.cfg.mt_default} 
            end
        """
        self.execute(sql_palm)