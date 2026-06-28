#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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

import numpy as np
from netCDF4 import Dataset
import pandas as pd
import matplotlib.pyplot  as plt
import os
import sys
from datetime import datetime
from pathlib import Path
from pyproj import CRS, Transformer
from scipy.linalg import lstsq, norm
from src.logger import progress, debug, verbose, warning, error, sql_debug, extra_verbose
from .base import BaseTask


class CctProcessing(BaseTask):
    """
    Handles all CCT (cut cell topography) processing for PALM-GeM.
    Orchestrates creation of slanted surfaces, walls, terrain, and roof structures.
    """

    def run(self):
        """Main orchestration method for CCT processing."""
        if not self.cfg.do_cct:
            return

        # allow staged execution: derive has_buildings etc. from the schema if
        # initialize_domain did not run in this process.
        from src.utils.capabilities import ensure_capability_flags
        ensure_capability_flags(self.cfg, self.db)

        progress('Run CCT Module')
        self.slanted_surface_init()

    def preprocess_terrain_height(self):
        """ correct terrain height """
        progress('Starting preprocessing of terrain height')

        schema = self.cfg.domain.case_schema
        t_corrected = self.cfg.tables.height_terr_corrected
        t_grid = self.cfg.tables.grid
        t_landcover = self.cfg.tables.landcover

        # --- 1. Create Initial Base Grid Table ---
        sqltext = f"""
            drop table if exists "{schema}"."{t_corrected}" cascade;
            create table "{schema}"."{t_corrected}" as 
            select 
                xmi, ymi, i, j, lid, 
                cast(null as double precision) as height, 
                cast(null as double precision) as height_dummy, 
                false as iswall, false as inside, 
                st_setsrid(st_makepoint(xmi, ymi), %s) as geom 
            from "{schema}"."{t_grid}"
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        # --- 2. Expand Boundaries / Guard Rings ---
        sqltext = f"""
            insert into "{schema}"."{t_corrected}" 
            select 
                xmi, yma, i, {self.cfg.domain.ny - 1} + 1, lid, 
                null, null, false, false, st_setsrid(st_makepoint(xmi, yma), %s) 
            from "{schema}"."{t_grid}" 
            where j = {self.cfg.domain.ny - 1}
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        sqltext = f"""
            insert into "{schema}"."{t_corrected}" 
            select 
                xma, ymi, i + 1, j, lid, 
                null, null, false, false, st_setsrid(st_makepoint(xma, ymi), %s) 
            from "{schema}"."{t_grid}" 
            where i = {self.cfg.domain.nx - 1}
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        sqltext = f"""
            insert into "{schema}"."{t_corrected}" 
            select 
                xma, yma, i + 1, j + 1, lid, 
                null, null, false, false, st_setsrid(st_makepoint(xma, yma), %s) 
            from "{schema}"."{t_grid}" 
            where i = {self.cfg.domain.nx - 1} and j = {self.cfg.domain.ny - 1}
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        # --- 3. Fill Missing Border Pixels via Anti-Joins ---
        sqltext = f"""
            insert into "{schema}"."{t_corrected}" 
            select 
                xmi, yma, i, j + 1, lid, 
                null, null, false, false, st_setsrid(st_makepoint(xmi, yma), %s) 
            from "{schema}"."{t_grid}" as g 
            where not exists (
                select 1 from "{schema}"."{t_corrected}" as tc 
                where tc.i = g.i and tc.j = g.j + 1
            )
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        sqltext = f"""
            insert into "{schema}"."{t_corrected}" 
            select 
                xma, ymi, i + 1, j, lid, 
                null, null, false, false, st_setsrid(st_makepoint(xma, ymi), %s) 
            from "{schema}"."{t_grid}" as g 
            where not exists (
                select 1 from "{schema}"."{t_corrected}" as tc 
                where tc.i = g.i + 1 and tc.j = g.j
            )
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        sqltext = f"""
            insert into "{schema}"."{t_corrected}" 
            select 
                xma, yma, i + 1, j + 1, lid, 
                null, null, false, false, st_setsrid(st_makepoint(xma, yma), %s) 
            from "{schema}"."{t_grid}" as g 
            where not exists (
                select 1 from "{schema}"."{t_corrected}" as tc 
                where tc.i = g.i + 1 and tc.j = g.j + 1
            )
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        # --- 4. Calculate Height (Moving Window Average) ---
        sqltext = f"""
            update "{schema}"."{t_corrected}" as h 
            set height = (
                select avg(height) - {self.cfg.domain.origin_z} 
                from "{schema}"."{t_grid}" as g 
                where g.i between h.i - 1 and h.i + 1 
                  and g.j between h.j - 1 and h.j + 1
            )
        """
        self.execute(sqltext)

        # --- 5. Conditional Building Adjustments ---
        if self.cfg.has_buildings:
            verbose('updating lids in case of buildings polygons')
            sqltext = f"""
                update "{schema}"."{t_corrected}" as h 
                set lid = lb.lid 
                from "{schema}"."{t_landcover}" as lb  
                where st_intersects(h.geom, lb.geom) 
                  and lb.type between 900 and 999
            """
            self.execute(sqltext)

            sqltext = f"""
                update "{schema}"."{t_corrected}" as h 
                set inside = true 
                from "{schema}"."{t_landcover}" as lb  
                where st_intersects(h.geom, lb.geom) 
                  and lb.type between 900 and 999
            """
            self.execute(sqltext)

            sqltext = f"""
                with bo as (
                    select * from "{schema}"."{self.cfg.tables.buildings_offset}"
                ) 
                update "{schema}"."{t_corrected}" as h 
                set height = bo.max 
                from bo, "{schema}"."{t_landcover}" as lb 
                where st_intersects(h.geom, lb.geom) 
                  and bo.lid = h.lid 
                  and lb.type between 900 and 999
            """
            self.execute(sqltext)

        verbose('start with checking height')
        sqltext = f"""
            update "{schema}"."{t_corrected}" as h 
            set height_dummy = height
        """
        self.execute(sqltext)

        # --- 6. Set Final Structural Indexes ---
        verbose('Putting indexes')
        self.execute(f'create index terr_height_corrected_j_i_idx on "{schema}"."{t_corrected}" (i asc, j asc)')
        self.execute(f'create index terr_height_corrected_geom_idx on "{schema}"."{t_corrected}" using gist(geom)')
        self.execute(f'create index terr_height_corrected_ji_idx on "{schema}"."{t_corrected}" (j, i)')

        # --- 7. Scan and Filter Step-Like Discontinuities ---
        sqltext = f"""
            with hc_diag  as (select i, j, height from "{schema}"."{t_corrected}"), 
                 hc_top   as (select i, j, height from "{schema}"."{t_corrected}"), 
                 hc_right as (select i, j, height from "{schema}"."{t_corrected}") 

            select 
                h.i, h.j, h.height as h_height, 
                hc_diag.height as h_diag, 
                hc_top.height as h_top, 
                hc_right.height as h_right,
                (h.height < hc_top.height and h.height < hc_right.height and hc_diag.height < hc_top.height and hc_diag.height < hc_right.height) as sml,
                (h.height > hc_top.height and h.height > hc_right.height and hc_diag.height > hc_top.height and hc_diag.height > hc_right.height) as hgh 
            from "{schema}"."{t_corrected}" h 
            left join hc_diag  on hc_diag.i  = h.i + 1 and hc_diag.j  = h.j + 1 and hc_diag.height is not null and not iswall 
            left join hc_top   on hc_top.i   = h.i     and hc_top.j   = h.j + 1 and hc_top.height is not null and not iswall 
            left join hc_right on hc_right.i = h.i + 1 and hc_right.j = h.j     and hc_right.height is not null and not iswall 
            where 
                (h.height < hc_top.height and h.height < hc_right.height and hc_diag.height < hc_top.height and hc_diag.height < hc_right.height) or 
                (h.height > hc_top.height and h.height > hc_right.height and hc_diag.height > hc_top.height and hc_diag.height > hc_right.height) 
            order by h.i, h.j
        """
        ij2corr = self.execute(sqltext)

        # --- 8. Loop and Execute Fine Height Adjustments ---
        verbose(f'There is {len(ij2corr)} to correct')
        sqlcorr = f"""
            update "{schema}"."{t_corrected}" 
            set height = %s 
            where (i = %s and j = %s) or (i = %s and j = %s)
        """

        for i, j, hh, hdiag, htop, hright, sml, hgh in ij2corr:
            verbose('Height correction for [i,j]:[{},{}]', i, j)
            verbose('\th:{}, hdiag:{}, htop:{}, hright:{}, sml: {}, hgh: {}', hh, hdiag, htop, hright, sml, hgh)

            if sml:
                self.execute(sqlcorr, (min(htop, hright), i, j, i + 1, j + 1))
            else:
                self.execute(sqlcorr, (min(hh, hdiag), i + 1, j, i, j + 1))

    def calculate_aspect_slope(self):
        """ Create slope and aspect on building roofs"""
        progress('Creating Aspect from buildings')
        sqltext = f"""
            drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.aspect}";
            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.aspect}" as 
            select st_aspect(rast) 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_height}"
        """
        self.execute(sqltext)

        progress('Creating Slope from buildings')
        sqltext = f"""
            drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.slope}";
            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slope}" as 
            select st_slope(rast) 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_height}"
        """
        self.execute(sqltext)

    def preprocess_building_height(self):
        """ correct building heights """
        progress('Starting preprocessing building height')

        # create grid with, i,j from grid
        sqltext = f"""
            drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" cascade; 
            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" as 
            select 
                xmi, ymi, i, j, 
                cast(null as double precision) as height, 
                cast(null as double precision) as height_bottom, 
                false as dummy_point, 
                st_setsrid(st_makepoint(xmi, ymi), %s) as geom 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}"
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        sqltext = f"""
            insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" 
            select xmi, yma, i, {self.cfg.domain.ny - 1} + 1, null, null, false, st_setsrid(st_makepoint(xmi, yma), %s) 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" 
            where j = {self.cfg.domain.ny - 1}
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        sqltext = f"""
            insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" 
            select xma, ymi, i + 1, j, null, null, false, st_setsrid(st_makepoint(xma, ymi), %s) 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" 
            where i = {self.cfg.domain.nx - 1}
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        sqltext = f"""
            insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" 
            select xma, yma, i + 1, j + 1, null, null, false, st_setsrid(st_makepoint(xma, yma), %s) 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" 
            where i = {self.cfg.domain.nx - 1} and j = {self.cfg.domain.ny - 1}
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        sqltext = f"""
            insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" 
            select xmi, yma, i, j + 1, null, null, false, st_setsrid(st_makepoint(xmi, yma), %s) 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" as g 
            where not exists (
                select 1 from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" as tc 
                where tc.i = g.i and tc.j = g.j + 1
            )
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        sqltext = f"""
            insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" 
            select xma, ymi, i + 1, j, null, null, false, st_setsrid(st_makepoint(xma, ymi), %s) 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" as g 
            where not exists (
                select 1 from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" as tc 
                where tc.i = g.i + 1 and tc.j = g.j
            )
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        sqltext = f"""
            insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" 
            select xma, yma, i + 1, j + 1, null, null, false, st_setsrid(st_makepoint(xma, yma), %s) 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" as g 
            where not exists (
                select 1 from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" as tc 
                where tc.i = g.i + 1 and tc.j = g.j + 1
            )
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        # fill with height
        debug('Filling table {} with heights', self.cfg.tables.height_corrected)
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" as bh 
            set height = (
                    select max(height) 
                    from "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_grid}" as g 
                    where g.i between bh.i - 1 and bh.i + 1 
                      and g.j between bh.j - 1 and bh.j + 1
                ) + th.height_dummy,
                height_bottom = th.height_dummy 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" as th, 
                 "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" as lb 
            where th.i = bh.i 
              and th.j = bh.j 
              and st_intersects(bh.geom, lb.geom)
              and lb.type between 900 and 999
        """
        self.execute(sqltext)

        # put an indexes on the table
        debug('Creating geom indexes on table {}', self.cfg.tables.height_corrected)
        sqltext = f"""
            create index height_corrected_geom_idx on "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" using gist(geom)
        """
        self.execute(sqltext)

        sqltext = f"""
            create index height_corrected_ji_idx on "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" (j, i)
        """
        self.execute(sqltext)

        debug('Update building height dummy point, so filtering algorithm would work near edges')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" bh
            set dummy_point = true
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.walls_outer}" wo
            where bh.height is null
                and st_dwithin(wo.geom, bh.geom, {self.cfg.domain.dx});
        """
        self.execute(sqltext)

        # Now perform filtering
        self.filter_building_heights()


    def filter_building_heights(self):
        """ Special filter to find specific cases"""
        debug('Apply specific building height filter')
        # now filter special cases
        sqltext = f"""
            with hc_diag  as (select i, j, height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}"), 
                 hc_top   as (select i, j, height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}"), 
                 hc_right as (select i, j, height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}") 
    
            select h.i, h.j, h.height as h_height, hc_diag.height as h_diag, hc_top.height as h_top, hc_right.height as h_right,
                   (h.height < hc_top.height and h.height < hc_right.height and hc_diag.height < hc_top.height and hc_diag.height < hc_right.height) as sml,
                   (h.height > hc_top.height and h.height > hc_right.height and hc_diag.height > hc_top.height and hc_diag.height > hc_right.height) as hgh 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" h 
            left join hc_diag  on hc_diag.i  = h.i + 1 and hc_diag.j  = h.j + 1 and hc_diag.height is not null 
            left join hc_top   on hc_top.i   = h.i     and hc_top.j   = h.j + 1 and hc_top.height is not null 
            left join hc_right on hc_right.i = h.i + 1 and hc_right.j = h.j     and hc_right.height is not null 
            where
                 (h.height < hc_top.height and h.height < hc_right.height and hc_diag.height < hc_top.height and hc_diag.height < hc_right.height) or 
                 (h.height > hc_top.height and h.height > hc_right.height and hc_diag.height > hc_top.height and hc_diag.height > hc_right.height) 
            order by h.i, h.j
        """
        ij2corr = self.execute(sqltext)

        sqlcorr = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" set 
            height = %s 
            where ((i = %s and j = %s) or (i = %s and j = %s)) and not dummy_point
        """
        for i, j, hh, hdiag, htop, hright, sml, hgh in ij2corr:
            verbose('Height correction for [i,j]:[{},{}]', i, j)
            verbose('\th:{}, hdiag:{}, htop:{}, hright:{}, sml: {}, hgh: {}', hh, hdiag, htop, hright, sml, hgh)
            if sml:
                # h and hdiag are both lower, correct height in both of them to min(htop,hright)
                self.execute(sqlcorr, (min(htop, hright), i, j, i + 1, j + 1))
            else:
                # top, right are lower, correct height in both of them to min(hh, hdiag)
                self.execute(sqlcorr, (min(hh, hdiag), i + 1, j, i, j + 1))

        def create_slanted_walls_terrain(self):
            """ So far dummy function, just idea """
            # SELECT intersecting point from wall
            progress('Processing connection between wall and adjacent terrain')
            sqltext = f"""
                drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}"; 
                create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}" as 
                select row_number() over () as id, point, false as j_line, false as i_line, 
                       cast(null as double precision) as height, 
                       cast(null as integer) as i,
                       cast(null as integer) as j 
                from (
                    select point1 as point from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" 
                    union all 
                    select point2 as point from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}"
                ) as s 
                group by point
            """
            self.execute(sqltext)

            debug('Finding if point is at i-line or j-line')
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}" set 
                j_line = case when abs((st_x(point) - {self.cfg.domain.origin_x}) / {self.cfg.domain.dx} - round((st_x(point) - {self.cfg.domain.origin_x}) / {self.cfg.domain.dx})) < 1e-10 then true else false end, 
                i_line = case when abs((st_y(point) - {self.cfg.domain.origin_y}) / {self.cfg.domain.dy} - round((st_y(point) - {self.cfg.domain.origin_y}) / {self.cfg.domain.dy})) < 1e-10 then true else false end
            """
            self.execute(sqltext)

            debug('Calculating of i,j')
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}" set 
                i = floor((st_x(point) - {self.cfg.domain.origin_x}) / {self.cfg.domain.dx}), 
                j = floor((st_y(point) - {self.cfg.domain.origin_y}) / {self.cfg.domain.dy})
            """
            self.execute(sqltext)

            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}" tw set 
                height = 
                case when i_line then (floor((select max(height) from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" as th 
                                             where (th.i = tw.i or th.i = tw.i + 1) and th.j = tw.j) / {self.cfg.domain.dz}) + 1) * {self.cfg.domain.dz} 
                     else             (floor((select max(height) from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" as th 
                                             where (th.j = tw.j or th.j = tw.j + 1) and th.i = tw.i) / {self.cfg.domain.dz}) + 1) * {self.cfg.domain.dz} 
                     end
            """
            self.execute(sqltext)

            # add those point into terrain correction
            sqltext = f"""
                insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" 
                select 
                    st_x(point), st_y(point), i, j, null, height, height, true, false, point 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}"
            """
            self.execute(sqltext)

            # Do some filtering in height_terr_corrected table
            debug('Small filtering inside {} table', self.cfg.tables.height_terr_corrected)
            sqltext_1 = f"""
                with tr as (select i, j, height, iswall from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" where not iswall) 
                select tc.i, tc.j, tr.height 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" as tc, tr 
                where ((tc.i + 1 = tr.i and tc.j     = tr.j)     or  
                       (tc.i     = tr.i and tc.j + 1 = tr.j)     or 
                       (tc.i     = tr.i and tc.j     = tr.j)   ) and 
                       tc.height < tr.height and tc.iswall 
                order by tc.i, tc.j
            """

            sqltext_2 = f"""
                with hc_diag  as (select i, j, height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" where not iswall), 
                     hc_top   as (select i, j, height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" where not iswall), 
                     hc_right as (select i, j, height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" where not iswall) 
    
                select h.i, h.j, h.height as h_height, hc_diag.height as h_diag, hc_top.height as h_top, hc_right.height as h_right,
                       (h.height < hc_top.height and h.height < hc_right.height and hc_diag.height < hc_top.height and hc_diag.height < hc_right.height) as sml,
                       (h.height > hc_top.height and h.height > hc_right.height and hc_diag.height > hc_top.height and hc_diag.height > hc_right.height) as hgh 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" h 
                left join hc_diag  on hc_diag.i  = h.i + 1 and hc_diag.j  = h.j + 1 and hc_diag.height is not null and not iswall 
                left join hc_top   on hc_top.i   = h.i     and hc_top.j   = h.j + 1 and hc_top.height is not null and not iswall 
                left join hc_right on hc_right.i = h.i + 1 and hc_right.j = h.j     and hc_right.height is not null and not iswall 
                where
                     (h.height < hc_top.height and h.height < hc_right.height and hc_diag.height < hc_top.height and hc_diag.height < hc_right.height) or 
                     ((h.height > hc_top.height and h.height > hc_right.height and hc_diag.height > hc_top.height and hc_diag.height > hc_right.height) and not h.iswall) 
                order by h.i, h.j
            """

            sqlcorr_1 = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" set 
                height = %s 
                where i = %s and j = %s and iswall
            """

            sqlcorr_2 = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" set 
                height = %s 
                where ((i = %s and j = %s) or (i = %s and j = %s)) and not iswall
            """

            sqltext_inside_update = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" as tc set 
                height = (select max(height) - 0.1 from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" as tr 
                          where not inside and st_dwithin(tc.geom, tr.geom, {self.cfg.slanted_pars.dist2edge_filter}) limit 1) 
                where inside
            """

            ij2corr = [1]
            while len(ij2corr) > 0:
                self.execute(sqltext_inside_update)
                ij2corr = self.execute(sqltext_1)

                debug('Updating places')
                for i, j, height in ij2corr:
                    height = (np.floor(height / self.cfg.domain.dz) + 1) * self.cfg.domain.dz
                    verbose('Height correction for [i,j]:[{},{}], height = {} ', i, j, height)
                    self.execute(sqlcorr_1, (height, i, j))

                # now filter special cases
                ij2corr = self.execute(sqltext_2)

                for i, j, hh, hdiag, htop, hright, sml, hgh in ij2corr:
                    verbose('Height correction for [i,j]:[{},{}]', i, j)
                    verbose('\th:{}, hdiag:{}, htop:{}, hright:{}, sml: {}, hgh: {}', hh, hdiag, htop, hright, sml, hgh)
                    if sml:
                        # h and hdiag are both lower, correct height in both of them to min(htop,hright)
                        self.execute(sqlcorr_2, (min(htop, hright), i, j, i + 1, j + 1))
                    else:
                        # top, right are lower, correct height in both of them to min(hh, hdiag)
                        self.execute(sqlcorr_2, (min(hh, hdiag), i + 1, j, i, j + 1))

            # -- OPTIMIZE HERE
            debug('Correcting the ones near the wall (just in case)')
            dist2edge = self.cfg.slanted_pars.dist2edge
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" as hc set height = 
                (select height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" as wo 
                 where iswall and st_dwithin(wo.geom, hc.geom, 2.0 * {dist2edge}) 
                 order by st_distance(wo.geom, hc.geom) 
                 limit 1) 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.walls_outer}" as wo 
                where not iswall and st_distance(hc.geom, wo.geom) < {dist2edge}
            """
            self.execute(sqltext)

            # now filter special cases
            sqltext = f"""
                with hc_diag  as (select i, j, height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" where not iswall), 
                     hc_top   as (select i, j, height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" where not iswall), 
                     hc_right as (select i, j, height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" where not iswall) 
    
                select h.i, h.j, h.height as h_height, hc_diag.height as h_diag, hc_top.height as h_top, hc_right.height as h_right,
                       (h.height < hc_top.height and h.height < hc_right.height and hc_diag.height < hc_top.height and hc_diag.height < hc_right.height) as sml,
                       (h.height > hc_top.height and h.height > hc_right.height and hc_diag.height > hc_top.height and hc_diag.height > hc_right.height) as hgh 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" h 
                left join hc_diag  on hc_diag.i  = h.i + 1 and hc_diag.j  = h.j + 1 and hc_diag.height is not null and not iswall 
                left join hc_top   on hc_top.i   = h.i     and hc_top.j   = h.j + 1 and hc_top.height is not null and not iswall 
                left join hc_right on hc_right.i = h.i + 1 and hc_right.j = h.j     and hc_right.height is not null and not iswall 
                where
                     (h.height < hc_top.height and h.height < hc_right.height and hc_diag.height < hc_top.height and hc_diag.height < hc_right.height) or 
                     (h.height > hc_top.height and h.height > hc_right.height and hc_diag.height > hc_top.height and hc_diag.height > hc_right.height) 
                order by h.i, h.j
            """
            ij2corr = [1]
            while len(ij2corr) > 0:
                ij2corr = self.execute(sqltext)

                sqlcorr = f"""
                    update "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" set 
                    height = %s 
                    where ((i = %s and j = %s) or (i = %s and j = %s)) and not iswall
                """
                for i, j, hh, hdiag, htop, hright, sml, hgh in ij2corr:
                    verbose('Height correction for [i,j]:[{},{}]', i, j)
                    verbose('\th:{}, hdiag:{}, htop:{}, hright:{}, sml: {}, hgh: {}', hh, hdiag, htop, hright, sml, hgh)
                    if sml:
                        # h and hdiag are both lower, correct height in both of them to min(htop,hright)
                        self.execute(sqlcorr, (min(htop, hright), i, j, i + 1, j + 1))
                    else:
                        # top, right are lower, correct height in both of them to min(hh, hdiag)
                        self.execute(sqlcorr, (min(hh, hdiag), i + 1, j, i, j + 1))

            #### PROCESS CONNECTION BETWEEN WALL AND BUILDING WALL
            progress('Processing connection between wall and adjacent terrain')
            sqltext = f"""
                drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}"; 
                create table if not exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}" as 
                select id, i, j, point1 as w_point1, point2 as w_point2, 
                       split_terr_wall, norm 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}"
            """
            self.execute(sqltext)

            # add indexes and unique indexes
            sqltext = f"""
                create index terr_wall_id_idx on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}" (id); 
                create index terr_wall_ji_idx on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}" (i asc, j asc)
            """
            self.execute(sqltext)

            # Add extra columns to table
            debug('Adding extra column in terr_wall table')
            sqltext = f"""
                alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}" 
                add column if not exists cent   geometry("point", %s), 
                add column if not exists norm   geometry("point", %s), 
                add column if not exists point1 geometry("point", %s), 
                add column if not exists point2 geometry("point", %s), 
                add column if not exists point3 geometry("point", %s), 
                add column if not exists point4 geometry("point", %s), 
                add column if not exists point5 geometry("point", %s), 
                add column if not exists point6 geometry("point", %s), 
                add column if not exists z1 double precision, 
                add column if not exists z2 double precision, 
                add column if not exists z3 double precision, 
                add column if not exists z4 double precision, 
                add column if not exists z5 double precision, 
                add column if not exists z6 double precision, 
                add column if not exists is_wall1 boolean, 
                add column if not exists is_wall2 boolean, 
                add column if not exists is_wall3 boolean, 
                add column if not exists is_wall4 boolean, 
                add column if not exists is_wall5 boolean, 
                add column if not exists is_wall6 boolean, 
                add column if not exists n_edges integer,
                add column if not exists geom3d geometry("polygonz", %s)
            """
            self.execute(sqltext, (
                self.cfg.srid_palm, self.cfg.srid_palm, self.cfg.srid_palm, self.cfg.srid_palm,
                self.cfg.srid_palm, self.cfg.srid_palm, self.cfg.srid_palm, self.cfg.srid_palm,
                self.cfg.srid_palm
            ))

            # Assign points to polygon corners
            debug('Assigning building corners')
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}" set 
                n_edges = st_npoints(split_terr_wall) - 1, 
                point1 = case when st_npoints(split_terr_wall) > 1 then st_pointn(st_boundary(split_terr_wall), 1) else null end, 
                point2 = case when st_npoints(split_terr_wall) > 2 then st_pointn(st_boundary(split_terr_wall), 2) else null end, 
                point3 = case when st_npoints(split_terr_wall) > 3 then st_pointn(st_boundary(split_terr_wall), 3) else null end, 
                point4 = case when st_npoints(split_terr_wall) > 4 then st_pointn(st_boundary(split_terr_wall), 4) else null end, 
                point5 = case when st_npoints(split_terr_wall) > 5 then st_pointn(st_boundary(split_terr_wall), 5) else null end
            """
            self.execute(sqltext)

            # decide which are wall points
            debug('Assigning which point is wall point')
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}" set 
                is_wall1 = w_point1 = point1 or w_point2 = point1, 
                is_wall2 = w_point1 = point2 or w_point2 = point2, 
                is_wall3 = w_point1 = point3 or w_point2 = point3, 
                is_wall4 = w_point1 = point4 or w_point2 = point4, 
                is_wall5 = w_point1 = point5 or w_point2 = point5
            """
            self.execute(sqltext)

            # assign height to each point, either from terrain height or from building (combination of terrain and building)
            debug('Assigning height to terr_wall points')
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}" set 
                z1 = (select height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" where st_dwithin(point1, geom, {dist2edge}) order by st_distance(point1, geom) limit 1),  
                z2 = (select height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" where st_dwithin(point2, geom, {dist2edge}) order by st_distance(point2, geom) limit 1),  
                z3 = (select height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" where st_dwithin(point3, geom, {dist2edge}) order by st_distance(point3, geom) limit 1),  
                z4 = (select height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" where st_dwithin(point4, geom, {dist2edge}) order by st_distance(point4, geom) limit 1),  
                z5 = (select height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" where st_dwithin(point5, geom, {dist2edge}) order by st_distance(point5, geom) limit 1)
            """
            self.execute(sqltext)

            # create 3d polygons to check
            debug('Create 3d terr_height polygons')
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}" set 
                geom3d = st_setsrid(st_convexhull(st_collect(array[
                    st_makepoint(st_x(point1), st_y(point1), z1), 
                    st_makepoint(st_x(point2), st_y(point2), z2), 
                    st_makepoint(st_x(point3), st_y(point3), z3), 
                    st_makepoint(st_x(point4), st_y(point4), z4), 
                    st_makepoint(st_x(point5), st_y(point5), z5)
                ])), %s)
            """
            self.execute(sqltext, (self.cfg.srid_palm,))

    def create_slanted_terrain(self):
        """ create slanted terrain """
        progress('Creating slanted terrain')
        if self.cfg.has_buildings:
            self.create_slanted_walls_terrain()

        debug('Creating table {}', self.cfg.tables.slanted_terrain)
        # FIXME: get lid inside this table from slanted_terr_wall
        sqltext = f"""
            drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}";
            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" 
            (
                id integer not null, lid integer, i integer not null, j integer not null, n_edges integer, 
                p1 geometry(pointz, %s), p2 geometry(pointz, %s), p3 geometry(pointz, %s), 
                p4 geometry(pointz, %s), p5 geometry(pointz, %s)
            )
        """
        self.execute(sqltext, (
            self.cfg.srid_palm, self.cfg.srid_palm, self.cfg.srid_palm,
            self.cfg.srid_palm, self.cfg.srid_palm
        ))

        debug('Create index on i,j and id')
        sqltext = f"""
            create index slanted_terrain_ji_idx on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" (i asc, j asc);
            create index slanted_terrain_id_idx on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" (id asc);
        """
        self.execute(sqltext)

        if self.cfg.has_buildings:
            debug('Insert buildings surrounding into slanted terrain table')
            sqltext = f"""
                insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" 
                (id, lid, i, j, n_edges, p1, p2, p3, p4, p5)
                select id, cast(null as integer) as lid, i, j, cast(null as integer) as n_edges, 
                       st_setsrid(st_makepoint(st_x(point1), st_y(point1), z1), %s) as p1, 
                       st_setsrid(st_makepoint(st_x(point2), st_y(point2), z2), %s) as p2, 
                       st_setsrid(st_makepoint(st_x(point3), st_y(point3), z3), %s) as p3, 
                       st_setsrid(st_makepoint(st_x(point4), st_y(point4), z4), %s) as p4, 
                       st_setsrid(st_makepoint(st_x(point5), st_y(point5), z5), %s) as p5 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terr_wall}"
            """
            self.execute(sqltext, (
                self.cfg.srid_palm, self.cfg.srid_palm, self.cfg.srid_palm,
                self.cfg.srid_palm, self.cfg.srid_palm
            ))

        debug('Calculated number of edges in slanted terrain table')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" set 
            n_edges = case when p1 is not null then 1 else 0 end + 
                      case when p2 is not null then 1 else 0 end + 
                      case when p3 is not null then 1 else 0 end + 
                      case when p4 is not null then 1 else 0 end + 
                      case when p5 is not null then 1 else 0 end
        """
        self.execute(sqltext)

        # -- OPTIMIZE HERE
        if self.cfg.has_buildings:
            debug('Insert the rest of polygons into table {}', self.cfg.tables.slanted_terrain)
            sqltext = f"""
                insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" 
                (id, lid, i, j, n_edges) 
                select g.id, g.lid, g.i, g.j, 4 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g
                    left join "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" st on st.id = g.id
                    left join "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_grid}" bg on bg.id = g.id
                where st.id is null and bg.id is null
            """
            self.execute(sqltext)
        else:
            debug('Insert the rest of polygons into table {}', self.cfg.tables.slanted_terrain)
            sqltext = f"""
                insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" (id, lid, i, j, n_edges) 
                select id, g.lid, g.i, g.j, 4 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" as g 
                where g.id not in (select id from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}")
            """
            self.execute(sqltext)

        debug('updating p1 in slanted terrain')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" as st set 
            p1 = st_setsrid(st_makepoint(st_x(th1.geom), st_y(th1.geom), th1.height), %s)
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" as th1 
            where st.i = th1.i and st.j = th1.j 
                  and p1 is null and n_edges >= 1 and not th1.iswall
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        debug('updating p2 in slanted terrain')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" as st set 
            p2 = st_setsrid(st_makepoint(st_x(th2.geom), st_y(th2.geom), th2.height), %s)
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" as th2 
            where st.i + 1 = th2.i and st.j = th2.j 
                  and p2 is null and n_edges >= 2 and not th2.iswall
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        debug('updating p3 in slanted terrain')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" as st set 
            p3 = st_setsrid(st_makepoint(st_x(th3.geom), st_y(th3.geom), th3.height), %s)
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" as th3 
            where st.i + 1 = th3.i and st.j + 1 = th3.j 
                  and p3 is null and n_edges >= 3 and not th3.iswall
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        debug('updating p4 in slanted terrain')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" as st set 
            p4 = st_setsrid(st_makepoint(st_x(th4.geom), st_y(th4.geom), th4.height), %s)
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}" as th4 
            where st.i = th4.i and st.j + 1 = th4.j 
                  and p4 is null and n_edges >= 4 and not th4.iswall
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        debug('Calculated number of edges in slanted terrain table')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" set 
            n_edges = case when p1 is not null then 1 else 0 end + 
                      case when p2 is not null then 1 else 0 end + 
                      case when p3 is not null then 1 else 0 end + 
                      case when p4 is not null then 1 else 0 end + 
                      case when p5 is not null then 1 else 0 end
        """
        self.execute(sqltext)

        debug('Building 3d polygon for slanted terrain')
        sqltext = f"""
            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" 
            add column if not exists geom3d geometry(polygonz, %s)
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" set 
            geom3d = st_setsrid(st_convexhull(st_collect(array[
                     p1, p2, p3, p4, p5])), %s)  
            where n_edges > 2
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        debug('Updating lid')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}" as st set 
            lid = (
                select l.lid from "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" as l 
                where not l.type between 900 and 999
                order by st_distance(geom3d, geom) limit 1
            )
            where lid is null
        """
        self.execute(sqltext)

    def create_slanted_walls(self):
        """ Process slanted walls """
        progress('Creating slanted walls')
        # Create intersection between line and grid
        progress('Creating intersect between wall line and grid')

        sqltext = f"""drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" """
        self.execute(sqltext)

        sqltext = f"""
            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" as 
            with outer_walls as (select (st_dump(geom)).geom as geom from "{self.cfg.domain.case_schema}"."{self.cfg.tables.walls_outer}") 
            select id, i, j, cast(null as integer) as wid, g.geom, w.geom as wall_geom, st_intersection(w.geom, st_boundary(g.geom)) as intersec 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" as g 
            join outer_walls as w on st_intersects(g.geom, w.geom)
        """
        self.execute(sqltext)

        # Update places where multiple intersection occurred
        # TODO: FIXME: UGLY HACK, NO there should be no point that needs this, hopefully
        debug('Fixing multiple intersections 1')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" set 
            intersec = case when st_distance(geom, st_startpoint(wall_geom)) > 0.20 then 
                                  st_collect(st_startpoint(st_geometryn(st_intersection(geom, wall_geom),1)), 
                                             st_endpoint(st_geometryn(st_intersection(geom, wall_geom),2)) 
                                             ) 
                     else st_collect(st_startpoint(st_geometryn(st_intersection(geom, wall_geom),2)), 
                                     st_endpoint(st_geometryn(st_intersection(geom, wall_geom),1))
                                     ) 
                     end 
            where st_numgeometries(st_intersection(geom, wall_geom)) = 2 and st_npoints(intersec) > 2
        """
        self.execute(sqltext)

        # TODO: FIXME: UGLY HACK
        debug('Fixing multiple intersections 2')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" set 
            intersec = st_collect(st_startpoint(st_geometryn(st_intersection(geom, wall_geom),2)), 
                                  st_endpoint(st_geometryn(st_intersection(geom, wall_geom),1)) 
                                  ) 
            where st_numgeometries(st_intersection(geom, wall_geom)) = 3 and st_npoints(intersec) > 2
        """
        self.execute(sqltext)

        debug('Snap to grid building walls and omit short wall lines')
        min_dist_wall = 1e-3
        sqltext = f"""
            -- extend distance from corner point in those that are too close. From 1e-3 to 5e-2 * dx
            drop table if exists wall_point_adjust;
            create temp table wall_point_adjust as 
            with wall_points as (
                select
                    sw.id, 
                    sw.i, 
                    sw.j,
                    (st_dump(intersec)).geom as point,
                    (st_dump(intersec)).path[1] as pidx
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" sw
            )
            select 
                abs(st_x(point) - (i * {self.cfg.domain.dx} + {self.cfg.domain.origin_x})) / {self.cfg.domain.dx} as x_dist_w,
                abs(st_x(point) - ((i+1) * {self.cfg.domain.dx} + {self.cfg.domain.origin_x})) / {self.cfg.domain.dx} as x_dist_e,
                abs(st_y(point) - (j * {self.cfg.domain.dy} + {self.cfg.domain.origin_y})) / {self.cfg.domain.dy} as y_dist_s,
                abs(st_y(point) - ((j+1) * {self.cfg.domain.dy} + {self.cfg.domain.origin_y})) / {self.cfg.domain.dy} as y_dist_n,
                *
            from wall_points wp;

            drop table if exists wall_point_updater;
            create temp table wall_point_updater as
            with wall_points_modified as (
                select 
                    sa.id, sa.i, sa.j, 
                 case when x_dist_w < 1e-8 and y_dist_n < {min_dist_wall} then -- case where point is on jline and is close to left bottom point in y direction
                     st_setsrid(st_makepoint((sa.i) * {self.cfg.domain.dx} + {self.cfg.domain.origin_x}, (sa.j + 1.0 - {min_dist_wall}) * {self.cfg.domain.dy} + {self.cfg.domain.origin_y}), {self.cfg.srid_palm})
                    when x_dist_w < 1e-8 and y_dist_s < {min_dist_wall} then 
                     st_setsrid(st_makepoint((sa.i) * {self.cfg.domain.dx} + {self.cfg.domain.origin_x}, (sa.j + {min_dist_wall}) * {self.cfg.domain.dy} + {self.cfg.domain.origin_y}), {self.cfg.srid_palm})
                    when x_dist_e < 1e-8 and y_dist_n < {min_dist_wall} then 
                     st_setsrid(st_makepoint((sa.i+1) * {self.cfg.domain.dx} + {self.cfg.domain.origin_x}, (sa.j + 1.0 - {min_dist_wall}) * {self.cfg.domain.dy} + {self.cfg.domain.origin_y}), {self.cfg.srid_palm})
                    when x_dist_e < 1e-8 and y_dist_s < {min_dist_wall} then 
                     st_setsrid(st_makepoint((sa.i+1) * {self.cfg.domain.dx} + {self.cfg.domain.origin_x}, (sa.j + {min_dist_wall}) * {self.cfg.domain.dy} + {self.cfg.domain.origin_y}), {self.cfg.srid_palm})

                    when x_dist_w < {min_dist_wall} and y_dist_s < 1e-8 then -- case where point is on iline
                     st_setsrid(st_makepoint((sa.i + {min_dist_wall}) * {self.cfg.domain.dx} + {self.cfg.domain.origin_x}, (sa.j) * {self.cfg.domain.dy} + {self.cfg.domain.origin_y}), {self.cfg.srid_palm})
                   when x_dist_w < {min_dist_wall} and y_dist_n < 1e-8 then
                     st_setsrid(st_makepoint((sa.i + {min_dist_wall}) * {self.cfg.domain.dx} + {self.cfg.domain.origin_x}, (sa.j+1) * {self.cfg.domain.dy} + {self.cfg.domain.origin_y}), {self.cfg.srid_palm})
                   when x_dist_e < {min_dist_wall} and y_dist_s < 1e-8 then -- case where point is on iline
                     st_setsrid(st_makepoint((sa.i + 1.0 - {min_dist_wall}) * {self.cfg.domain.dx} + {self.cfg.domain.origin_x}, (sa.j) * {self.cfg.domain.dy} + {self.cfg.domain.origin_y}), {self.cfg.srid_palm})
                   when x_dist_e < {min_dist_wall} and y_dist_n < 1e-8 then
                     st_setsrid(st_makepoint((sa.i + 1.0 - {min_dist_wall}) * {self.cfg.domain.dx} + {self.cfg.domain.origin_x}, (sa.j+1) * {self.cfg.domain.dy} + {self.cfg.domain.origin_y}), {self.cfg.srid_palm})
                 else point
                 end as point
                from wall_point_adjust sa
            )
            select 
                wp.id, wp.i, wp.j, 
                st_multi(st_union(array_agg(point))) as intersec
            from wall_points_modified wp
            group by wp.id, wp.i, wp.j;

            create index wall_point_updater_idx on wall_point_updater(id);

            -- Now update intersect in the main table
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" sw
            set intersec = wp.intersec
            from wall_point_updater wp
            where wp.id = sw.id;
        """
        self.execute(sqltext)

        # TODO: check and drop points that are inside structure, e.g. in corners etc

        # Add columns with points and splits
        debug('Adding extra columns to table {}', self.cfg.tables.slanted_wall)
        sqltext = f"""
            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" 
            add column if not exists split geometry(polygon, %s), 
            add column if not exists split_terr_wall geometry(polygon, %s), 
            add column if not exists split1 geometry(polygon, %s), 
            add column if not exists split2 geometry(polygon, %s), 
            add column if not exists point1 geometry(point, %s), 
            add column if not exists point2 geometry(point, %s)
        """
        self.execute(sqltext, (
            self.cfg.srid_palm, self.cfg.srid_palm, self.cfg.srid_palm,
            self.cfg.srid_palm, self.cfg.srid_palm, self.cfg.srid_palm
        ))

        # Set this columns
        debug('Updating slanted walls (splits, points)')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" set 
            split1 = st_setsrid(st_geometryn(st_split(geom, st_linefrommultipoint(intersec)), 1), %s), 
            split2 = st_setsrid(st_geometryn(st_split(geom, st_linefrommultipoint(intersec)), 2), %s), 
            point1 = st_setsrid(st_geometryn(intersec, 1), %s), 
            point2 = st_setsrid(st_geometryn(intersec, 2), %s) 
            where st_npoints(intersec) > 1
        """
        self.execute(sqltext, (
            self.cfg.srid_palm, self.cfg.srid_palm, self.cfg.srid_palm, self.cfg.srid_palm
        ))

        sqltext = f"""
            create index point1_geom_index on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" using gist(point1);
            create index point2_geom_index on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" using gist(point2);
        """
        self.execute(sqltext)

        # TODO: FIXME: UGLY HACK
        # remove the row that where split1 or split2 IS NULL
        sqltext = f"""
            delete from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" 
            where split1 is null or split2 is null
        """
        self.execute(sqltext)

        # Calculate Normal vectors
        debug('Calculating normal vectors')
        sqltext = f"""
            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" 
            add column if not exists cent geometry(point, %s), 
            add column if not exists norm1 geometry(point, %s), 
            add column if not exists norm2 geometry(point, %s), 
            add column if not exists norm geometry(point, %s),
            add column if not exists z1 double precision,
            add column if not exists z1b double precision,
            add column if not exists z2 double precision, 
            add column if not exists z2b double precision, 
            add column if not exists geom3d geometry(polygonz, %s)
        """
        self.execute(sqltext, (
            self.cfg.srid_palm, self.cfg.srid_palm, self.cfg.srid_palm,
            self.cfg.srid_palm, self.cfg.srid_palm
        ))

        # Update Normal vectors
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" set 
            cent = st_setsrid(st_centroid(st_collect(array[point1, point2])), %s)
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" set 
            norm1 = st_setsrid(st_point(st_x(cent) - (st_y(point1)-st_y(point2))/sqrt((st_y(point1)-st_y(point2))^2 + (st_x(point1)-st_x(point2))^2), 
                                        st_y(cent) + (st_x(point1)-st_x(point2))/sqrt((st_y(point1)-st_y(point2))^2 + (st_x(point1)-st_x(point2))^2)), %s), 
            norm2 = st_setsrid(st_point(st_x(cent) + (st_y(point1)-st_y(point2))/sqrt((st_y(point1)-st_y(point2))^2 + (st_x(point1)-st_x(point2))^2), 
                                        st_y(cent) - (st_x(point1)-st_x(point2))/sqrt((st_y(point1)-st_y(point2))^2 + (st_x(point1)-st_x(point2))^2)), %s)
        """
        self.execute(sqltext, (self.cfg.srid_palm, self.cfg.srid_palm,))

        # Now decide which norm vector is the right one
        # sqltext = 'UPDATE "{0}"."{1}" AS sw SET norm = ' \
        #           'CASE WHEN ST_Distance((SELECT geom FROM "{0}"."{2}" WHERE type BETWEEN {3} AND {4} ORDER BY ST_Distance(geom, sw.geom) LIMIT 1), norm1) > ' \
        #           '          ST_Distance((SELECT geom FROM "{0}"."{2}" WHERE type BETWEEN {3} AND {4} ORDER BY ST_Distance(geom, sw.geom) LIMIT 1), norm2) ' \
        #           'THEN norm1 ' \
        #           'ELSE norm2 ' \
        #           'END'\
        #     .format(cfg.domain.case_schema, cfg.tables.slanted_wall, cfg.tables.landcover, cfg.type_range.building_min, cfg.type_range.building_max)
        # self.execute(sqltext)

        # sqltext = 'UPDATE "{0}"."{1}" AS sw SET norm = ' \
        #           'CASE WHEN ST_Distance((SELECT geom FROM "{0}"."{2}" WHERE type BETWEEN {3} AND {4} ORDER BY ST_Distance(geom, sw.cent) LIMIT 1), norm1) > ' \
        #           '          ST_Distance((SELECT geom FROM "{0}"."{2}" WHERE type BETWEEN {3} AND {4} ORDER BY ST_Distance(geom, sw.cent) LIMIT 1), norm2) ' \
        #           'THEN norm1 ' \
        #           'ELSE norm2 ' \
        #           'END'\
        #     .format(cfg.domain.case_schema, cfg.tables.slanted_wall, cfg.tables.landcover, cfg.type_range.building_min, cfg.type_range.building_max)
        # self.execute(sqltext)

        # debug('Deciding which normal vector is correct one (inside or outside of building)')
        # sqltext = 'UPDATE "{0}"."{1}" AS sw SET norm = ' \
        #           'CASE WHEN ST_Distance((SELECT geom FROM "{0}"."{2}" ORDER BY ST_Distance(geom, sw.cent) LIMIT 1), norm1) > ' \
        #           '          ST_Distance((SELECT geom FROM "{0}"."{2}" ORDER BY ST_Distance(geom, sw.cent) LIMIT 1), norm2) ' \
        #           'THEN norm1 ' \
        #           'ELSE norm2 ' \
        #           'END'\
        #     .format(cfg.domain.case_schema, cfg.tables.slanted_wall, cfg.tables.build_new)
        # self.execute(sqltext)

        # debug('Deciding which normal vector is correct one (inside or outside of building)')
        # sqltext = 'UPDATE "{0}"."{1}" AS sw SET norm = ' \
        #           'CASE WHEN ST_Distance((SELECT geom FROM "{0}"."{2}" ORDER BY ST_Distance(geom, sw.cent) LIMIT 1), ' \
        #           '                      ST_SetSRID(ST_MakePoint(ST_X(sw.cent)+{3}*(-ST_X(sw.cent)+ST_X(sw.norm1)), ' \
        #           '                                              ST_Y(sw.cent)+{3}*(-ST_Y(sw.cent)+ST_Y(sw.norm1))), %s))' \
        #           '          > ' \
        #           '          ST_Distance((SELECT geom FROM "{0}"."{2}" ORDER BY ST_Distance(geom, sw.cent) LIMIT 1), ' \
        #           '                      ST_SetSRID(ST_MakePoint(ST_X(sw.cent)+{3}*(-ST_X(sw.cent)+ST_X(sw.norm2)), ' \
        #           '                                              ST_Y(sw.cent)+{3}*(-ST_Y(sw.cent)+ST_Y(sw.norm2))), %s)) ' \
        #           'THEN norm1 ' \
        #           'ELSE norm2 ' \
        #           'END'\
        #     .format(cfg.domain.case_schema, cfg.tables.slanted_wall, cfg.tables.build_new, 0.50)
        # self.execute(sqltext, (cfg.srid_palm, cfg.srid_palm,))

        # # Now decide which split is the one
        # debug('Deciding which split take')
        # sqltext = 'UPDATE "{0}"."{1}" AS sw SET split = ' \
        #           'CASE WHEN ST_Distance(norm, split1) > ' \
        #           '          ST_Distance(norm, split2) ' \
        #           'THEN split1 ' \
        #           'ELSE split2 ' \
        #           'END'\
        #     .format(cfg.domain.case_schema, cfg.tables.slanted_wall)
        # self.execute(sqltext)

        debug('Deciding which split take')
        sqltext = f"""
            with lb as (select geom from "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l where l.type between 900 and 999)
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" as sw set split = 
            case when st_area(st_intersection(lb.geom, split1)) / st_area(split1) > 
                      st_area(st_intersection(lb.geom, split2)) / st_area(split2) 
            then split1 
            else split2 
            end 
            from lb 
            where st_intersects(sw.geom, lb.geom)
        """
        self.execute(sqltext)

        # Now decide which split is the one
        debug('Deciding which normal vector is correct one (inside or outside of building)')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" as sw set norm = 
            case when st_distance(split, norm1) > 
                      st_distance(split, norm2) 
            then norm1 
            else norm2 
            end
        """
        self.execute(sqltext)

        # Now assign split that is for connection terrain and building
        debug('Deciding which split between terrain and building to take')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" as sw set split_terr_wall = 
            case when st_distance(norm, split1) < 
                      st_distance(norm, split2) 
            then split1 
            else split2 
            end
        """
        self.execute(sqltext)

        # Delete unnecessary columns point1, point2, norm1, norm2, split1, split2
        if self.cfg.slanted_pars.clean_up:
            sqltext = f"""
                alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" 
                drop column norm1, 
                drop column norm2, 
                drop column split1, 
                drop column split2, 
                drop column geom
            """
            self.execute(sqltext)

        for i in range(1):
            # Iterate to final solution
            self.calculate_slanted_walls_height()
            self.slanted_wall_height_modifications()
            self.calculate_slanted_walls_height()

        self.create_aux_slanted_wall_height_points()

        self.filter_building_heights()
        self.filter_building_heights()
        self.filter_building_heights()
        self.filter_building_heights()
        self.filter_building_heights()


    def calculate_slanted_walls_height(self):
        """ Calculate slanted walls heights """
        # Process walls heights
        debug('Calculation of z1 (top), z1b (bottom), z2, z2b in the slanted walls from buildings heights')
        max_dist = self.cfg.slanted_pars.wall_build_height_max_dist

        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" set 
            z1 = floor((select height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" hc
                        where st_dwithin(point1, hc.geom, {max_dist}) and height is not null and not dummy_point
                        order by st_distance(point1, hc.geom) 
                        limit 1) / {self.cfg.domain.dz}) * {self.cfg.domain.dz}, 
            z2 = floor((select height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" hc
                        where st_dwithin(point2, hc.geom, {max_dist}) and height is not null and not dummy_point
                        order by st_distance(point2, hc.geom) 
                        limit 1) / {self.cfg.domain.dz}) * {self.cfg.domain.dz}, 
            z1b = floor((select height_bottom from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" hc
                         where st_dwithin(point1, hc.geom, {max_dist}) and height is not null and not dummy_point
                         order by st_distance(point1, hc.geom) 
                         limit 1) / {self.cfg.domain.dz}) * {self.cfg.domain.dz}, 
            z2b = floor((select height_bottom from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" hc
                         where st_dwithin(point2, hc.geom, {max_dist}) and height is not null and not dummy_point
                         order by st_distance(point2, hc.geom) 
                         limit 1) / {self.cfg.domain.dz}) * {self.cfg.domain.dz}
        """
        self.execute(sqltext)

        # process rest of the wall where height and height_bottom is missing
        debug('Correcting missing heights')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" set 
            z1 = floor((select height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" hc
                        where height is not null and not dummy_point
                            and st_dwithin(point1, hc.geom, {self.cfg.domain.dx * 2.0}) 
                        order by st_distance(point1, hc.geom) 
                        limit 1) / {self.cfg.domain.dz}) * {self.cfg.domain.dz}
            where z1 is null
        """
        self.execute(sqltext)

        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" set 
            z1b = floor((select height_bottom from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" hc
                         where height_bottom is not null and not dummy_point
                             and st_dwithin(point1, hc.geom, {self.cfg.domain.dx * 2.0})
                         order by st_distance(point1, hc.geom) 
                         limit 1) / {self.cfg.domain.dz}) * {self.cfg.domain.dz}
            where z1b is null
        """
        self.execute(sqltext)

        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" set 
            z2 = floor((select height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" hc
                        where height is not null and not dummy_point
                            and st_dwithin(point2, hc.geom, {self.cfg.domain.dx * 2.0})
                        order by st_distance(point2, hc.geom) 
                        limit 1) / {self.cfg.domain.dz}) * {self.cfg.domain.dz}
            where z2 is null
        """
        self.execute(sqltext)

        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" set 
            z2b = floor((select height_bottom from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" hc
                         where height_bottom is not null and not dummy_point
                             and st_dwithin(point2, hc.geom, {self.cfg.domain.dx * 2.0})
                         order by st_distance(point2, hc.geom) 
                         limit 1) / {self.cfg.domain.dz}) * {self.cfg.domain.dz}
            where z2b is null
        """
        self.execute(sqltext)

        # Create 3d polygon for debugging and checking
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" set 
            geom3d = st_setsrid(st_makepolygon(st_makeline(array[
                st_makepoint(st_x(point1), st_y(point1), z1b), 
                st_makepoint(st_x(point1), st_y(point1), z1 ), 
                st_makepoint(st_x(point2), st_y(point2), z2 ), 
                st_makepoint(st_x(point2), st_y(point2), z1b), 
                st_makepoint(st_x(point1), st_y(point1), z1b)
            ])), %s)
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        # update wid
        debug('Updating wid')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" set 
            wid = (select wid from "{self.cfg.domain.case_schema}"."{self.cfg.tables.walls}" as w
                   where st_dwithin(w.geom, geom3d, {2.0 * self.cfg.domain.dx})
                   order by st_distance(w.geom, geom3d) 
                   limit 1)
        """
        self.execute(sqltext)

    def create_aux_slanted_wall_height_points(self):
        """"""
        debug('Creating supplementary table {}', self.cfg.tables.slanted_wall_points)

        sqltext = f"""
            drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_points}";

            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_points}" as (
                select st_setsrid(st_makepoint(st_x(point1), st_y(point1)), %s) as w_point, z1 as z 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" 
                union all  
                select st_setsrid(st_makepoint(st_x(point2), st_y(point2)), %s) as w_point, z2 as z 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}"
            ); 

            create index sw_point_geom_index on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_points}" using gist(w_point);
        """
        self.execute(sqltext, (self.cfg.srid_palm, self.cfg.srid_palm,))

    def slanted_wall_height_modifications(self):
        """ Iteratively modify height in slanted walls and building height near edges """

        self.create_aux_slanted_wall_height_points()

        debug('Based on height from wall edges, update near building heights')
        sqltext = f"""
            with correct_height_near_edge as (
                select bh.i, bh.j, sw.z as new_height
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" bh
                    join lateral( 
                        select sw.z 
                        from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_points}" sw 
                        where st_dwithin(bh.geom, sw.w_point, {1.44 * np.sqrt(self.cfg.domain.dx ** 2 + self.cfg.domain.dy ** 2)})
                            and sw.z > bh.height
                            and not bh.dummy_point
                        order by sw.z desc
                        limit 1
                    ) sw on true
            )
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" bh
            set height = ch.new_height
            from correct_height_near_edge ch
            where bh.i = ch.i and bh.j = ch.j and not bh.dummy_point;
        """
        self.execute(sqltext)

        debug('Adjust dummy point height in building heights')
        sqltext = f"""
            with dummy_point_update as (
                select bh.i, bh.j, swp.height
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" bh
                    join lateral (
                        select z as height
                        from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_points}" swp
                        where st_dwithin(swp.w_point, bh.geom, {self.cfg.domain.dx})
                        order by st_distance(swp.w_point, bh.geom) asc
                        limit 1
                    ) swp on true
                where bh.dummy_point
            )
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" bh
            set height = dpu.height
            from dummy_point_update dpu
            where bh.i = dpu.i and bh.j = dpu.j and bh.dummy_point;
        """
        self.execute(sqltext)

        # Now perform filtering
        self.filter_building_heights()

    def create_slated_roof(self):
        """ Create slanted roof """
        progress('Creating slanted roof')

        sqltext = f'drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}"'
        self.execute(sqltext)

        sqltext = f"""
            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" as 
            select id, i, j, cast(null as integer) as rid, split 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}"
        """
        self.execute(sqltext)

        # add remaining buildings grid
        # sqltext = f"""
        #     insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}"
        #     select bg.id, bg.i, bg.j, bg.geom
        #     from "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_grid}" as bg
        #     left join "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" as sr on sr.id = bg.id
        #     where sr.id is null
        # """
        # self.execute(sqltext)

        # add rest of the roofs
        sqltext = f"""
            with nb as (select geom from "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l where l.type between 900 and 999)
            insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" as sr 
            select g.id, g.i, g.j, null, g.geom 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" as g, nb 
            where (st_intersects(g.point, nb.geom) and 
                   g.id not in (select id from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}"))
        """
        self.execute(sqltext)

        # put geom index on split polygon
        sqltext = f'create index slanted_roof_geom_idx on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" using gist(split)'
        self.execute(sqltext)

        # Add edge points in roof geoms, max 5 points
        sqltext = f"""
            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" 
            add column if not exists p1 geometry("point", %s), 
            add column if not exists p2 geometry("point", %s), 
            add column if not exists p3 geometry("point", %s), 
            add column if not exists p4 geometry("point", %s), 
            add column if not exists p5 geometry("point", %s), 
            add column if not exists p6 geometry("point", %s), 
            add column if not exists norm geometry("pointz", %s), 
            add column if not exists cent geometry("pointz", %s), 
            add column if not exists geom3d geometry("polygonz", %s), 
            add column if not exists z1 double precision, 
            add column if not exists z2 double precision, 
            add column if not exists z3 double precision, 
            add column if not exists z4 double precision, 
            add column if not exists z5 double precision, 
            add column if not exists z6 double precision, 
            add column if not exists n_edges integer
        """
        self.execute(sqltext, (self.cfg.srid_palm,) * 9)

        # fill the points
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" set 
            n_edges = st_npoints(split)-1, 
            p1 = case when st_npoints(split) > 1 then st_pointn(st_boundary(split), 1) else null end, 
            p2 = case when st_npoints(split) > 1 then st_pointn(st_boundary(split), 2) else null end, 
            p3 = case when st_npoints(split) > 1 then st_pointn(st_boundary(split), 3) else null end, 
            p4 = case when st_npoints(split) > 1 then st_pointn(st_boundary(split), 4) else null end, 
            p5 = case when st_npoints(split) > 1 then st_pointn(st_boundary(split), 5) else null end
        """
        self.execute(sqltext)

        # TODO: Add p6 point in case of z1 != z2 from walls
        # sqltext = f"""
        #     update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" as sr set
        #     n_edges = st_npoints(sr.split)-1+1,
        #     p6 = case when sw.z1 > sw.z2 then st_setsrid(st_makepoint(st_x(sw.point1), st_y(sw.point1)), %s)
        #              else st_setsrid(st_makepoint(st_x(sw.point2), st_y(sw.point2)), %s) end,
        #     z6 = case when sw.z1 > sw.z2 then sw.z2 else sw.z1 end
        #     from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}" as sw
        #     where sw.id = sr.id and sw.z1 != sw.z2
        # """
        # self.execute(sqltext, (self.cfg.srid_palm, self.cfg.srid_palm))

        # add indexes on p1 .. p6
        sqltext = f"""
            create index p1_geom_index on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" using gist(p1); 
            create index p2_geom_index on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" using gist(p2); 
            create index p3_geom_index on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" using gist(p3); 
            create index p4_geom_index on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" using gist(p4); 
            create index p5_geom_index on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" using gist(p5); 
            create index p6_geom_index on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" using gist(p6);
        """
        self.execute(sqltext)

        #### SOLUTION WITH USING DIRECTLY RASTER (Commented)
        # ... (all internal logic of this block would be converted similarly if uncommented)

        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" set 
            z1 = (case when p1 is not null then (select height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" hc
                         where st_dwithin(p1, hc.geom, {self.cfg.slanted_pars.wall_build_height_max_dist}) and height is not null and not dummy_point 
                         order by st_distance(p1, hc.geom) 
                         limit 1) else null end), 
            z2 = (case when p2 is not null then (select height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" hc
                         where st_dwithin(p2, hc.geom, {self.cfg.slanted_pars.wall_build_height_max_dist}) and height is not null and not dummy_point
                         order by st_distance(p2, hc.geom) 
                         limit 1) else null end), 
            z3 = (case when p3 is not null then (select height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" hc
                         where st_dwithin(p3, hc.geom, {self.cfg.slanted_pars.wall_build_height_max_dist}) and height is not null and not dummy_point 
                         order by st_distance(p3, hc.geom) 
                         limit 1) else null end), 
            z4 = (case when p4 is not null then (select height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" hc
                         where st_dwithin(p4, hc.geom, {self.cfg.slanted_pars.wall_build_height_max_dist}) and height is not null and not dummy_point 
                         order by st_distance(p4, hc.geom) 
                         limit 1) else null end), 
            z5 = (case when p5 is not null then (select height from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" hc
                         where st_dwithin(p5, hc.geom, {self.cfg.slanted_pars.wall_build_height_max_dist}) and height is not null and not dummy_point 
                         order by st_distance(p5, hc.geom) 
                         limit 1) else null end)
        """
        self.execute(sqltext)

        # fill the missing ones
        debug('Filling missing height in slanted roof')
        for pi in range(1, 6):
            verbose('Filling missing {} height in slanted roof tables', pi)
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" as sr set 
                z{pi} = (select z from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_points}" as sw 
                        where st_dwithin(w_point, p{pi}, {4.0 * self.cfg.domain.dx}) 
                        order by p{pi} <-> sw.w_point limit 1)
                where z{pi} is null and p{pi} is not null
            """
            self.execute(sqltext)

        # modify height at the roof edge, set to floor(height)
        debug('Modification of roof edge height')
        roofs_dist2edge = self.cfg.slanted_pars.roofs_dist2edge
        sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" set
                z1 = case when (select st_distance(p1, geom) 
                                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.walls_outer}" 
                                where st_dwithin(p1, geom, 1.2 * {roofs_dist2edge})
                                order by st_distance(p1, geom) limit 1) < {roofs_dist2edge} then floor(z1 / {self.cfg.domain.dz}) * {self.cfg.domain.dz} else z1 end, 
                z2 = case when (select st_distance(p2, geom) 
                                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.walls_outer}" 
                                where st_dwithin(p2, geom, 1.2 * {roofs_dist2edge})
                                order by st_distance(p2, geom) limit 1) < {roofs_dist2edge} then floor(z2 / {self.cfg.domain.dz}) * {self.cfg.domain.dz} else z2 end, 
                z3 = case when (select st_distance(p3, geom) 
                                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.walls_outer}" 
                                where st_dwithin(p3, geom, 1.2 * {roofs_dist2edge})
                                order by st_distance(p3, geom) limit 1) < {roofs_dist2edge} then floor(z3 / {self.cfg.domain.dz}) * {self.cfg.domain.dz} else z3 end, 
                z4 = case when (select st_distance(p4, geom) 
                                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.walls_outer}" 
                                where st_dwithin(p4, geom, 1.2 * {roofs_dist2edge})
                                order by st_distance(p4, geom) limit 1) < {roofs_dist2edge} then floor(z4 / {self.cfg.domain.dz}) * {self.cfg.domain.dz} else z4 end, 
                z5 = case when (select st_distance(p5, geom) 
                                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.walls_outer}" 
                                where st_dwithin(p5, geom, 1.2 * {roofs_dist2edge})
                                order by st_distance(p5, geom) limit 1) < {roofs_dist2edge} then floor(z5 / {self.cfg.domain.dz}) * {self.cfg.domain.dz} else z5 end 
        """
        self.execute(sqltext)

        for pi in range(1, 6):
            verbose('Correcting point {} height in slanted roof tables', pi)
            sqltext = f"""
            with found_edges as (
                select swp.z as new_z, sr.id
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" sr
                    join "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_points}" swp on 
                            st_distance(swp.w_point, sr.p{pi}) < 1e-5 and st_dwithin(swp.w_point, sr.p{pi}, 0.2)
            )
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" sr
            set z{pi} = new_z
            from found_edges fe
            where fe.id = sr.id;
            """
            self.execute(sqltext)

        # find center and normal vector
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" set 
            cent = st_setsrid(st_makepoint(st_x(st_centroid(split)), 
                                           st_y(st_centroid(split)), 
                                           (coalesce(z1, 0.0) + coalesce(z2, 0.0) + coalesce(z3, 0.0) + coalesce(z4, 0.0) + coalesce(z5, 0.0))/n_edges), %s)
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        # Create 3D polygon of the roof
        debug('Creating 3d polygon')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}" set 
            geom3d = st_setsrid(st_convexhull(st_collect(array[
                st_makepoint(st_x(p1), st_y(p1), z1), st_makepoint(st_x(p2), st_y(p2), z2), st_makepoint(st_x(p3), st_y(p3), z3), 
                st_makepoint(st_x(p4), st_y(p4), z4), st_makepoint(st_x(p5), st_y(p5), z5)
            ])), %s) 
            where st_npoints(st_collect(array[
                     st_makepoint(st_x(p1), st_y(p1), z1), st_makepoint(st_x(p2), st_y(p2), z2), st_makepoint(st_x(p3), st_y(p3), z3), 
                     st_makepoint(st_x(p4), st_y(p4), z4), st_makepoint(st_x(p5), st_y(p5), z5)
            ])) > 2
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        debug('Updating rid')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}"
            set rid = r.rid 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.roofs}" r
            where st_intersects(r.geom, geom3d)
        """
        self.execute(sqltext)

        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}"  
            set rid = (select rid from "{self.cfg.domain.case_schema}"."{self.cfg.tables.roofs}" as r
                   order by st_distance(r.geom, geom3d) 
                   limit 1) 
            where rid is null
        """
        self.execute(sqltext)

    def create_grid_slanted_walls(self):
        """ Grid slanted walls """
        progress('Processing slanted walls into gridded structure')

        sqltext = f'drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_gridded}"'
        self.execute(sqltext)

        sqltext = f"""
            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_gridded}" (
                id integer, 
                wid integer, 
                geom geometry("polygonz", %s), 
                norm geometry("pointz", %s)
            )
        """
        self.execute(sqltext, (self.cfg.srid_palm, self.cfg.srid_palm))

        # find max height -> k_max
        sqltext = f'select max(z1), max(z2) from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}"'
        z_max = self.fetch(sqltext)
        z_max = [x for x in z_max[0]]
        k_max = int(max(z_max) / self.cfg.domain.dz) + 1

        for k in range(1, k_max):
            sqltext = f'drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_gridded_temp}"'
            self.execute(sqltext)

            sqltext = f"""
                create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_gridded_temp}" as 
                select id, wid, 
                st_x(point1) as x1, st_y(point1) as y1, 
                st_x(point2) as x2, st_y(point2) as y2,
                z1, z2, z1b, z2b, norm  
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall}"
            """
            self.execute(sqltext)

            sqltext = f"""
                alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_gridded_temp}" 
                add column if not exists t_t double precision, add column if not exists t_l double precision,  
                add column if not exists x1l double precision, add column if not exists y1l double precision,  
                add column if not exists z1l double precision, add column if not exists x1t double precision,  
                add column if not exists y1t double precision, add column if not exists z1t double precision,  
                add column if not exists x2l double precision, add column if not exists y2l double precision,  
                add column if not exists z2l double precision, add column if not exists x2t double precision,  
                add column if not exists y2t double precision, add column if not exists z2t double precision,  
                add column if not exists x12l double precision, add column if not exists y12l double precision, 
                add column if not exists z12l double precision, add column if not exists x12t double precision, 
                add column if not exists y12t double precision, add column if not exists z12t double precision, 
                add column if not exists z_cent double precision, add column if not exists n_vert integer, 
                add column if not exists p1l geometry(pointz, %s), add column if not exists p1t geometry(pointz, %s), 
                add column if not exists p2l geometry(pointz, %s), add column if not exists p2t geometry(pointz, %s), 
                add column if not exists p12l geometry(pointz, %s), add column if not exists p12t geometry(pointz, %s)
            """
            self.execute(sqltext, (self.cfg.srid_palm,) * 6)

            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_gridded_temp}" set 
                t_t = case when z1 >= {k * self.cfg.domain.dz} and z2 >= {k * self.cfg.domain.dz} then 0.0 
                           when z1 <= {k * self.cfg.domain.dz} and z2 >= {k * self.cfg.domain.dz} then ({k * self.cfg.domain.dz} - z1) / (z2 - z1)
                           when z1 >= {k * self.cfg.domain.dz} and z2 <= {k * self.cfg.domain.dz} then ({k * self.cfg.domain.dz} - z1) / (z2 - z1)
                           else 0.0 end,
                t_l = case when z1 >= {k * self.cfg.domain.dz} and z2 >= {k * self.cfg.domain.dz} then 0.0 
                           when z1 >= ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) and z2 >= ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) then 0.0
                           when z1 <= ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) and z2 >= ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) then ({k * self.cfg.domain.dz} - {self.cfg.domain.dz} - z1) / (z2 - z1)
                           when z1 >= ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) and z2 <= ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) then ({k * self.cfg.domain.dz} - {self.cfg.domain.dz} - z1) / (z2 - z1)
                           else 0.0 end
            """
            self.execute(sqltext)

            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_gridded_temp}" set 
                x1l = case when z1 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) or z1b > ({k * self.cfg.domain.dz}) then null else x1 end, 
                y1l = case when z1 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) or z1b > ({k * self.cfg.domain.dz}) then null else y1 end, 
                z1l = case when z1 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) or z1b > ({k * self.cfg.domain.dz}) then null else ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) end, 
                x1t = case when z1 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) or z1b > ({k * self.cfg.domain.dz}) then null else x1 end, 
                y1t = case when z1 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) or z1b > ({k * self.cfg.domain.dz}) then null else y1 end, 
                z1t = case when z1 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) or z1b > ({k * self.cfg.domain.dz}) then null when z1 < {k * self.cfg.domain.dz} then z1 else {k * self.cfg.domain.dz} end, 
                x2l = case when z2 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) or z2b > ({k * self.cfg.domain.dz}) then null else x2  end, 
                y2l = case when z2 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) or z2b > ({k * self.cfg.domain.dz}) then null else y2  end, 
                z2l = case when z2 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) or z2b > ({k * self.cfg.domain.dz}) then null else ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) end, 
                x2t = case when z2 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) or z2b > ({k * self.cfg.domain.dz}) then null else x2 end, 
                y2t = case when z2 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) or z2b > ({k * self.cfg.domain.dz}) then null else y2 end, 
                z2t = case when z2 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) or z2b > ({k * self.cfg.domain.dz}) then null when z2 < {k * self.cfg.domain.dz} then z2 else {k * self.cfg.domain.dz} end, 
                x12l = case when (z1 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) and z2 > ({k * self.cfg.domain.dz} - {self.cfg.domain.dz})) or (z1 > ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) and z2 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz})) then x1 + t_l*(x2-x1) else null end, 
                y12l = case when (z1 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) and z2 > ({k * self.cfg.domain.dz} - {self.cfg.domain.dz})) or (z1 > ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) and z2 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz})) then y1 + t_l*(y2-y1) else null end, 
                z12l = case when (z1 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) and z2 > ({k * self.cfg.domain.dz} - {self.cfg.domain.dz})) or (z1 > ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) and z2 < ({k * self.cfg.domain.dz} - {self.cfg.domain.dz})) then ({k * self.cfg.domain.dz} - {self.cfg.domain.dz}) else null end, 
                x12t = case when (z1 < {k * self.cfg.domain.dz} and z2 > {k * self.cfg.domain.dz}) or (z1 > {k * self.cfg.domain.dz} and z2 < {k * self.cfg.domain.dz}) then x1 + t_t*(x2-x1) else null end, 
                y12t = case when (z1 < {k * self.cfg.domain.dz} and z2 > {k * self.cfg.domain.dz}) or (z1 > {k * self.cfg.domain.dz} and z2 < {k * self.cfg.domain.dz}) then y1 + t_t*(y2-y1) else null end, 
                z12t = case when (z1 < {k * self.cfg.domain.dz} and z2 > {k * self.cfg.domain.dz}) or (z1 > {k * self.cfg.domain.dz} and z2 < {k * self.cfg.domain.dz}) then {k * self.cfg.domain.dz} else null end
            """
            self.execute(sqltext)

            self.execute(f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_gridded_temp}" set n_vert = 
                (case when z1l is not null then 1 else 0 end) + (case when z1t is not null then 1 else 0 end) + 
                (case when z2l is not null then 1 else 0 end) + (case when z2t is not null then 1 else 0 end) + 
                (case when z12l is not null then 1 else 0 end) + (case when z12t is not null then 1 else 0 end)
            """)

            self.execute(f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_gridded_temp}" set z_cent = 
                (coalesce(z1l, 0) + coalesce(z1t, 0) + coalesce(z2l, 0) + coalesce(z2t, 0) + coalesce(z12l, 0) + coalesce(z12t, 0)) / n_vert 
                where n_vert > 0
            """)

            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_gridded_temp}" set 
                p1l = case when x1l is not null then st_setsrid(st_makepoint(x1l, y1l, z1l), %s) else null end, 
                p1t = case when x1t is not null then st_setsrid(st_makepoint(x1t, y1t, z1t), %s) else null end, 
                p2l = case when x2l is not null then st_setsrid(st_makepoint(x2l, y2l, z2l), %s) else null end, 
                p2t = case when x2t is not null then st_setsrid(st_makepoint(x2t, y2t, z2t), %s) else null end, 
                p12l= case when x12l is not null then st_setsrid(st_makepoint(x12l, y12l, z12l), %s) else null end, 
                p12t= case when x12t is not null then st_setsrid(st_makepoint(x12t, y12t, z12t), %s) else null end
            """
            self.execute(sqltext, (self.cfg.srid_palm,) * 6)

            sqltext = f"""
                insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_gridded}" 
                select id, wid, st_setsrid(st_makepolygon(st_makeline(array[p1l, p1t, p12t, p2t, p2l, p12l, 
                case when p1l is not null then p1l when p1t is not null then p1t when p12t is not null then p12t 
                     when p2t is not null then p2t when p2l is not null then p2l when p12l is not null then p12l end])), %s), 
                st_setsrid(st_makepoint(st_x(norm), st_y(norm), z_cent), %s)
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_gridded_temp}"
                where (case when p1l is null then 0 else 1 end + case when p1t is null then 0 else 1 end + 
                       case when p2l is null then 0 else 1 end + case when p2t is null then 0 else 1 end + 
                       case when p12l is null then 0 else 1 end + case when p12t is null then 0 else 1 end) > 2
            """
            self.execute(sqltext, (self.cfg.srid_palm, self.cfg.srid_palm))

    def create_grid_slanted_terrain(self):
        """ Process slanted terrain into gridded slanted terrain """
        progress('gridding the slanted terrain')

        sqltext = f"""
            drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}";
            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" (
                id integer, 
                lid integer,  
                geom geometry("polygonz", %s), 
                points geometry("multipointz", %s),
                lines geometry("linestringz", %s)
            )
        """
        self.execute(sqltext, (self.cfg.srid_palm,) * 3)

        # get terrain max height
        debug('selecting max height')
        sqltext = f'select max(height) from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_terr_corrected}"'
        z_max = self.execute(sqltext)[0][0]
        k_max = int(np.ceil(z_max) / self.cfg.domain.dz) + 2

        debug('loop over all k-levels')
        for k in range(0, k_max):
            debug(f'k={k}')
            # create temp table
            verbose('drop temp table')
            self.execute(
                f'drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded_temp}"')

            verbose('create temp table')
            self.execute(f"""
                create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded_temp}" as 
                select id, lid, geom3d 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain}"
            """)

            verbose('add new columns in temp table')
            self.execute(f"""
                alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded_temp}" 
                add column if not exists npoints integer, 
                add column if not exists z1 double precision, 
                add column if not exists z2 double precision, 
                add column if not exists mezi_dolni boolean default false, 
                add column if not exists mezi_horni boolean default false, 
                add column if not exists p1 geometry(pointz, %s), 
                add column if not exists p2 geometry(pointz, %s)
            """, (self.cfg.srid_palm,) * 2)

            verbose('loop over all points')
            for po in range(1, 6):  # 6 points is maximum and the last is repeated
                verbose(f'point {po}')
                self.execute(f"""
                    alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded_temp}" 
                    add column if not exists p{po}_mezid geometry(pointz, %s), 
                    add column if not exists p{po}_mezih geometry(pointz, %s), 
                    add column if not exists p{po}_f geometry(pointz, %s)
                """, (self.cfg.srid_palm,) * 3)

                self.execute(f"""
                    update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded_temp}" set 
                    p1 = st_pointn(st_exteriorring(geom3d), {po}), 
                    p2 = st_pointn(st_exteriorring(geom3d), {po}+1)
                """)

                dz = self.cfg.domain.dz
                k_dz = k * dz
                self.execute(f"""
                    update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded_temp}" set 
                    mezi_dolni = case when st_z(p1) < ({k_dz}-{dz}) and (st_z(p2) > ({k_dz}-{dz})) then true
                                      when st_z(p1) > ({k_dz}-{dz}) and (st_z(p2) < ({k_dz}-{dz})) then true
                                      else false end, 
                    mezi_horni = case when st_z(p1) < {k_dz} and (st_z(p2) > {k_dz}) then true
                                      when st_z(p1) > {k_dz} and (st_z(p2) < {k_dz}) then true 
                                      else false end, 
                    z2 = case when st_z(p2) < ({k_dz}-{dz}) then null
                              when st_z(p2) > {k_dz} then {k_dz}
                              else st_z(p2) end
                """)

                self.execute(f"""
                    update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded_temp}" set 
                    p{po}_mezid = case when mezi_dolni then st_setsrid(st_makepoint(
                        st_x(p1) + ({k_dz}-{dz}-st_z(p1))/(st_z(p2)-st_z(p1))*(st_x(p2)-st_x(p1)), 
                        st_y(p1) + ({k_dz}-{dz}-st_z(p1))/(st_z(p2)-st_z(p1))*(st_y(p2)-st_y(p1)), 
                        {k_dz}-{dz}), %s) else null end, 
                    p{po}_mezih = case when mezi_horni then st_setsrid(st_makepoint(
                        st_x(p1) + ({k_dz}-st_z(p1))/(st_z(p2)-st_z(p1))*(st_x(p2)-st_x(p1)), 
                        st_y(p1) + ({k_dz}-st_z(p1))/(st_z(p2)-st_z(p1))*(st_y(p2)-st_y(p1)), 
                        {k_dz}), %s) else null end, 
                    p{po}_f = case when st_z(p2) >= ({k_dz}-{dz}) and st_z(p2) <= {k_dz} 
                              then st_setsrid(st_makepoint(st_x(p2), st_y(p2), z2), %s) else null end
                """, (self.cfg.srid_palm,) * 3)

                # set mezi_dolni, mezi_horni to false
                self.execute(
                    f'update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded_temp}" set mezi_dolni = false, mezi_horni = false')

            # gather point to form polygon
            debug('gathering points')
            self.execute(f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded_temp}" set 
                npoints = (case when p1_mezid is not null then 1 else 0 end + case when p1_mezih is not null then 1 else 0 end + case when p1_f is not null then 1 else 0 end + 
                           case when p2_mezid is not null then 1 else 0 end + case when p2_mezih is not null then 1 else 0 end + case when p2_f is not null then 1 else 0 end + 
                           case when p3_mezid is not null then 1 else 0 end + case when p3_mezih is not null then 1 else 0 end + case when p3_f is not null then 1 else 0 end + 
                           case when p4_mezid is not null then 1 else 0 end + case when p4_mezih is not null then 1 else 0 end + case when p4_f is not null then 1 else 0 end + 
                           case when p5_mezid is not null then 1 else 0 end + case when p5_mezih is not null then 1 else 0 end + case when p5_f is not null then 1 else 0 end)
            """)

            debug('insert point into points collection')
            self.execute(f"""
                insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" (id, lid, points) 
                select id, lid, st_setsrid(st_collect(array[p1_mezid, p1_mezih, p1_f, p2_mezid, p2_mezih, p2_f, p3_mezid, p3_mezih, p3_f, p4_mezid, p4_mezih, p4_f, p5_mezid, p5_mezih, p5_f]), %s) 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded_temp}" 
                where npoints > 2
            """, (self.cfg.srid_palm,))
        debug('creating polygon geom')
        self.execute(
            f'update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" set geom = st_setsrid(st_convexhull(points), %s)',
            (self.cfg.srid_palm,))

        verbose('updating its srid')
        self.execute(
            f'update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" set lines = st_setsrid(st_boundary(geom), %s)',
            (self.cfg.srid_palm,))

        # delete duplicates
        verbose('deleting duplicates')
        self.execute(
            f'alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" add column if not exists rgid serial')

        self.execute(f"""
            delete from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" 
            where rgid in (select rgid from (select rgid, row_number() over (partition by geom order by id) as rownumber 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}") as t where t.rownumber > 1)
        """)

        # mb here
        debug('separate polygon when 3 or more vertices has z = (k+1)*dz')
        self.execute(f"""
            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" 
            add column if not exists vert1 geometry(pointz, %s), add column if not exists vert2 geometry(pointz, %s), 
            add column if not exists vert3 geometry(pointz, %s), add column if not exists vert4 geometry(pointz, %s), 
            add column if not exists vert5 geometry(pointz, %s), add column if not exists vert6 geometry(pointz, %s), 
            add column if not exists vert7 geometry(pointz, %s), add column if not exists z_max double precision, 
            add column if not exists z_min double precision, add column if not exists k_max integer, 
            add column if not exists n_vert integer
        """, (self.cfg.srid_palm,) * 7)

        verbose('create vert points')
        self.execute(f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" set 
            vert1 = st_pointn(st_boundary(geom), 1), vert2 = st_pointn(st_boundary(geom), 2), 
            vert3 = st_pointn(st_boundary(geom), 3), vert4 = st_pointn(st_boundary(geom), 4), 
            vert5 = st_pointn(st_boundary(geom), 5), vert6 = st_pointn(st_boundary(geom), 6), 
            vert7 = st_pointn(st_boundary(geom), 7)
        """)

        verbose('calculate number of points')
        self.execute(
            f'update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" set n_vert = st_npoints(points)+1')

        self.execute(f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" set 
            z_max = greatest(st_z(st_geometryn(points, 1)), st_z(st_geometryn(points, 2)), st_z(st_geometryn(points, 3)), 
                             st_z(st_geometryn(points, 4)), st_z(st_geometryn(points, 5)), st_z(st_geometryn(points, 6)), st_z(st_geometryn(points, 7))),
            z_min = least(st_z(st_geometryn(points, 1)), st_z(st_geometryn(points, 2)), st_z(st_geometryn(points, 3)), 
                          st_z(st_geometryn(points, 4)), st_z(st_geometryn(points, 5)), st_z(st_geometryn(points, 6)), st_z(st_geometryn(points, 7)))
        """)

        verbose('selecting polygons')
        z_max = self.execute(
            f'select max(z_max) from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}"')[0][0]
        k_max = int(np.floor(z_max) + 2)

        for k in range(0, k_max):
            sqltext = f"""
                select id, rgid, lid, n_vert, 
                array[st_x(vert1), st_y(vert1), st_z(vert1)],  
                array[st_x(vert2), st_y(vert2), st_z(vert2)], 
                array[st_x(vert3), st_y(vert3), st_z(vert3)], 
                array[st_x(vert4), st_y(vert4), st_z(vert4)], 
                array[st_x(vert5), st_y(vert5), st_z(vert5)], 
                array[st_x(vert6), st_y(vert6), st_z(vert6)], 
                array[st_x(vert7), st_y(vert7), st_z(vert7)]  
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" as s 
                where (case when st_z(vert1) = {(k + 1) * self.cfg.domain.dz} then 1 else 0 end + 
                       case when st_z(vert2) = {(k + 1) * self.cfg.domain.dz} then 1 else 0 end + 
                       case when st_z(vert3) = {(k + 1) * self.cfg.domain.dz} then 1 else 0 end + 
                       case when st_z(vert4) = {(k + 1) * self.cfg.domain.dz} and n_vert > 4 then 1 else 0 end + 
                       case when st_z(vert5) = {(k + 1) * self.cfg.domain.dz} and n_vert > 5 then 1 else 0 end + 
                       case when st_z(vert6) = {(k + 1) * self.cfg.domain.dz} and n_vert > 6 then 1 else 0 end + 
                       case when st_z(vert7) = {(k + 1) * self.cfg.domain.dz} and n_vert > 7 then 1 else 0 end) > 2 
                      and n_vert > 3 and z_min != z_max 
            """
            verts = self.execute(sqltext)

            to_insert = []
            to_delete = []
            for vert in verts:
                p1 = []
                p2 = []
                np_verts_p1 = np.empty((7, 3), dtype=object)
                np_verts_p2 = np.empty((7, 3), dtype=object)
                id, rgid, lid, n_vert = vert[0], vert[1], vert[2], vert[3]
                lastidx = 4
                x_vert, y_vert, z_vert = [], [], []
                for idx in range(n_vert):
                    if vert[lastidx + idx][0] is not None:
                        x_vert.append(vert[lastidx + idx][0])
                        y_vert.append(vert[lastidx + idx][1])
                        z_vert.append(vert[lastidx + idx][2])
                x_vert = np.asarray(x_vert)
                y_vert = np.asarray(y_vert)
                z_vert = np.asarray(z_vert)
                tt_max = max(z_vert)
                for it, ttt in enumerate(z_vert):
                    if it == 0:
                        ileft = len(z_vert) - 1
                        iright = it + 1
                    elif it == len(z_vert) - 1:
                        iright = 0
                        ileft = it - 1
                    else:
                        iright = it + 1
                        ileft = it - 1
                    if z_vert[ileft] == tt_max and z_vert[it] == tt_max and z_vert[iright] == tt_max:
                        p2.append(it)
                    else:
                        if z_vert[it] == tt_max:
                            p1.append(it)
                            p2.append(it)
                        else:
                            p1.append(it)

                if len(p1) > 2:
                    n_vert1 = len(p1) + 1
                    np_verts_p1[:n_vert1 - 1, 0] = x_vert[p1]
                    np_verts_p1[:n_vert1 - 1, 1] = y_vert[p1]
                    np_verts_p1[:n_vert1 - 1, 2] = z_vert[p1]
                    np_verts_p1[n_vert1 - 1, :] = np_verts_p1[0, :]
                    to_insert.append((rgid, lid, n_vert1,
                                      *np_verts_p1[0], self.cfg.srid_palm,
                                      *np_verts_p1[1], self.cfg.srid_palm,
                                      *np_verts_p1[2], self.cfg.srid_palm,
                                      *np_verts_p1[3], self.cfg.srid_palm,
                                      *np_verts_p1[4], self.cfg.srid_palm,
                                      *np_verts_p1[5], self.cfg.srid_palm,
                                      *np_verts_p1[6], self.cfg.srid_palm))
                if len(p2) > 2:
                    n_vert2 = len(p2) + 1
                    np_verts_p2[:n_vert2 - 1, 0] = x_vert[p2]
                    np_verts_p2[:n_vert2 - 1, 1] = y_vert[p2]
                    np_verts_p2[:n_vert2 - 1, 2] = z_vert[p2]
                    np_verts_p2[n_vert2 - 1, :] = np_verts_p2[0, :]
                    to_insert.append((rgid, lid, n_vert2,
                                      *np_verts_p2[0], self.cfg.srid_palm,
                                      *np_verts_p2[1], self.cfg.srid_palm,
                                      *np_verts_p2[2], self.cfg.srid_palm,
                                      *np_verts_p2[3], self.cfg.srid_palm,
                                      *np_verts_p2[4], self.cfg.srid_palm,
                                      *np_verts_p2[5], self.cfg.srid_palm,
                                      *np_verts_p2[6], self.cfg.srid_palm))
                if len(p2) > 2 or len(p1) > 2:
                    to_delete.append((rgid,))

            debug('deleting all unwanted rows')
            sqltext = f'delete from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" where rgid = any(%s)'
            self.execute(sqltext, (to_delete,))

            debug('inserting all new entries into slanted faces table')
            sqltext = f"""
                insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" 
                (id, rgid, lid, n_vert, vert1, vert2, vert3, vert4, vert5, vert6, vert7) 
                values (null, %s, %s, %s, 
                        st_setsrid(st_makepoint(%s, %s, %s), %s), 
                        st_setsrid(st_makepoint(%s, %s, %s), %s), 
                        st_setsrid(st_makepoint(%s, %s, %s), %s), 
                        st_setsrid(st_makepoint(%s, %s, %s), %s), 
                        st_setsrid(st_makepoint(%s, %s, %s), %s), 
                        st_setsrid(st_makepoint(%s, %s, %s), %s), 
                        st_setsrid(st_makepoint(%s, %s, %s), %s) 
                )
            """
            self.executemany(sqltext, to_insert)

            debug('updating 3d polygon')
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" set geom =  
                st_forcerhr(
                st_setsrid(st_makepolygon(st_makeline(array[vert1, vert2, vert3, vert4, vert5, vert6, vert7,
                     case when vert1 is not null then vert1 
                          when vert2 is not null then vert2 
                          when vert3 is not null then vert3 
                          when vert4 is not null then vert4 
                          when vert5 is not null then vert5 
                          when vert6 is not null then vert6 
                          when vert7 is not null then vert7 end
                ])), %s)) 
                where geom is null
            """
            self.execute(sqltext, (self.cfg.srid_palm,))

        # TODO: create new serial index
        self.execute(f"""
            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" drop column if exists id; 
            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" add column id serial
        """)

        self.execute(
            f'alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" add primary key (id)')

        # sqltext = 'alter table "{0}"."{1}" drop column if exists i; ' \
        #           'alter table "{0}"."{1}" drop column if exists j;' \
        #           'alter table "{0}"."{1}" drop column if exists k;'.format(cfg.domain.case_schema, cfg.tables.slanted_terrain_gridded)
        # self.execute(sqltext)


        # sqltext = 'alter table "{0}"."{1}" add column i integer,' \
        #           'alter table "{0}"."{1}" add column j integer,' \
        #           'alter table "{0}"."{1}" add column k integer,' \
        #           'alter table "{0}"."{1}" add column center geometry(pointz, %s)'.format(cfg.domain.case_schema, cfg.tables.slanted_terrain_gridded)
        # self.execute(sqltext, (cfg.srid_palm, ))
        #
        # debug('updating faces centers')
        # sqltext = 'update "{0}"."{1}" set ' \
        #           'center = st_setsrid(st_makepoint(st_x(st_centroid(geom)), st_y(st_centroid(geom)), ' \
        #           '     (coalesce(st_z(st_pointn(st_exteriorring(geom),1)), 0.0) + coalesce(st_z(st_pointn(st_exteriorring(geom),2)), 0.0) + ' \
        #           '      coalesce(st_z(st_pointn(st_exteriorring(geom),3)), 0.0) + coalesce(st_z(st_pointn(st_exteriorring(geom),4)), 0.0) + ' \
        #           '      coalesce(st_z(st_pointn(st_exteriorring(geom),5)), 0.0) + coalesce(st_z(st_pointn(st_exteriorring(geom),6)), 0.0) + ' \
        #           '      coalesce(st_z(st_pointn(st_exteriorring(geom),7)), 0.0)) / st_npoints(geom))' \
        #           '         , %s)'\
        #     .format(cfg.domain.case_schema, cfg.tables.slanted_terrain_gridded)
        # self.execute(sqltext, (cfg.srid_palm, ))
        #
        # debug('calculating face i,j,k')
        # sqltext = 'update "{0}"."{1}" set ' \
        #           'i = floor((st_x(center) - {3}) / {2}) , ' \
        #           'j = floor((st_y(center) - {4}) / {2}), ' \
        #           'k = floor(st_z(center) / {2})' \
        #           ''.format(cfg.domain.case_schema, cfg.tables.slanted_terrain_gridded, cfg.domain.dx,
        #                     cfg.domain.origin_x, cfg.domain.origin_y)
        # self.execute(sqltext)

        if self.cfg.slanted_pars.clean_up:
            self.execute(
                f'alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}" drop column rgid, drop column rijk')

    def create_grid_slanted_roof(self):
        """ processing gridding slanted roof """
        # TODO: Add debug, verbose reports
        progress('processing, gridding slanted roof')

        sqltext = f"""
            drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}";
            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" (
                id integer, 
                rid integer,  
                geom geometry("polygonz", %s), 
                points geometry("multipointz", %s),
                lines geometry("linestringz", %s)
            )
        """
        self.execute(sqltext, (self.cfg.srid_palm,) * 3)

        # create temp table, destroy after cycle
        # find max height -> k_max
        sqltext = f'select max(height) from "{self.cfg.domain.case_schema}"."{self.cfg.tables.height_corrected}" where not dummy_point'
        z_max = self.execute(sqltext)
        z_max = [x for x in z_max[0]]
        k_max = int(np.ceil(max(z_max)) / self.cfg.domain.dz) + 2


        for k in range(1, k_max):
            verbose(f'gridding slanted roof: {k}')
            # create temp table
            sqltext = f'drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded_temp}"'
            self.execute(sqltext)

            sqltext = f"""
                create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded_temp}" as 
                select id, rid, geom3d 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof}"
            """
            self.execute(sqltext)

            sqltext = f"""
                alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded_temp}" 
                add column if not exists npoints integer, 
                add column if not exists z1 double precision, 
                add column if not exists z2 double precision, 
                add column if not exists mezi_dolni boolean default false, 
                add column if not exists mezi_horni boolean default false, 
                add column if not exists p1 geometry(pointz, %s), 
                add column if not exists p2 geometry(pointz, %s)
            """
            self.execute(sqltext, (self.cfg.srid_palm,) * 2)

            for po in range(1, 6):  # 6 points is maximum and the last is repeated
                sqltext = f"""
                    alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded_temp}" 
                    add column if not exists p{po}_mezid geometry(pointz, %s), 
                    add column if not exists p{po}_mezih geometry(pointz, %s), 
                    add column if not exists p{po}_f geometry(pointz, %s)
                """
                self.execute(sqltext, (self.cfg.srid_palm,) * 3)

                sqltext = f"""
                    update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded_temp}" set 
                    p1 = st_pointn(st_exteriorring(geom3d), {po}), 
                    p2 = st_pointn(st_exteriorring(geom3d), {po}+1)
                """
                self.execute(sqltext)

                dz = self.cfg.domain.dz
                k_dz = k * dz
                sqltext = f"""
                    update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded_temp}" set 
                    mezi_dolni = case when st_z(p1) < ({k_dz}-{dz}) and (st_z(p2) > ({k_dz}-{dz})) then true
                                      when st_z(p1) > ({k_dz}-{dz}) and (st_z(p2) < ({k_dz}-{dz})) then true
                                      else false end, 
                    mezi_horni = case when st_z(p1) < {k_dz} and (st_z(p2) > {k_dz}) then true
                                      when st_z(p1) > {k_dz} and (st_z(p2) < {k_dz}) then true 
                                      else false end, 
                    z2 = case when st_z(p2) < ({k_dz}-{dz}) then null
                              when st_z(p2) > {k_dz} then {k_dz}
                              else st_z(p2) end
                """
                self.execute(sqltext)

                sqltext = f"""
                    update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded_temp}" set 
                    p{po}_mezid = case when mezi_dolni then st_setsrid(st_makepoint(
                        st_x(p1) + ({k_dz}-{dz}-st_z(p1))/(st_z(p2)-st_z(p1))*(st_x(p2)-st_x(p1)), 
                        st_y(p1) + ({k_dz}-{dz}-st_z(p1))/(st_z(p2)-st_z(p1))*(st_y(p2)-st_y(p1)), 
                        {k_dz}-{dz}), %s) else null end, 
                    p{po}_mezih = case when mezi_horni then st_setsrid(st_makepoint(
                        st_x(p1) + ({k_dz}-st_z(p1))/(st_z(p2)-st_z(p1))*(st_x(p2)-st_x(p1)), 
                        st_y(p1) + ({k_dz}-st_z(p1))/(st_z(p2)-st_z(p1))*(st_y(p2)-st_y(p1)), 
                        {k_dz}), %s) else null end, 
                    p{po}_f = case when st_z(p2) >= ({k_dz}-{dz}) and st_z(p2) <= {k_dz} 
                              then st_setsrid(st_makepoint(st_x(p2), st_y(p2), z2), %s) else null end
                """
                self.execute(sqltext, (self.cfg.srid_palm,) * 3)

                # set mezi_dolni, mezi_horni to false
                sqltext = f'update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded_temp}" set mezi_dolni = false, mezi_horni = false'
                self.execute(sqltext)

            # gather point to form polygon
            # find number of points
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded_temp}" set 
                npoints = (
                    case when p1_mezid is not null then 1 else 0 end + case when p1_mezih is not null then 1 else 0 end + case when p1_f is not null then 1 else 0 end + 
                    case when p2_mezid is not null then 1 else 0 end + case when p2_mezih is not null then 1 else 0 end + case when p2_f is not null then 1 else 0 end + 
                    case when p3_mezid is not null then 1 else 0 end + case when p3_mezih is not null then 1 else 0 end + case when p3_f is not null then 1 else 0 end + 
                    case when p4_mezid is not null then 1 else 0 end + case when p4_mezih is not null then 1 else 0 end + case when p4_f is not null then 1 else 0 end + 
                    case when p5_mezid is not null then 1 else 0 end + case when p5_mezih is not null then 1 else 0 end + case when p5_f is not null then 1 else 0 end 
                )
            """
            self.execute(sqltext)

            sqltext = f"""
                insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" (id, rid, points)
                select id, rid, st_setsrid(st_collect(array[
                    p1_mezid, p1_mezih, p1_f, p2_mezid, p2_mezih, p2_f, p3_mezid, p3_mezih, p3_f, 
                    p4_mezid, p4_mezih, p4_f, p5_mezid, p5_mezih, p5_f
                ]), %s) as points 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded_temp}" 
                where npoints > 2
            """
            self.execute(sqltext, (self.cfg.srid_palm,))

        sqltext = f'update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" set geom = st_setsrid(st_convexhull(points), %s)'
        self.execute(sqltext, (self.cfg.srid_palm,))


        sqltext = f'update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" set lines = st_setsrid(st_boundary(geom), %s)'
        self.execute(sqltext, (self.cfg.srid_palm,))


        # delete duplicates (dont know where they come from)
        verbose('deleting duplicates')
        sqltext = f'alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" add column if not exists rgid serial'
        self.execute(sqltext)


        sqltext = f"""
            delete from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" 
            where rgid in (
                select rgid from (
                    select rgid, row_number() over (partition by geom order by id) as rownumber 
                    from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}"
                ) as t 
                where t.rownumber > 1
            )
        """
        self.execute(sqltext)


        debug('separate polygon when 3 or more vertices has z = (k+1)*dz or z = k * dz')
        sqltext = f"""
            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" 
            add column if not exists vert1 geometry(pointz, %s), 
            add column if not exists vert2 geometry(pointz, %s), 
            add column if not exists vert3 geometry(pointz, %s), 
            add column if not exists vert4 geometry(pointz, %s), 
            add column if not exists vert5 geometry(pointz, %s), 
            add column if not exists vert6 geometry(pointz, %s), 
            add column if not exists vert7 geometry(pointz, %s), 
            add column if not exists z_max double precision, 
            add column if not exists z_min double precision, 
            add column if not exists k_max integer, 
            add column if not exists n_vert integer
        """
        self.execute(sqltext, (self.cfg.srid_palm,) * 7)


        verbose('create vert points')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" set 
            vert1 = st_pointn(st_boundary(geom), 1), 
            vert2 = st_pointn(st_boundary(geom), 2), 
            vert3 = st_pointn(st_boundary(geom), 3), 
            vert4 = st_pointn(st_boundary(geom), 4), 
            vert5 = st_pointn(st_boundary(geom), 5), 
            vert6 = st_pointn(st_boundary(geom), 6), 
            vert7 = st_pointn(st_boundary(geom), 7)
        """
        self.execute(sqltext)


        verbose('calculate number of points')
        sqltext = f'update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" set n_vert = st_npoints(points)+1'
        self.execute(sqltext)


        # fetch max height
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" set 
            z_max = greatest(
                st_z(st_geometryn(points, 1)), st_z(st_geometryn(points, 2)), st_z(st_geometryn(points, 3)), 
                st_z(st_geometryn(points, 4)), st_z(st_geometryn(points, 5)), st_z(st_geometryn(points, 6)), 
                st_z(st_geometryn(points, 7))
            ),
            z_min = least(
                st_z(st_geometryn(points, 1)), st_z(st_geometryn(points, 2)), st_z(st_geometryn(points, 3)), 
                st_z(st_geometryn(points, 4)), st_z(st_geometryn(points, 5)), st_z(st_geometryn(points, 6)), 
                st_z(st_geometryn(points, 7))
            )
        """
        self.execute(sqltext)


        verbose('selecting polygons')
        verbose('updating all planar-horizontal faces, update their k')
        verbose('fetching max k from slanted faces')
        sqltext = f'select max(z_max) from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}"'
        z_max = self.execute(sqltext)[0][0]

        k_max = int(np.floor(z_max) + 2)
        # kk = 0 check z = k * dz, kk = 1 check z = (k+1) * dz
        for kk in [1]:
            for k in range(0, k_max):
                extra_verbose(f'loop over k: {k}')
                # Need to define dz locally for the query logic
                dz = self.cfg.domain.dz
                k_val = (k + kk) * dz
                sqltext = f"""
                    select id, rgid, rid, n_vert, 
                    array[st_x(vert1), st_y(vert1), st_z(vert1)],  
                    array[st_x(vert2), st_y(vert2), st_z(vert2)], 
                    array[st_x(vert3), st_y(vert3), st_z(vert3)], 
                    array[st_x(vert4), st_y(vert4), st_z(vert4)], 
                    array[st_x(vert5), st_y(vert5), st_z(vert5)], 
                    array[st_x(vert6), st_y(vert6), st_z(vert6)], 
                    array[st_x(vert7), st_y(vert7), st_z(vert7)]  
                    from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" as s 
                    where (case when st_z(vert1) = {k_val} then 1 else 0 end + 
                           case when st_z(vert2) = {k_val} then 1 else 0 end + 
                           case when st_z(vert3) = {k_val} then 1 else 0 end + 
                           case when st_z(vert4) = {k_val} and n_vert > 4 then 1 else 0 end + 
                           case when st_z(vert5) = {k_val} and n_vert > 5 then 1 else 0 end + 
                           case when st_z(vert6) = {k_val} and n_vert > 6 then 1 else 0 end + 
                           case when st_z(vert7) = {k_val} and n_vert > 7 then 1 else 0 end) > 2 
                          and n_vert > 3 and z_min != z_max 
                """
                verts = self.execute(sqltext)

                # TODO: Now here separate this polygon into two. One with 3 or more top points and the rest
                to_insert = []
                to_delete = []
                for vert in verts:
                    p1 = []
                    p2 = []
                    np_verts_p1 = np.empty((7, 3), dtype=object)
                    np_verts_p2 = np.empty((7, 3), dtype=object)
                    id, rgid, rid, n_vert = vert[0], vert[1], vert[2], vert[3]
                    lastidx = 4
                    x_vert, y_vert, z_vert = [], [], []
                    for idx in range(n_vert):
                        if vert[lastidx + idx][0] is not None:
                            x_vert.append(vert[lastidx + idx][0])
                            y_vert.append(vert[lastidx + idx][1])
                            z_vert.append(vert[lastidx + idx][2])
                    x_vert = np.asarray(x_vert)
                    y_vert = np.asarray(y_vert)
                    z_vert = np.asarray(z_vert)
                    to_keep = []
                    tt_max = max(z_vert) if kk == 1 else min(z_vert)
                    for it, ttt in enumerate(z_vert):
                        # print(ttt)
                        if it == 0:
                            ileft = len(z_vert) - 1
                            iright = it + 1
                        elif it == len(z_vert) - 1:
                            iright = 0
                            ileft = it - 1
                        else:
                            iright = it + 1
                            ileft = it - 1
                        if z_vert[ileft] == tt_max and z_vert[it] == tt_max and z_vert[iright] == tt_max:
                            # print('drop this one')
                            p2.append(it)
                        else:
                            if z_vert[it] == tt_max:
                                p1.append(it)
                                p2.append(it)
                            else:
                                p1.append(it)

                    if len(p1) > 2:
                        n_vert1 = len(p1)
                        np_verts_p1[:n_vert1, 0] = x_vert[p1]
                        np_verts_p1[:n_vert1, 1] = y_vert[p1]
                        np_verts_p1[:n_vert1, 2] = z_vert[p1]
                        if not (x_vert[0] == x_vert[n_vert1 - 1] and y_vert[0] == y_vert[n_vert1 - 1] and z_vert[0] ==
                                z_vert[n_vert1 - 1]):
                            n_vert1 = len(p1) + 1
                            np_verts_p1[n_vert1 - 1, :] = np_verts_p1[0, :]

                        to_insert.append((rgid, rid, n_vert1,
                                          np_verts_p1[0, 0], np_verts_p1[0, 1], np_verts_p1[0, 2], self.cfg.srid_palm,
                                          np_verts_p1[1, 0], np_verts_p1[1, 1], np_verts_p1[1, 2], self.cfg.srid_palm,
                                          np_verts_p1[2, 0], np_verts_p1[2, 1], np_verts_p1[2, 2], self.cfg.srid_palm,
                                          np_verts_p1[3, 0], np_verts_p1[3, 1], np_verts_p1[3, 2], self.cfg.srid_palm,
                                          np_verts_p1[4, 0], np_verts_p1[4, 1], np_verts_p1[4, 2], self.cfg.srid_palm,
                                          np_verts_p1[5, 0], np_verts_p1[5, 1], np_verts_p1[5, 2], self.cfg.srid_palm,
                                          np_verts_p1[6, 0], np_verts_p1[6, 1], np_verts_p1[6, 2], self.cfg.srid_palm,
                                          ))
                    if len(p2) > 2:
                        n_vert2 = len(p2) + 1
                        np_verts_p2[:n_vert2 - 1, 0] = x_vert[p2]
                        np_verts_p2[:n_vert2 - 1, 1] = y_vert[p2]
                        np_verts_p2[:n_vert2 - 1, 2] = z_vert[p2]
                        np_verts_p2[n_vert2 - 1, :] = np_verts_p2[0, :]
                        to_insert.append((rgid, rid, n_vert2,
                                          np_verts_p2[0, 0], np_verts_p2[0, 1], np_verts_p2[0, 2], self.cfg.srid_palm,
                                          np_verts_p2[1, 0], np_verts_p2[1, 1], np_verts_p2[1, 2], self.cfg.srid_palm,
                                          np_verts_p2[2, 0], np_verts_p2[2, 1], np_verts_p2[2, 2], self.cfg.srid_palm,
                                          np_verts_p2[3, 0], np_verts_p2[3, 1], np_verts_p2[3, 2], self.cfg.srid_palm,
                                          np_verts_p2[4, 0], np_verts_p2[4, 1], np_verts_p2[4, 2], self.cfg.srid_palm,
                                          np_verts_p2[5, 0], np_verts_p2[5, 1], np_verts_p2[5, 2], self.cfg.srid_palm,
                                          np_verts_p2[6, 0], np_verts_p2[6, 1], np_verts_p2[6, 2], self.cfg.srid_palm,
                                          ))
                    if len(p2) > 2 or len(p1) > 2:
                        to_delete.append((rgid,))

                debug('deleting all unwanted rows')
                # -- optmize here
                sqltext = f'delete from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" where rgid = any(%s)'
                self.execute(sqltext, (to_delete,))

                debug('inserting all new entries into slanted faces table')
                sqltext = f"""
                    insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" (id, rgid, rid, n_vert, 
                                             vert1, vert2, vert3, vert4, vert5, vert6, vert7) 
                    values                  (null, %s, %s, %s, 
                                            st_setsrid(st_makepoint(%s, %s, %s), %s), 
                                            st_setsrid(st_makepoint(%s, %s, %s), %s), 
                                            st_setsrid(st_makepoint(%s, %s, %s), %s), 
                                            st_setsrid(st_makepoint(%s, %s, %s), %s), 
                                            st_setsrid(st_makepoint(%s, %s, %s), %s), 
                                            st_setsrid(st_makepoint(%s, %s, %s), %s), 
                                            st_setsrid(st_makepoint(%s, %s, %s), %s) 
                                            )  
                """
                self.executemany(sqltext, to_insert)

                # create polygon
                debug('updating 3d polygon')
                sqltext = f"""
                    update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" set geom =  
                    st_forcerhr(
                    st_setsrid(st_makepolygon(st_makeline(array[vert1, vert2, vert3, vert4, vert5, vert6, vert7,
                         case when vert1 is not null then vert1 
                              when vert2 is not null then vert2 
                              when vert3 is not null then vert3 
                              when vert4 is not null then vert4 
                              when vert5 is not null then vert5 
                              when vert6 is not null then vert6 
                              when vert7 is not null then vert7 end
                    ])), %s)) 
                    where geom is null
                """
                self.execute(sqltext, (self.cfg.srid_palm,))

        # TODO: create new serial index
        sqltext = f"""
            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" drop column if exists id; 
            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" add column id serial
        """
        self.execute(sqltext)


        sqltext = f'alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" add primary key (id)'
        self.execute(sqltext)


        if self.cfg.slanted_pars.clean_up:
            sqltext = f'alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}" drop column rgid'
            self.execute(sqltext)

    def merge_walls_terrain(self):
        """ merging roof edges with walls """
        progress('merging grid faces of terrain and walls')

        debug('finding duplicates')
        # find all aggregated faces, create new table with aggregated ones
        sqltext = f"""
            select i, j, k from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" 
            where not isroof 
            group by i, j, k 
            having count(*)>1 
            order by i, j, k
        """
        duplicits = self.execute(sqltext)
        # sql_debug(self.connection)
        # self.connection.commit()

        i_all = [x[0] for x in duplicits]
        j_all = [x[1] for x in duplicits]
        k_all = [x[2] for x in duplicits]

        # build dynamic filter condition
        sqltext_ijk = ' or '.join([f'(i = {i} and j = {j} and k = {k})' for i, j, k in zip(i_all, j_all, k_all)])

        # select all wid
        debug('finding all wids')
        sqltext = f'select wid from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" where iswall and ({sqltext_ijk}) order by i, j, k'
        wid = self.execute(sqltext)
        # sql_debug(self.connection)
        # self.connection.commit()

        if len(i_all) != len(wid):
            error('number of items in i_all is not the same as in wid')
            sys.exit(1)

        # get all wall coordinates
        debug('selecting all wall coordinates')
        sqltext = f"""
            select 
            array[st_x(vert1), st_y(vert1), st_z(vert1)],  
            array[st_x(vert2), st_y(vert2), st_z(vert2)], 
            array[st_x(vert3), st_y(vert3), st_z(vert3)], 
            array[st_x(vert4), st_y(vert4), st_z(vert4)], 
            array[st_x(vert5), st_y(vert5), st_z(vert5)], 
            array[st_x(vert6), st_y(vert6), st_z(vert6)], 
            array[st_x(vert7), st_y(vert7), st_z(vert7)] 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" 
            where {sqltext_ijk} and iswall 
            order by i, j, k
        """
        wall_coord = self.execute(sqltext)
        # sql_debug(self.connection)
        # self.connection.commit()

        # transform into numpy array
        verbose('transforming coordinates into numpy array')
        wall_coord_np = np.zeros((len(wall_coord), 7, 3), dtype=object)
        wall_vert = np.zeros(len(wall_coord), dtype='int')
        for idx, coord in enumerate(wall_coord):
            wall_vert[idx] = len([wc[0] for wc in wall_coord[idx] if wc[0] is not None]) - 1
            wall_coord_np[idx, 0, :] = wall_coord[idx][0]
            wall_coord_np[idx, 1, :] = wall_coord[idx][1]
            wall_coord_np[idx, 2, :] = wall_coord[idx][2]
            if wall_vert[idx] >= 3:
                wall_coord_np[idx, 3, :] = wall_coord[idx][3]
            if wall_vert[idx] >= 4:
                wall_coord_np[idx, 4, :] = wall_coord[idx][4]
            if wall_vert[idx] >= 5:
                wall_coord_np[idx, 5, :] = wall_coord[idx][5]
            if wall_vert[idx] >= 6:
                wall_coord_np[idx, 6, :] = wall_coord[idx][6]

        # get all terrain coordinates
        debug('selecting all terrain coordinates')
        sqltext = f"""
            select 
            array[st_x(vert1), st_y(vert1), st_z(vert1)],  
            array[st_x(vert2), st_y(vert2), st_z(vert2)], 
            array[st_x(vert3), st_y(vert3), st_z(vert3)], 
            array[st_x(vert4), st_y(vert4), st_z(vert4)], 
            array[st_x(vert5), st_y(vert5), st_z(vert5)], 
            array[st_x(vert6), st_y(vert6), st_z(vert6)], 
            array[st_x(vert7), st_y(vert7), st_z(vert7)] 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" 
            where {sqltext_ijk} and isterr 
            order by i, j, k
        """
        terr_coord = self.execute(sqltext)
        # sql_debug(self.connection)
        # self.connection.commit()

        # transform into numpy array
        verbose('transforming into numpy array')
        terr_coord_np = np.zeros((len(terr_coord), 7, 3), dtype=object)
        terr_vert = np.zeros(len(terr_coord), dtype='int')
        for idx, coord in enumerate(terr_coord):
            terr_vert[idx] = len([wc[0] for wc in terr_coord[idx] if wc[0] is not None]) - 1
            terr_coord_np[idx, 0, :] = terr_coord[idx][0]
            terr_coord_np[idx, 1, :] = terr_coord[idx][1]
            terr_coord_np[idx, 2, :] = terr_coord[idx][2]
            if terr_vert[idx] >= 3:
                terr_coord_np[idx, 3, :] = terr_coord[idx][3]
            if terr_vert[idx] >= 4:
                terr_coord_np[idx, 4, :] = terr_coord[idx][4]
            if terr_vert[idx] >= 5:
                terr_coord_np[idx, 5, :] = terr_coord[idx][5]
            if terr_vert[idx] >= 6:
                terr_coord_np[idx, 6, :] = terr_coord[idx][6]

        del terr_coord
        del wall_coord

        # join them and find correct coordinates
        debug('merging duplicates')
        vert_final = []
        for idx, i in enumerate(i_all):
            v_f = self.merge_local_wall_terrain(i_all[idx], j_all[idx], k_all[idx],
                                           wall_coord_np[idx], terr_coord_np[idx],
                                           wall_vert[idx], terr_vert[idx])
            vert_final.append(v_f)

        # collect all into tuple
        debug('final collecting of new vertices into one tuple')
        to_insert = []
        for idx, verts in enumerate(vert_final):
            to_insert.append((i_all[idx], j_all[idx], k_all[idx], wid[idx],
                              verts[0, 0], verts[0, 1], verts[0, 2], self.cfg.srid_palm,
                              verts[1, 0], verts[1, 1], verts[1, 2], self.cfg.srid_palm,
                              verts[2, 0], verts[2, 1], verts[2, 2], self.cfg.srid_palm,
                              verts[3, 0], verts[3, 1], verts[3, 2], self.cfg.srid_palm,
                              verts[4, 0], verts[4, 1], verts[4, 2], self.cfg.srid_palm,
                              verts[5, 0], verts[5, 1], verts[5, 2], self.cfg.srid_palm,
                              verts[6, 0], verts[6, 1], verts[6, 2], self.cfg.srid_palm,)
                             )

        # delete original faces
        debug('deleting original faces')
        sqltext = f'delete from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" where {sqltext_ijk}'
        self.execute(sqltext)
        # sql_debug(self.connection)
        # self.connection.commit()

        # insert all new entries
        debug('inserting all new entries into slanted faces table')
        sqltext = f"""
            insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" 
            (i, j, k, wid, iswall, vert1, vert2, vert3, vert4, vert5, vert6, vert7) 
            values (%s, %s, %s, %s, true, 
                    st_setsrid(st_makepoint(%s, %s, %s), %s), 
                    st_setsrid(st_makepoint(%s, %s, %s), %s), 
                    st_setsrid(st_makepoint(%s, %s, %s), %s), 
                    st_setsrid(st_makepoint(%s, %s, %s), %s), 
                    st_setsrid(st_makepoint(%s, %s, %s), %s), 
                    st_setsrid(st_makepoint(%s, %s, %s), %s), 
                    st_setsrid(st_makepoint(%s, %s, %s), %s))
        """
        self.self.executemany(sqltext, to_insert)
        # sql_debug(self.connection)
        # self.connection.commit()

        # create polygon
        debug('updating 3d polygon')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set geom =  
            st_forcerhr(
                st_setsrid(st_makepolygon(st_makeline(array[vert1, vert2, vert3, vert4, vert5, vert6, vert7,
                     case when vert1 is not null then vert1 
                          when vert2 is not null then vert2 
                          when vert3 is not null then vert3 
                          when vert4 is not null then vert4 
                          when vert5 is not null then vert5 
                          when vert6 is not null then vert6 
                          when vert7 is not null then vert7 end
                ])), %s)) 
            where geom is null
        """
        self.execute(sqltext, (self.cfg.srid_palm,))
        # sql_debug(self.connection)
        # self.connection.commit()

        debug('reupdate vertices')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set 
            vert1 = st_pointn(st_boundary(geom), 1), 
            vert2 = st_pointn(st_boundary(geom), 2), 
            vert3 = st_pointn(st_boundary(geom), 3), 
            vert4 = st_pointn(st_boundary(geom), 4), 
            vert5 = st_pointn(st_boundary(geom), 5), 
            vert6 = st_pointn(st_boundary(geom), 6), 
            vert7 = st_pointn(st_boundary(geom), 7)
        """
        self.execute(sqltext)
        # sql_debug(self.connection)
        # self.connection.commit()

        debug('update center of faces, just in case')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set center = 
            st_setsrid(st_makepoint(st_x(st_centroid(geom)), st_y(st_centroid(geom)), 
                                   (st_z(vert1) + st_z(vert2) + 
                                      case when st_npoints(geom) > 3 then st_z(st_pointn(st_exteriorring(geom),3)) else 0.0 end + 
                                      case when st_npoints(geom) > 4 then st_z(st_pointn(st_exteriorring(geom),4)) else 0.0 end + 
                                      case when st_npoints(geom) > 5 then st_z(st_pointn(st_exteriorring(geom),5)) else 0.0 end + 
                                      case when st_npoints(geom) > 6 then st_z(st_pointn(st_exteriorring(geom),6)) else 0.0 end) / (st_npoints(geom)-1))
                     , %s) 
            where center is null
        """
        self.execute(sqltext, (self.cfg.srid_palm,))
        # sql_debug(self.connection)
        # self.connection.commit()

        ### old one
        # sqltext = f"""
        #     select i, j, k from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}"
        #     where isterr or iswall
        #     group by i, j, k
        #     having count(*)>1
        # """
        # self.execute(sqltext)
        # duplicits = self.fetchall()
        # # sql_debug(self.connection)
        # # self.connection.commit()
        #
        # debug('processing duplicates')
        # for i, j, k in duplicits:
        #     verbose(f'\tnow processing duplicate [k,j,i] = [{k},{j},{i}]')
        #     sqltext = f"""
        #         select wid from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}"
        #         where i = {i} and j = {j} and k = {k} and iswall
        #     """
        #     self.execute(sqltext)
        #     wid = self.fetchone()
        #     # sql_debug(self.connection)
        #     # self.connection.commit()
        #
        #     sqltext = f"""
        #         select
        #         array[st_x(vert1), st_y(vert1), st_z(vert1)],
        #         array[st_x(vert2), st_y(vert2), st_z(vert2)],
        #         array[st_x(vert3), st_y(vert3), st_z(vert3)],
        #         array[st_x(vert4), st_y(vert4), st_z(vert4)],
        #         array[st_x(vert5), st_y(vert5), st_z(vert5)],
        #         array[st_x(vert6), st_y(vert6), st_z(vert6)],
        #         array[st_x(vert7), st_y(vert7), st_z(vert7)]
        #         from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}"
        #         where i = {i} and j = {j} and k = {k} and iswall
        #     """
        #     self.execute(sqltext)
        #     wall_coord = list(self.fetchall()[0])
        #     wall_coord1 = [wall_c for wall_c in wall_coord if wall_c[0] is not None]
        #     wall_coord = np.asarray(wall_coord1[:-1])
        #     # sql_debug(self.connection)
        #     # self.connection.commit()
        #
        #     sqltext = f"""
        #         select
        #         array[st_x(vert1), st_y(vert1), st_z(vert1)],
        #         array[st_x(vert2), st_y(vert2), st_z(vert2)],
        #         array[st_x(vert3), st_y(vert3), st_z(vert3)],
        #         array[st_x(vert4), st_y(vert4), st_z(vert4)],
        #         array[st_x(vert5), st_y(vert5), st_z(vert5)],
        #         array[st_x(vert6), st_y(vert6), st_z(vert6)],
        #         array[st_x(vert7), st_y(vert7), st_z(vert7)]
        #         from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}"
        #         where i = {i} and j = {j} and k = {k} and isterr
        #     """
        #     self.execute(sqltext)
        #     terr_coord = list(self.fetchall()[0])
        #     terr_coord1 = [terr_c for terr_c in terr_coord if terr_c[0] is not None]
        #     terr_coord = np.asarray(terr_coord1[:-1])
        #     # sql_debug(self.connection)
        #     # self.connection.commit()
        #
        #     # remove original faces
        #     verbose('\tdeleting original faces')
        #     sqltext = f'delete from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" where i = {i} and j = {j} and k = {k}'
        #     self.execute(sqltext)
        #     # sql_debug(self.connection)
        #     # self.connection.commit()
        #
        #     # find which terrain points are wall point and find appropriate ones
        #     # only top ones
        #     wall_coord_t = wall_coord[wall_coord[:, 2] >= np.max(wall_coord[:, 2])]
        #     trtw = []
        #     tr_new = []
        #     for tri, tr in enumerate(terr_coord):
        #         tr_new.append(tr)
        #         trtw0 = [tri, -1, False]
        #         found = False
        #         for twi, tw in enumerate(wall_coord_t):
        #             if tw[0] == tr[0] and tw[1] == tr[1]:
        #                 trtw0 = [tri, twi, True]
        #                 trtw.append(trtw0)
        #                 if tw[2] > tr[2]:
        #                     trtw.append(trtw0)
        #                     tr_new.append(tw)
        #                 found = True
        #                 break
        #         if not found:
        #             trtw.append(trtw0)
        #
        #     tr_new.append(tr_new[0])
        #     vertices = np.asarray(tr_new)
        #
        #     n_vert = vertices.shape[0]
        #     cent = np.mean(vertices, 0)
        #
        #     svd = np.linalg.svd(vertices.T - np.mean(vertices.T, axis=1, keepdims=True))
        #     left = svd[0]
        #     n = left[:, -1] / np.linalg.norm(left[:, -1])
        #
        #     vi = 0
        #     vj = 1
        #     A = cent - vertices[vi, :]
        #     q = np.cross(A, n)
        #
        #     angle = np.zeros(n_vert)
        #     for ir in range(n_vert):
        #         r = cent - vertices[ir, :]
        #         t = np.dot(n, np.cross(r, A))
        #         u = np.dot(n, np.cross(r, q))
        #         angle[ir] = np.arctan2(u, t) / np.pi * 180
        #         angle[ir] = angle[ir] if angle[ir] > 0 else 360.0 + angle[ir]
        #
        #     order = angle.argsort()
        #     order_all = np.append(order, np.arange(n_vert, 7))
        #
        #     vert_order = np.zeros((8, 3), dtype=object)
        #     vert_order[:] = None
        #     vert_order[:n_vert] = vertices[order]
        #
        #     verbose('\tinserting new merged face')
        #     sqltext = f"""
        #         insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}"
        #         (i, j, k, wid, iswall, isroof, isterr, vert1, vert2, vert3, vert4, vert5, vert6, vert7)
        #         select {i}, {j}, {k}, {wid}, true, false, false,
        #         st_setsrid(st_makepoint(%s,%s,%s), %s),
        #         st_setsrid(st_makepoint(%s,%s,%s), %s),
        #         st_setsrid(st_makepoint(%s,%s,%s), %s),
        #         st_setsrid(st_makepoint(%s,%s,%s), %s),
        #         st_setsrid(st_makepoint(%s,%s,%s), %s),
        #         st_setsrid(st_makepoint(%s,%s,%s), %s),
        #         st_setsrid(st_makepoint(%s,%s,%s), %s)
        #     """
        #     # Note: *order_all + 1 logic needs careful handling if executed directly
        #     self.execute(sqltext, (vert_order[0,0], vert_order[0,1], vert_order[0,2], self.cfg.srid_palm,
        #                           vert_order[1,0], vert_order[1,1], vert_order[1,2], self.cfg.srid_palm,
        #                           vert_order[2,0], vert_order[2,1], vert_order[2,2], self.cfg.srid_palm,
        #                           vert_order[3,0], vert_order[3,1], vert_order[3,2], self.cfg.srid_palm,
        #                           vert_order[4,0], vert_order[4,1], vert_order[4,2], self.cfg.srid_palm,
        #                           vert_order[5,0], vert_order[5,1], vert_order[5,2], self.cfg.srid_palm,
        #                           vert_order[6,0], vert_order[6,1], vert_order[6,2], self.cfg.srid_palm,))
        #     # sql_debug(self.connection)
        #     # self.connection.commit()
        #
        #     verbose('update 3d polygon')
        #     sqltext = f"""
        #         update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set geom =
        #         st_forcerhr(
        #         st_setsrid(st_makepolygon(st_makeline(array[vert1, vert2, vert3, vert4, vert5, vert6, vert7,
        #              case when vert1 is not null then vert1
        #                   when vert2 is not null then vert2
        #                   when vert3 is not null then vert3
        #                   when vert4 is not null then vert4
        #                   when vert5 is not null then vert5
        #                   when vert6 is not null then vert6
        #                   when vert7 is not null then vert7 end
        #         ])), %s))
        #         where i = {i} and j = {j} and k = {k}
        #     """
        #     self.execute(sqltext, (self.cfg.srid_palm,))
        #     # sql_debug(self.connection)
        #     # self.connection.commit()
        #
        #     sqltext = f"""
        #         update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set
        #         vert1 = st_pointn(st_boundary(geom), 1),
        #         vert2 = st_pointn(st_boundary(geom), 2),
        #         vert3 = st_pointn(st_boundary(geom), 3),
        #         vert4 = st_pointn(st_boundary(geom), 4),
        #         vert5 = st_pointn(st_boundary(geom), 5),
        #         vert6 = st_pointn(st_boundary(geom), 6),
        #         vert7 = st_pointn(st_boundary(geom), 7)
        #     """
        #     self.execute(sqltext)
        #     # sql_debug(self.connection)
        #     # self.connection.commit()
        #
        #     sqltext = f"""
        #         update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set center =
        #         st_setsrid(st_makepoint(st_x(st_centroid(geom)), st_y(st_centroid(geom)),
        #              (coalesce(st_z(st_pointn(st_exteriorring(geom),1)), 0.0) + coalesce(st_z(st_pointn(st_exteriorring(geom),2)), 0.0) +
        #               coalesce(st_z(st_pointn(st_exteriorring(geom),3)), 0.0) + coalesce(st_z(st_pointn(st_exteriorring(geom),4)), 0.0) +
        #               coalesce(st_z(st_pointn(st_exteriorring(geom),5)), 0.0) + coalesce(st_z(st_pointn(st_exteriorring(geom),6)), 0.0) +
        #               coalesce(st_z(st_pointn(st_exteriorring(geom),7)), 0.0)) / st_npoints(geom))
        #              , %s)
        #         where i = {i} and j = {j} and k = {k}
        #     """
        #     self.execute(sqltext, (self.cfg.srid_palm,))
        #     # sql_debug(self.connection)
        #     # self.connection.commit()

    def normal_vector_triangle(self, p1, p2, p3):
        N = np.cross(p2 - p1, p3 - p1)
        return N[::-1] / np.sqrt(np.sum(N ** 2))

    def merge_walls_roofs(self):
        """ Function that merge wall and roof occupying same grid box"""
        progress('Merging grid faces of walls and roofs')
        # find all aggregated faces, create new table with aggregated ones
        debug('Finding duplicates')
        sqltext = f"""
            select i, j, k from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" 
            where not isterr 
            group by i, j, k 
            having count(*)>1 
            order by i, j, k
        """
        duplicits = self.execute(sqltext)
        i_all = [x[0] for x in duplicits]
        j_all = [x[1] for x in duplicits]
        k_all = [x[2] for x in duplicits]

        if len(i_all) == 0:
            return 1

        # SELECT ALL rid
        debug('Finding all rids')
        sqltext_ijk = ' or '.join([f'(i = {i} and j = {j} and k = {k})' for i, j, k in zip(i_all, j_all, k_all)])
        sqltext = f'select rid from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" where isroof and ({sqltext_ijk}) order by i, j, k'
        rid = self.execute(sqltext)

        # SELECT ALL Vertices
        debug('Selecting all coordinates')
        sqltext = f"""
            select count(*), array_agg(st_x(points)), array_agg(st_y(points)), array_agg(st_z(points)), i, j, k 
            from (select points, i, j, k
                  from (select (st_dumppoints(geom)).geom as points, i, j, k from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" 
                        where not isterr and {sqltext_ijk}) as s 
                  group by points, i, j, k ) as ss 
            group by i, j, k 
            order by i, j, k
        """
        verts = self.execute(sqltext)

        verbose('Creating counts')
        count = [x[0] for x in verts]

        # check if count > 8
        if max(count) > 7:
            warning('Some error in merging')
            for ic in range(len(count)):
                if count[ic] > 7:
                    warning(f'\tproblematic [i,j,k, idx], [{i_all[ic]}, {j_all[ic]}, {k_all[ic]}, {ic}]')

            error('No go for merging')
            exit(1)

        verbose('Creating x verts')
        x_vert = [x[1] for x in verts]
        x_vert_np = np.empty((len(count), 7), dtype=object)
        for i, j in enumerate(x_vert):
            x_vert_np[i][0:len(j)] = j
        del x_vert

        verbose('Creating y verts')
        y_vert = [x[2] for x in verts]
        y_vert_np = np.empty((len(count), 7), dtype=object)
        for i, j in enumerate(y_vert):
            y_vert_np[i][0:len(j)] = j
        del y_vert

        verbose('Creating z verts')
        z_vert = [x[3] for x in verts]
        z_vert_np = np.empty((len(count), 7), dtype=object)
        for i, j in enumerate(z_vert):
            z_vert_np[i][0:len(j)] = j
        del z_vert

        verbose('Deleting verts')
        del verts

        debug('Delete the ones that does not lie at grid lines')
        x_vert_np_n, y_vert_np_n, z_vert_np_n = np.empty((len(count), 7), dtype=object), np.empty((len(count), 7),
                                                                                                  dtype=object), np.empty(
            (len(count), 7), dtype=object)
        for i in range(len(count)):
            q = 0
            for j in range(count[i]):
                xdist = np.abs(
                    (x_vert_np[i, j] - self.cfg.domain.origin_x) / self.cfg.domain.dx
                    - np.round((x_vert_np[i, j] - self.cfg.domain.origin_x) / self.cfg.domain.dx))

                ydist = np.abs(
                    (y_vert_np[i, j] - self.cfg.domain.origin_y) / self.cfg.domain.dy
                    - np.round((y_vert_np[i, j] - self.cfg.domain.origin_y) / self.cfg.domain.dy))
                if xdist > 1e-10 and ydist > 1e-10:
                    pass
                else:
                    x_vert_np_n[i, q] = x_vert_np[i, j]
                    y_vert_np_n[i, q] = y_vert_np[i, j]
                    z_vert_np_n[i, q] = z_vert_np[i, j]
                    q += 1
            count[i] = q

        x_vert_np, y_vert_np, z_vert_np = x_vert_np_n, y_vert_np_n, z_vert_np_n

        debug('Merging all coordinates into final form')
        order_all = []
        for idx, c in enumerate(count):
            # extra_verbose('Merging i,j,k, x coords, y coords, z coords, count, {}, {}, {}, {}, {}, {}, {}',
            #               i_all[idx], j_all[idx], k_all[idx],
            #               x_vert_np[idx], y_vert_np[idx], y_vert_np[idx], count[idx])
            or_all = self.merge_local_wall_roof(i_all[idx], j_all[idx], k_all[idx], x_vert_np[idx], y_vert_np[idx],
                                           z_vert_np[idx], count[idx], self.cfg)
            order_all.append(or_all)
        order_all = np.asarray(order_all)

        # COLLECT ALL INTO TUPLE
        debug('Final collecting of new vertices into one tuple')
        to_insert = []
        for idx, order in enumerate(order_all):
            to_insert.append((i_all[idx], j_all[idx], k_all[idx], rid[idx],
                              x_vert_np[idx, order[0]], y_vert_np[idx, order[0]], z_vert_np[idx, order[0]],
                              self.cfg.srid_palm,
                              x_vert_np[idx, order[1]], y_vert_np[idx, order[1]], z_vert_np[idx, order[1]],
                              self.cfg.srid_palm,
                              x_vert_np[idx, order[2]], y_vert_np[idx, order[2]], z_vert_np[idx, order[2]],
                              self.cfg.srid_palm,
                              x_vert_np[idx, order[3]], y_vert_np[idx, order[3]], z_vert_np[idx, order[3]],
                              self.cfg.srid_palm,
                              x_vert_np[idx, order[4]], y_vert_np[idx, order[4]], z_vert_np[idx, order[4]],
                              self.cfg.srid_palm,
                              x_vert_np[idx, order[5]], y_vert_np[idx, order[5]], z_vert_np[idx, order[5]],
                              self.cfg.srid_palm,
                              x_vert_np[idx, order[6]], y_vert_np[idx, order[6]], z_vert_np[idx, order[6]],
                              self.cfg.srid_palm,)
                             )
            # print(to_insert[idx])

        # DELETE previous entry
        debug('Deleting original faces')
        sqltext = f'delete from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" where {sqltext_ijk}'
        self.execute(sqltext)

        # INSERT ALL NEW ENTRIES
        debug('Inserting all new entries into slanted faces table')
        sqltext = f"""
            insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" 
            (i, j, k, rid, isroof, vert1, vert2, vert3, vert4, vert5, vert6, vert7) 
            values (%s, %s, %s, %s, true, 
                    st_setsrid(st_makepoint(%s, %s, %s), %s), 
                    st_setsrid(st_makepoint(%s, %s, %s), %s), 
                    st_setsrid(st_makepoint(%s, %s, %s), %s), 
                    st_setsrid(st_makepoint(%s, %s, %s), %s), 
                    st_setsrid(st_makepoint(%s, %s, %s), %s), 
                    st_setsrid(st_makepoint(%s, %s, %s), %s), 
                    st_setsrid(st_makepoint(%s, %s, %s), %s) 
                    )
        """

        self.executemany(sqltext, to_insert)

        # Create polygon
        debug('Updating 3d polygon')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set geom =  
            st_forcerhr(
                st_setsrid(st_makepolygon(st_makeline(array[vert1, vert2, vert3, vert4, vert5, vert6, vert7,
                     case when vert1 is not null then vert1 
                          when vert2 is not null then vert2 
                          when vert3 is not null then vert3 
                          when vert4 is not null then vert4 
                          when vert5 is not null then vert5 
                          when vert6 is not null then vert6 
                          when vert7 is not null then vert7 end
                ])), %s)) 
            where geom is null
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        debug('Reupdate vertices')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set 
            vert1 = st_pointn(st_boundary(geom), 1), 
            vert2 = st_pointn(st_boundary(geom), 2), 
            vert3 = st_pointn(st_boundary(geom), 3), 
            vert4 = st_pointn(st_boundary(geom), 4), 
            vert5 = st_pointn(st_boundary(geom), 5), 
            vert6 = st_pointn(st_boundary(geom), 6), 
            vert7 = st_pointn(st_boundary(geom), 7)
        """
        self.execute(sqltext)

        debug('Update center of faces, just in case')
        debug('Updating center')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set center = 
            st_setsrid(st_makepoint(st_x(st_centroid(geom)), st_y(st_centroid(geom)), 
                                   (st_z(vert1) + st_z(vert2) + 
                                      case when st_npoints(geom) > 3 then st_z(st_pointn(st_exteriorring(geom),3)) else 0.0 end + 
                                      case when st_npoints(geom) > 4 then st_z(st_pointn(st_exteriorring(geom),4)) else 0.0 end + 
                                      case when st_npoints(geom) > 5 then st_z(st_pointn(st_exteriorring(geom),5)) else 0.0 end + 
                                      case when st_npoints(geom) > 6 then st_z(st_pointn(st_exteriorring(geom),6)) else 0.0 end) / (st_npoints(geom) - 1))
                     , %s) 
            where center is null
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        sqltext = f"""
            with ijk as (select i,j,k 
                         from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}"  
                         where isterr 
                         group by i,j,k 
                         having count(*) = 2 
                         order by i,j,k ) 
            select st_z(center), id, s.i, s.j, s.k  
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" as s 
            right join ijk on ijk.i = s.i and ijk.j = s.j and ijk.k = s.k 
            where isterr 
            order by s.i, s.j, s.k
        """
        zijk = self.execute(sqltext)

        id2del = []
        for ijk in range(0, len(zijk), 2):
            z1, z2 = zijk[ijk][0], zijk[ijk + 1][0]
            id1, id2 = zijk[ijk][1], zijk[ijk + 1][1]
            id2del.append((id1 if z1 < z2 else id2,))

        debug('Deleting all unwanted rows')
        # -- OPTIMIZE HERE
        sqltext = f'delete from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" where id = any(%s)'
        self.execute(sqltext, (id2del,))

        #
        # for i, j, k in duplicits:
        #     verbose('Processing [i,j,k] = [{},{},{}]', i,j,k)
        #     sqltext = 'SELECT rid FROM "{0}"."{1}" ' \
        #               'WHERE i = {2} AND j = {3} AND k = {4} AND isroof'\
        #               .format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces, i, j, k)
        #     self.execute(sqltext)
        #     rid = self.fetchone()
        #
        #     # delete old one and create new one
        #     sqltext = 'SELECT ST_Collect(ARRAY_AGG(points)) ' \
        #               '     FROM (' \
        #               '           SELECT points FROM ( ' \
        #               '                               SELECT i, j, k, iswall, (ST_DumpPoints(geom)).geom AS points ' \
        #               '                               FROM "{0}"."{1}"' \
        #               '                               WHERE i = {2} AND j = {3} AND k = {4}) AS s ' \
        #               '     GROUP BY points) AS ss'.format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces, i, j, k)
        #     self.execute(sqltext, (self.cfg.srid_palm, ))
        #     polygon = self.fetchone()
        #
        #     sqltext = 'DELETE FROM "{0}"."{1}" ' \
        #               'WHERE i = {2} AND j = {3} AND k = {4}'.format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces, i, j, k)
        #     self.execute(sqltext)
        #
        #     # reorder the data to form polygon
        #     sqltext = 'SELECT ST_X(ST_GeometryN(%s,1)), ST_X(ST_GeometryN(%s,2)), ST_X(ST_GeometryN(%s,3)), ' \
        #               '       ST_X(ST_GeometryN(%s,4)), ST_X(ST_GeometryN(%s,5)), ST_X(ST_GeometryN(%s,6)),' \
        #               '       ST_X(ST_GeometryN(%s,7)) '. \
        #               format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
        #     self.execute(sqltext, (polygon, polygon, polygon, polygon, polygon, polygon, polygon, ))
        #     x_vert = self.fetchall()
        #
        #     sqltext = 'SELECT ST_Y(ST_GeometryN(%s,1)), ST_Y(ST_GeometryN(%s,2)), ST_Y(ST_GeometryN(%s,3)), ' \
        #               '       ST_Y(ST_GeometryN(%s,4)), ST_Y(ST_GeometryN(%s,5)), ST_Y(ST_GeometryN(%s,6)),' \
        #               '       ST_Y(ST_GeometryN(%s,7)) '. \
        #               format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
        #     self.execute(sqltext, (polygon, polygon, polygon, polygon, polygon, polygon, polygon, ))
        #     y_vert = self.fetchall()
        #
        #     sqltext = 'SELECT ST_Z(ST_GeometryN(%s,1)), ST_Z(ST_GeometryN(%s,2)), ST_Z(ST_GeometryN(%s,3)), ' \
        #               '       ST_Z(ST_GeometryN(%s,4)), ST_Z(ST_GeometryN(%s,5)), ST_Z(ST_GeometryN(%s,6)),' \
        #               '       ST_Z(ST_GeometryN(%s,7)) '. \
        #               format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
        #     self.execute(sqltext, (polygon, polygon, polygon, polygon, polygon, polygon, polygon, ))
        #     z_vert = self.fetchall()
        #
        #     x_vert = np.asarray([np.nan if x is None else x for x in x_vert[0]])
        #     y_vert = np.asarray([np.nan if x is None else x for x in y_vert[0]])
        #     z_vert = np.asarray([np.nan if x is None else x for x in z_vert[0]])
        #
        #     n_vert = np.sum(~np.isnan(x_vert))
        #
        #     vertices = np.zeros((n_vert,3))
        #     vertices[:, 0] = x_vert[:n_vert]
        #     vertices[:, 1] = y_vert[:n_vert]
        #     vertices[:, 2] = z_vert[:n_vert]
        #
        #
        #     cent = np.mean(vertices,0)
        #
        #     # calculate normal vector of some triangles
        #     vi = 0
        #     vj = 1
        #     A = cent - vertices[vi, :]
        #     B = cent - vertices[vj, :]
        #     # n = np.array([A[1] * B[2] - A[2] * B[1], A[2] * B[0] - A[0] * B[2], A[0] * B[1] - A[1] * B[0]])
        #     #
        #
        #     # b = vertices[:,2].T
        #     # Ab = np.concatenate((vertices[:,:2], np.ones((1,n_vert)).T),axis=1)
        #     # Ab[:, 0] = Ab[:, 0] # - self.cfg.domain.origin_x
        #     # Ab[:, 1] = Ab[:, 1] #- self.cfg.domain.origin_y
        #     # fit, residual, rnk, s = lstsq(Ab, b)
        #     # n = fit / norm(fit)
        #
        #     svd = np.linalg.svd(vertices.T - np.mean(vertices.T , axis=1, keepdims=True))
        #     left = svd[0]
        #     left[:, -1]
        #
        #     n = left[:, -1] / norm(left[:, -1])
        #
        #     q = np.cross(A, n)
        #
        #     angle = np.zeros(n_vert)
        #     for ir in range(n_vert):
        #         r = cent - vertices[ir, :]
        #         t = np.dot(n, np.cross(r, A))
        #         u = np.dot(n, np.cross(r, q))
        #         angle[ir] = np.arctan2(u, t) / np.pi * 180
        #         angle[ir] = angle[ir] if angle[ir] > 0 else 360.0 + angle[ir]
        #
        #     order = angle.argsort()
        #     order_all = np.append(order, np.arange(n_vert, 7))
        #     #
        #     # fig = plt.figure()
        #     # from mpl_toolkits import mplot3d
        #     # ax = plt.axes(projection='3d')
        #     # plt.title('i,j,k: {},{},{}'.format(i, j, k))
        #     # ax.plot3D(vertices[:, 0], vertices[:, 1], vertices[:, 2], 'o')
        #     # ax.plot3D([cent[0], cent[0] + n[0]], [cent[1], cent[1] + n[1]], [cent[2], cent[2] + n[2]], 'k-')
        #     # ax.plot3D([cent[0], cent[0] + q[0]], [cent[1], cent[1] + q[1]], [cent[2], cent[2] + q[2]], 'k:')
        #     # ax.plot3D([cent[0], cent[0] + A[0]], [cent[1], cent[1] + A[1]], [cent[2], cent[2] + A[2]], 'k--')
        #     # ax.plot3D(vertices[np.append(order, order[0]), 0],
        #     #           vertices[np.append(order, order[0]), 1],
        #     #           vertices[np.append(order, order[0]), 2], 'k-')
        #     # # xlim = ax.get_xlim()
        #     # # ylim = ax.get_ylim()
        #     # # X, Y = np.meshgrid(np.arange(xlim[0], xlim[1], 0.1),
        #     # #                    np.arange(ylim[0], ylim[1], 0.1))
        #     # # Z = np.zeros(X.shape)
        #     # # for r in range(X.shape[0]):
        #     # #     for c in range(X.shape[1]):
        #     # #         Z[r, c] = n[0] * X[r, c] + n[1] * Y[r, c] + n[2] * Z[r ,c]
        #     # # ax.plot_wireframe(X, Y, Z, color='k')
        #     # plt.show()
        #
        #     sqltext = 'INSERT INTO "{0}"."{1}" (i, j, k, rid, vert1, vert2, vert3, vert4, vert5, vert6, vert7) ' \
        #               'SELECT {2}, {3}, {4}, {5}, ' \
        #               'ST_GeometryN(%s,{6}), ST_GeometryN(%s,{7}), ST_GeometryN(%s,{8}), ' \
        #               'ST_GeometryN(%s,{9}), ST_GeometryN(%s,{10}), ST_GeometryN(%s,{11}), ST_GeometryN(%s,{12}) '\
        #         .format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces, i, j, k, rid, *order_all+1)
        #     self.execute(sqltext, (polygon, polygon, polygon, polygon, polygon, polygon, polygon, ))
        # # Create polygon
        # sqltext = 'UPDATE "{0}"."{1}" SET geom =  ' \
        #           'ST_ForceRHR(' \
        #           'ST_SetSRID(ST_MakePolygon(ST_MakeLine(ARRAY[vert1, vert2, vert3, vert4, vert5, vert6, vert7,' \
        #           '     CASE WHEN vert1 IS NOT NULL THEN vert1 ' \
        #           '          WHEN vert2 IS NOT NULL THEN vert2 ' \
        #           '          WHEN vert3 IS NOT NULL THEN vert3 ' \
        #           '          WHEN vert4 IS NOT NULL THEN vert4 ' \
        #           '          WHEN vert5 IS NOT NULL THEN vert5 ' \
        #           '          WHEN vert6 IS NOT NULL THEN vert6 ' \
        #           '          WHEN vert7 IS NOT NULL THEN vert7 END' \
        #           '])), %s)) ' \
        #           'WHERE i = {2} AND j = {3} AND k = {4}'.format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces, i, j, k)
        # self.execute(sqltext, (self.cfg.srid_palm, ))

        #
        # sqltext = 'UPDATE "{0}"."{1}" SET ' \
        #           'vert1 = ST_PointN(ST_Boundary(geom), 1), ' \
        #           'vert2 = ST_PointN(ST_Boundary(geom), 2), ' \
        #           'vert3 = ST_PointN(ST_Boundary(geom), 3), ' \
        #           'vert4 = ST_PointN(ST_Boundary(geom), 4), ' \
        #           'vert5 = ST_PointN(ST_Boundary(geom), 5), ' \
        #           'vert6 = ST_PointN(ST_Boundary(geom), 6), ' \
        #           'vert7 = ST_PointN(ST_Boundary(geom), 7)' \
        #     .format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
        # self.execute(sqltext)

        #
        # sqltext = ' UPDATE "{0}"."{1}" SET center = ST_SetSRID(ST_MakePoint(ST_X(ST_Centroid(geom)), ST_Y(ST_Centroid(geom)), ' \
        #           '     (COALESCE(ST_Z(ST_PointN(ST_ExteriorRing(geom),1)), 0.0) + COALESCE(ST_Z(ST_PointN(ST_ExteriorRing(geom),2)), 0.0) + ' \
        #           '      COALESCE(ST_Z(ST_PointN(ST_ExteriorRing(geom),3)), 0.0) + COALESCE(ST_Z(ST_PointN(ST_ExteriorRing(geom),4)), 0.0) + ' \
        #           '      COALESCE(ST_Z(ST_PointN(ST_ExteriorRing(geom),5)), 0.0) + COALESCE(ST_Z(ST_PointN(ST_ExteriorRing(geom),6)), 0.0) + ' \
        #           '      COALESCE(ST_Z(ST_PointN(ST_ExteriorRing(geom),7)), 0.0)) / ST_NPoints(geom))' \
        #           '         , %s)' \
        #           'WHERE i = {2} AND j = {3} AND k = {4}'.format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces, i, j, k)
        # self.execute(sqltext, (self.cfg.srid_palm,))


    def merge_local_wall_roof(self, i, j, k, x_vert, y_vert, z_vert, n_vert):
        """ merge vertices on local machine """
        vertices = np.zeros((n_vert, 3))
        vertices[:, 0] = np.asarray(x_vert[:n_vert]) - self.cfg.domain.origin_x
        vertices[:, 1] = np.asarray(y_vert[:n_vert]) - self.cfg.domain.origin_y
        vertices[:, 2] = np.asarray(z_vert[:n_vert])

        # cent = np.mean(vertices, 0)
        # cent = np.mean(np.unique(vertices, axis=0), 0)
        cent = np.mean(np.unique(vertices[:, :2], axis=0), 0)

        # calculate normal vector of some triangles
        # A = cent - vertices[1, :]
        #
        # svd = np.linalg.svd(vertices.T - np.mean(vertices.T, axis=1, keepdims=True))
        # left = svd[0]
        # # left[:, -1]
        #
        # n = left[:, -1] / norm(left[:, -1])
        #
        # q = np.cross(A, n)
        #
        # angle = np.zeros(n_vert)
        # for ir in range(n_vert):
        #     r = cent - vertices[ir, :]
        #     t = np.dot(n, np.cross(r, A))
        #     u = np.dot(n, np.cross(r, q))
        #     angle[ir] = np.arctan2(u, t) / np.pi * 180
        #     angle[ir] = angle[ir] if angle[ir] > 0 else 360.0 + angle[ir]
        #
        # order = angle.argsort()

        # cx, cy = list_of_xy_coords.mean(0)

        angles = np.arctan2(vertices[:, 0] - cent[0], vertices[:, 1] - cent[1])
        order = np.argsort(angles)

        # vertices[:, 0] = x_vert[:n_vert]
        # vertices[:, 1] = y_vert[:n_vert]
        # vertices[:, 2] = z_vert[:n_vert]
        # if i == 17 and j == 19 and k == 14:
        #     print(vertices, order)
        #     print(vertices[order])
        #     # exit(1)
        for ir in range(n_vert):
            ir_curr = ir
            ir_prev = ir - 1 if ir > 0 else n_vert - 1
            ir_next = ir + 1 if ir < n_vert - 1 else 0
            curr = order[ir]
            prev = order[ir_prev]
            next = order[ir_next]
            # check if following point lies above each other
            if vertices[curr, 0] == vertices[next, 0] and vertices[curr, 1] == vertices[next, 1]:
                #     # if current and previos has the same height, keep, else change curr and next:
                if not vertices[curr, 2] == vertices[prev, 2] and vertices[next, 2] == vertices[prev, 2]:
                    order[ir_curr], order[ir_next] = order[ir_next], order[ir_curr]
                # elif vertices[next, 2] == vertices[prev, 2]:
                #     order[ir_curr], order[ir_next] = order[ir_next], order[ir_curr]
            # if vertices[curr, 0] == vertices[prev, 0] and vertices[curr, 1] == vertices[prev, 1]:
            #     # if current and previos has the same height, keep, else change curr and next:
            #     if not vertices[curr, 2] == vertices[next, 2] and vertices[next, 2] == vertices[prev, 2]:
            #         order[ir_curr], order[ir_prev] = order[ir_prev], order[ir_curr]
            # elif vertices[next, 2] == vertices[prev, 2]:
            #     order[ir_curr], order[ir_next] = order[ir_next], order[ir_curr]
        # if i == 17 and j == 19 and k == 14:
        #     print(vertices, order)
        #     print(vertices[order])
        #     exit(1)

        # fig = plt.figure()
        # from mpl_toolkits import mplot3d
        # ax = plt.axes(projection='3d')
        # plt.title('i,j,k: {},{},{}'.format(i, j, k))
        # ax.plot3D(vertices[:, 0], vertices[:, 1], vertices[:, 2], 'o')
        # ax.plot3D([cent[0], cent[0] + n[0]], [cent[1], cent[1] + n[1]], [cent[2], cent[2] + n[2]], 'k-')
        # ax.plot3D([cent[0], cent[0] + q[0]], [cent[1], cent[1] + q[1]], [cent[2], cent[2] + q[2]], 'k:')
        # ax.plot3D([cent[0], cent[0] + A[0]], [cent[1], cent[1] + A[1]], [cent[2], cent[2] + A[2]], 'k--')
        # ax.plot3D(vertices[np.append(order, order[0]), 0],
        #           vertices[np.append(order, order[0]), 1],
        #           vertices[np.append(order, order[0]), 2], 'k-')
        # ax.set_xlabel('x coordinate')
        # ax.set_ylabel('y coordinate')
        # ax.set_zlabel('z coordinate')
        # # xlim = ax.get_xlim()
        # # ylim = ax.get_ylim()
        # # X, Y = np.meshgrid(np.arange(xlim[0], xlim[1], 0.1),
        # #                    np.arange(ylim[0], ylim[1], 0.1))
        # # Z = np.zeros(X.shape)
        # # for r in range(X.shape[0]):
        # #     for c in range(X.shape[1]):
        # #         Z[r, c] = n[0] * X[r, c] + n[1] * Y[r, c] + n[2] * Z[r ,c]
        # # ax.plot_wireframe(X, Y, Z, color='k')
        # plt.show()

        order_all = np.append(order, np.arange(n_vert, 7))
        return order_all

    def merge_local_wall_terrain(self, i, j, k, wall_coord, terr_coord, wall_vert, terr_vert):
        """ merging faces between terrain and wall """
        wall_coord = wall_coord[:wall_vert, :]
        terr_coord = terr_coord[:terr_vert, :]

        wall_coord_t = wall_coord[wall_coord[:, 2] >= np.max(wall_coord[:, 2])]
        # only_top = True if wall_coord_t[0,2] == wall_coord_t[1,2] else False
        # loop for detection when points are above each other
        trtw = []
        tr_new = []
        for tri, tr in enumerate(terr_coord):
            tr_new.append(tr)
            trtw0 = [tri, -1, False]
            found = False
            for twi, tw in enumerate(wall_coord_t):
                if tw[0] == tr[0] and tw[1] == tr[1]:
                    trtw0 = [tri, twi, True]
                    trtw.append(trtw0)
                    if tw[2] > tr[2]:
                        trtw.append(trtw0)
                        terr_coord[tri, 2] = tw[2]
                        # tr_new.append(tw)
                    found = True
                    break
            if not found:
                trtw.append(trtw0)

        tr_new.append(tr_new[0])
        vertices = np.asarray(tr_new).astype('float')

        n_vert = vertices.shape[0]

        cent = np.mean(vertices, 0)

        # calculate normal vector of some triangles
        vi = 0
        vj = 1
        A = cent - vertices[vi, :]

        svd = np.linalg.svd(vertices.T - np.mean(vertices.T, axis=1, keepdims=True))
        left = svd[0]

        n = left[:, -1] / norm(left[:, -1])

        q = np.cross(A, n)

        angle = np.zeros(n_vert)
        for ir in range(n_vert):
            r = cent - vertices[ir, :]
            t = np.dot(n, np.cross(r, A))
            u = np.dot(n, np.cross(r, q))
            angle[ir] = np.arctan2(u, t) / np.pi * 180
            angle[ir] = angle[ir] if angle[ir] > 0 else 360.0 + angle[ir]

        order = angle.argsort()
        order_all = np.append(order, np.arange(n_vert, 7))

        # fig = plt.figure()
        # from mpl_toolkits import mplot3d
        # ax = plt.axes(projection='3d')
        # plt.title('i,j,k: {},{},{}'.format(i, j, k))
        # ax.plot3D(vertices[:, 0], vertices[:, 1], vertices[:, 2], 'o')
        # ax.plot3D(vertices[:, 0], vertices[:, 1], vertices[:, 2], '-b')
        # ax.plot3D(vertices[np.append(order, order[0]), 0],
        #           vertices[np.append(order, order[0]), 1],
        #           vertices[np.append(order, order[0]), 2], 'k-')
        # ax.set_xlabel('x coordinate')
        # ax.set_ylabel('y coordinate')
        # ax.set_zlabel('z coordinate')
        # plt.show()

        vert_order = np.zeros((8, 3), dtype=object)
        vert_order[:] = None
        vert_order[:n_vert] = vertices[order]

        return vert_order

    def initialize_slanted_faces(self):
        """ Initialization of slanted faces from terrain, wall, roof faces """
        progress('Processing merging of final structure')

        # create final structure of slanted faces
        sqltext = f"""
            drop table if exists "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}"; 
            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" ( 
                i integer, j integer, k integer, wid integer,
                rid integer, lid integer, 
                iswall boolean, 
                isroof boolean, 
                isterr boolean, 
                n_vert integer, 
                center geometry(pointz, %s), 
                geom geometry("polygonz", %s),
                vert1 geometry(pointz, %s), 
                vert2 geometry(pointz, %s), 
                vert3 geometry(pointz, %s), 
                vert4 geometry(pointz, %s), 
                vert5 geometry(pointz, %s), 
                vert6 geometry(pointz, %s), 
                vert7 geometry(pointz, %s), 
                norm geometry("pointz", %s), 
                vert1i integer, vert2i integer, vert3i integer, 
                vert4i integer, vert5i integer, vert6i integer, vert7i integer  
            )
        """
        self.execute(sqltext, (
            self.cfg.srid_palm, self.cfg.srid_palm, self.cfg.srid_palm, self.cfg.srid_palm,
            self.cfg.srid_palm, self.cfg.srid_palm, self.cfg.srid_palm, self.cfg.srid_palm,
            self.cfg.srid_palm, self.cfg.srid_palm,
        ))

        self.execute(
            f'create index slanted_faces_ji_idx on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" (j,i)')

        if self.cfg.has_buildings:
            debug('Inserting slanted gridded roof into slanted faces')
            sqltext = f"""
                insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" (geom, rid, wid, lid, iswall, isroof, isterr) 
                select st_forcerhr(geom), rid, null, null, false, true, false 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_roof_gridded}"
            """
            self.execute(sqltext)

            debug('Inserting slanted gridded wall into slanted faces')
            sqltext = f"""
                insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" (geom, rid, wid, lid, iswall, isroof, isterr, norm) 
                select st_forcerhr(geom), null, wid, null, true, false, false, norm  
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_wall_gridded}"
            """
            self.execute(sqltext)

        debug('Inserting slanted gridded terrain into slanted faces')
        sqltext = f"""
            insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" (geom, rid, wid, lid, iswall, isroof, isterr) 
            select st_forcerhr(geom), null, null, lid, false, false, true  
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_terrain_gridded}"
        """
        self.execute(sqltext)

        debug('Updating faces centers')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set 
            center = st_setsrid(st_makepoint(st_x(st_centroid(geom)), st_y(st_centroid(geom)), 
                 (coalesce(st_z(st_pointn(st_exteriorring(geom)),1), 0.0) + coalesce(st_z(st_pointn(st_exteriorring(geom)),2), 0.0) + 
                  coalesce(st_z(st_pointn(st_exteriorring(geom)),3), 0.0) + coalesce(st_z(st_pointn(st_exteriorring(geom)),4), 0.0) + 
                  coalesce(st_z(st_pointn(st_exteriorring(geom)),5), 0.0) + coalesce(st_z(st_pointn(st_exteriorring(geom)),6), 0.0) + 
                  coalesce(st_z(st_pointn(st_exteriorring(geom)),7), 0.0)) / st_npoints(geom))
                     , %s)
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        debug('Calculating face i,j,k')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set 
            i = floor((st_x(center) - {self.cfg.domain.origin_x}) / {self.cfg.domain.dx}), 
            j = floor((st_y(center) - {self.cfg.domain.origin_y}) / {self.cfg.domain.dy}), 
            k = floor(st_z(center) / {self.cfg.domain.dx})
        """
        self.execute(sqltext)

        debug('Add id into table slanted faces table')
        self.execute(f'alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" add column id serial')

        verbose('Delete all wall that are under terr_wall faces')
        sqltext = f"""
            with ij_terr as (select i,j,k from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" where isterr) 
            select s.id 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" as s 
               right join ij_terr as ts on ts.i = s.i and ts.j = s.j 
            where iswall and s.k < ts.k
        """
        ids = self.execute(sqltext)
        ids = [x[0] for x in ids]

        if len(ids) > 0:
            sqltext = f'delete from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" where id in {tuple(ids)}'
            self.execute(sqltext)

        # verbose('Deleting duplicates')
        # sqltext = 'ALTER TABLE "{0}"."{1}" ADD COLUMN IF NOT EXISTS rijk SERIAL'\
        #           .format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
        # self.execute(sqltext)
        #
        # sqltext = 'DELETE FROM "{0}"."{1}" ' \
        #           'WHERE rijk IN (' \
        #           '               SELECT rijk FROM (' \
        #           '                     SELECT rijk, ROW_NUMBER() OVER (partition BY i,j,k ) AS RowNumber ' \
        #           '                     FROM "{0}"."{1}"' \
        #           '                     WHERE isroof) AS T ' \
        #           '               WHERE T.RowNumber > 1)'\
        #           .format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
        # self.execute(sqltext)

        # sqltext = 'ALTER TABLE "{0}"."{1}" DROP COLUMN rijk'\
        #           .format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
        # self.execute(sqltext)
        #
        #
        # verbose('Deleting duplicates')
        # sqltext = 'ALTER TABLE "{0}"."{1}" ADD COLUMN IF NOT EXISTS rijk SERIAL'\
        #           .format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
        # self.execute(sqltext)
        #
        # sqltext = 'DELETE FROM "{0}"."{1}" ' \
        #           'WHERE rijk IN (' \
        #           '               SELECT rijk FROM (' \
        #           '                     SELECT rijk, ROW_NUMBER() OVER (partition BY i,j,k ) AS RowNumber ' \
        #           '                     FROM "{0}"."{1}"' \
        #           '                     WHERE isterr) AS T ' \
        #           '               WHERE T.RowNumber > 1)'\
        #           .format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
        # self.execute(sqltext)
        #
        # sqltext = 'ALTER TABLE "{0}"."{1}" DROP COLUMN rijk'\
        #           .format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
        # self.execute(sqltext)

        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set 
            vert1 = st_pointn(st_boundary(geom), 1), 
            vert2 = st_pointn(st_boundary(geom), 2), 
            vert3 = st_pointn(st_boundary(geom), 3), 
            vert4 = st_pointn(st_boundary(geom), 4), 
            vert5 = st_pointn(st_boundary(geom), 5), 
            vert6 = st_pointn(st_boundary(geom), 6), 
            vert7 = st_pointn(st_boundary(geom), 7)
        """
        self.execute(sqltext)

        debug('Updating n_vert')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set 
            n_vert = case when vert7 is not null then 7 
                          when vert6 is not null then 6 
                          when vert5 is not null then 5 
                          when vert4 is not null then 4 
                          when vert3 is not null then 3 
                          when vert2 is not null then 2 
                          when vert1 is not null then 1 end 
        """
        self.execute(sqltext)

        debug('Updating all planar-horizontal faces, update their k')
        verbose('Fetching max k from slanted faces')
        sqltext = f'select max(k) from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}"'
        k_max = self.execute(sqltext)[0][0]

        for k in range(k_max + 1):
            verbose('\tDelete all wall that has the same height in all vertices k={}', k)
            z_val = (k + 1) * self.cfg.domain.dz
            sqltext = f"""
                delete from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" 
                where id in 
                  (select id from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" 
                   where       (case when st_z(vert1) = {z_val} then 1 else 0 end + 
                                case when st_z(vert2) = {z_val} then 1 else 0 end + 
                                case when st_z(vert3) = {z_val} then 1 else 0 end + 
                                case when st_z(vert4) = {z_val} and n_vert > 4 then 1 else 0 end + 
                                case when st_z(vert5) = {z_val} and n_vert > 5 then 1 else 0 end + 
                                case when st_z(vert6) = {z_val} and n_vert > 6 then 1 else 0 end + 
                                case when st_z(vert7) = {z_val} and n_vert > 7 then 1 else 0 end) = n_vert-1 
                               and iswall)
            """
            self.execute(sqltext)

        for k in range(k_max + 1):
            verbose('\tUpdating k={}', k)
            z_val = (k + 1) * self.cfg.domain.dz
            sqltext = f"""
                select id, i, j, k, n_vert, rid, wid, lid, isterr, iswall, isroof, 
                 array[st_x(vert1), st_y(vert1), st_z(vert1)],  
                 array[st_x(vert2), st_y(vert2), st_z(vert2)], 
                 array[st_x(vert3), st_y(vert3), st_z(vert3)], 
                 array[st_x(vert4), st_y(vert4), st_z(vert4)], 
                 array[st_x(vert5), st_y(vert5), st_z(vert5)], 
                 array[st_x(vert6), st_y(vert6), st_z(vert6)], 
                 array[st_x(vert7), st_y(vert7), st_z(vert7)]  
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" as s 
                where (case when st_z(vert1) = {z_val} then 1 else 0 end + 
                       case when st_z(vert2) = {z_val} then 1 else 0 end + 
                       case when st_z(vert3) = {z_val} then 1 else 0 end + 
                       case when st_z(vert4) = {z_val} and n_vert > 4 then 1 else 0 end + 
                       case when st_z(vert5) = {z_val} and n_vert > 5 then 1 else 0 end + 
                       case when st_z(vert6) = {z_val} and n_vert > 6 then 1 else 0 end + 
                       case when st_z(vert7) = {z_val} and n_vert > 7 then 1 else 0 end) > 2 
                      and n_vert > 4 and k = {k} 
                order by i,j,k
            """
            verts = self.execute(sqltext)

            to_insert = []
            to_delete = []
            for vert in verts:
                np_verts = np.empty((7, 3), dtype=object)
                id_val, i_val, j_val, k_val, n_vert_val = vert[0], vert[1], vert[2], vert[3], vert[4]
                rid, wid, lid, isterr, iswall, isroof = vert[5], vert[6], vert[7], vert[8], vert[9], vert[10]
                lastidx = 11
                x_vert, y_vert, z_vert = [], [], []
                for idx in range(n_vert_val - 1):
                    if vert[lastidx + idx][0] is not None:
                        x_vert.append(vert[lastidx + idx][0])
                        y_vert.append(vert[lastidx + idx][1])
                        z_vert.append(vert[lastidx + idx][2])
                x_vert = np.asarray(x_vert)
                y_vert = np.asarray(y_vert)
                z_vert = np.asarray(z_vert)
                to_keep = []
                tt_max = max(z_vert)
                for it, ttt in enumerate(z_vert):
                    if it == 0:
                        ileft = len(z_vert) - 1
                        iright = it + 1
                    elif it == len(z_vert) - 1:
                        iright = 0
                        ileft = it - 1
                    else:
                        iright = it + 1
                        ileft = it - 1
                    if z_vert[ileft] == tt_max and z_vert[it] == tt_max and z_vert[iright] == tt_max:
                        pass
                    else:
                        to_keep.append(it)
                n_vert_new = len(to_keep) + 1
                np_verts[:n_vert_new - 1, 0] = x_vert[to_keep]
                np_verts[:n_vert_new - 1, 1] = y_vert[to_keep]
                np_verts[:n_vert_new - 1, 2] = z_vert[to_keep]
                np_verts[n_vert_new - 1, :] = np_verts[0, :]
                to_insert.append((id_val, i_val, j_val, k_val, rid, wid, lid, iswall, isroof, isterr,
                                  np_verts[0, 0], np_verts[0, 1], np_verts[0, 2], self.cfg.srid_palm,
                                  np_verts[1, 0], np_verts[1, 1], np_verts[1, 2], self.cfg.srid_palm,
                                  np_verts[2, 0], np_verts[2, 1], np_verts[2, 2], self.cfg.srid_palm,
                                  np_verts[3, 0], np_verts[3, 1], np_verts[3, 2], self.cfg.srid_palm,
                                  np_verts[4, 0], np_verts[4, 1], np_verts[4, 2], self.cfg.srid_palm,
                                  np_verts[5, 0], np_verts[5, 1], np_verts[5, 2], self.cfg.srid_palm,
                                  np_verts[6, 0], np_verts[6, 1], np_verts[6, 2], self.cfg.srid_palm,
                                  ))
                to_delete.append((id_val,))

            debug('Deleting all unwanted rows')
            sqltext = f'delete from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" where id = any(%s)'
            self.execute(sqltext, (to_delete,))

            debug('Inserting all new entries into slanted faces table')
            sqltext = f"""
                insert into "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" (id, i, j, k, rid, wid, lid, iswall, isroof, isterr, 
                                         vert1, vert2, vert3, vert4, vert5, vert6, vert7) 
                values                  (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
                                        st_setsrid(st_makepoint(%s, %s, %s), %s), 
                                        st_setsrid(st_makepoint(%s, %s, %s), %s), 
                                        st_setsrid(st_makepoint(%s, %s, %s), %s), 
                                        st_setsrid(st_makepoint(%s, %s, %s), %s), 
                                        st_setsrid(st_makepoint(%s, %s, %s), %s), 
                                        st_setsrid(st_makepoint(%s, %s, %s), %s), 
                                        st_setsrid(st_makepoint(%s, %s, %s), %s) 
                                        ) 
            """
            self.executemany(sqltext, to_insert)

            # Create polygon
            debug('Updating 3d polygon')
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set geom =  
                st_forcerhr(
                st_setsrid(st_makepolygon(st_makeline(array[vert1, vert2, vert3, vert4, vert5, vert6, vert7,
                     case when vert1 is not null then vert1 
                          when vert2 is not null then vert2 
                          when vert3 is not null then vert3 
                          when vert4 is not null then vert4 
                          when vert5 is not null then vert5 
                          when vert6 is not null then vert6 
                          when vert7 is not null then vert7 end
                ])), %s)) 
                where geom is null
            """
            self.execute(sqltext, (self.cfg.srid_palm,))

            # debug('Update center of faces, just in case')
            # debug('Updating center')
            # sqltext = 'UPDATE "{0}"."{1}" SET center = ' \
            #           'ST_SetSRID(ST_MakePoint(ST_X(ST_Centroid(geom)), ST_Y(ST_Centroid(geom)), ' \
            #           '                       (ST_Z(vert1) + ST_Z(vert2) + ' \
            #           '                          CASE WHEN ST_NPoints(geom) > 3 THEN ST_Z(ST_PointN(ST_ExteriorRing(geom),3)) ELSE 0.0 END + ' \
            #           '                          CASE WHEN ST_NPoints(geom) > 4 THEN ST_Z(ST_PointN(ST_ExteriorRing(geom),4)) ELSE 0.0 END + ' \
            #           '                          CASE WHEN ST_NPoints(geom) > 5 THEN ST_Z(ST_PointN(ST_ExteriorRing(geom),5)) ELSE 0.0 END + ' \
            #           '                          CASE WHEN ST_NPoints(geom) > 6 THEN ST_Z(ST_PointN(ST_ExteriorRing(geom),6)) ELSE 0.0 END) / (ST_NPoints(geom) - 1))' \
            #           '         , %s)'.format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
            # self.execute(sqltext, (self.cfg.srid_palm,))

        debug('Updating faces centers')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set 
            center = st_setsrid(st_makepoint(st_x(st_centroid(geom)), st_y(st_centroid(geom)), 
                 (coalesce(st_z(st_pointn(st_exteriorring(geom)),1), 0.0) + coalesce(st_z(st_pointn(st_exteriorring(geom)),2), 0.0) + 
                  coalesce(st_z(st_pointn(st_exteriorring(geom)),3), 0.0) + coalesce(st_z(st_pointn(st_exteriorring(geom)),4), 0.0) + 
                  coalesce(st_z(st_pointn(st_exteriorring(geom)),5), 0.0) + coalesce(st_z(st_pointn(st_exteriorring(geom)),6), 0.0) + 
                  coalesce(st_z(st_pointn(st_exteriorring(geom)),7), 0.0) + coalesce(st_z(st_pointn(st_exteriorring(geom)),8), 0.0)) / st_npoints(geom))
                     , %s)
        """
        self.execute(sqltext, (self.cfg.srid_palm,))

        debug('Update i,j,k according to new centers')
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set 
            i = floor((st_x(center) - {self.cfg.domain.origin_x}) / {self.cfg.domain.dx}), 
            j = floor((st_y(center) - {self.cfg.domain.origin_y}) / {self.cfg.domain.dy}), 
            k = floor((st_z(center) / {self.cfg.domain.dx}) + 1)
        """
        self.execute(sqltext)

        for k in range(k_max + 1):
            verbose(
                '\tUpdating k={} (to k+1) in faces where all vertices lies in the same horizontal plane = k*dz [{}]',
                k, k * self.cfg.domain.dz)
            z_val = k * self.cfg.domain.dz
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set k = 
                k + 1 
                where k = {k} and (case when st_z(vert1) = {z_val} then 1 else 0 end + 
                                   case when st_z(vert2) = {z_val} then 1 else 0 end + 
                                   case when st_z(vert3) = {z_val} then 1 else 0 end + 
                                   case when st_z(vert4) = {z_val} and n_vert > 4 then 1 else 0 end + 
                                   case when st_z(vert5) = {z_val} and n_vert > 5 then 1 else 0 end + 
                                   case when st_z(vert6) = {z_val} and n_vert > 6 then 1 else 0 end + 
                                   case when st_z(vert7) = {z_val} and n_vert > 7 then 1 else 0 end) >= n_vert-1
            """
            self.execute(sqltext)

        sqltext = f"""
            with ijk as (select i,j,k 
                         from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}"  
                         where not iswall  
                         group by i,j,k 
                         having count(*) = 2 
                         order by i,j,k ) 
            select st_z(center), id, s.i, s.j, s.k  
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" as s 
            right join ijk on ijk.i = s.i and ijk.j = s.j and ijk.k = s.k 
            where not iswall 
            order by s.i, s.j, s.k
        """
        zijk = self.execute(sqltext)

        id2del = []
        for ijk in range(0, len(zijk), 2):
            z1, z2 = zijk[ijk][0], zijk[ijk + 1][0]
            id1, id2 = zijk[ijk][1], zijk[ijk + 1][1]
            id2del.append((id1 if z1 < z2 else id2,))

        debug('Deleting all unwanted rows')
        sqltext = f'delete from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" where id = any(%s)'
        self.execute(sqltext, (id2del,))

    def create_integer_vertices(self):
        """ create coordinates of vertices using 4 integer and 1 float
            i,j,k position of the line where vertex sits
            dir direction in which inside orthogonal face vertex is placed
                0 +k, 1 -k, 2 +j, 3 -j, 4 +i, 5 -i
            length normalized lenght between inside point and slanted face vertex
        """
        progress('creating new coordinates of the slanted faces')
        for ni in range(1, 8):
            # define indices for adjacent vertices
            ni_p = min(ni + 1, 7)
            ni_m = max(ni - 1, 1)

            debug('processing {}. coordinates', ni)
            verbose('\tadding new columns')

            sqltext = f"""
                alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" 
                add column if not exists ii{ni} integer, 
                add column if not exists jj{ni} integer, 
                add column if not exists kk{ni} integer, 
                add column if not exists dir{ni} integer, 
                add column if not exists len{ni} double precision, 
                add column if not exists iline boolean, 
                add column if not exists jline boolean, 
                add column if not exists kline boolean,
                add column if not exists nx{ni}_l double precision, 
                add column if not exists ny{ni}_l double precision, 
                add column if not exists nz{ni}_l double precision
            """
            self.execute(sqltext)

            debug('calculate for each vertex its own normal vector from adjacent vertices')
            sqltext = f"""
                with c as ( 
                   select 
                       vert{ni} as vert_m, 
                       case when ({ni} + 1) < n_vert then vert{ni_p} else vert1 end as vert_r, 
                       case when ({ni} - 1) > 0 then vert{ni_m} else 
                            case when n_vert = 4 then vert3 when n_vert = 5 then vert4 when n_vert = 6 then vert5 when n_vert = 7 then vert6 end 
                       end as vert_l, 
                       id 
                    from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}"
                ) 
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" as s set ( nx{ni}_l, ny{ni}_l, nz{ni}_l ) = 
                (case when {ni} < n_vert then ((st_y(vert_l)-st_y(vert_m))*(st_z(vert_r)-st_z(vert_m)) - (st_z(vert_l)-st_z(vert_m))*(st_y(vert_r)-st_y(vert_m)))
                  else null end, 
                 case when {ni} < n_vert then ((st_z(vert_l)-st_z(vert_m))*(st_x(vert_r)-st_x(vert_m)) - (st_x(vert_l)-st_x(vert_m))*(st_z(vert_r)-st_z(vert_m)))
                  else null end, 
                 case when {ni} < n_vert then ((st_x(vert_l)-st_x(vert_m))*(st_y(vert_r)-st_y(vert_m)) - (st_y(vert_l)-st_y(vert_m))*(st_x(vert_r)-st_x(vert_m)))
                  else null end) 
                from c where c.id = s.id and not iswall
            """
            self.execute(sqltext)

            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" as s set ( nx{ni}_l, ny{ni}_l, nz{ni}_l ) = 
                (nx1_l, ny1_l, nz1_l) 
                where {ni} = n_vert
            """
            self.execute(sqltext)

            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" as s set ( nx{ni}_l, ny{ni}_l, nz{ni}_l ) = 
                (normx, normy, normz) 
                where iswall
            """
            self.execute(sqltext)

            verbose('\tupdating ii, jj, kk')
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set 
                ii{ni} = floor((st_x(vert{ni}) - {self.cfg.domain.origin_x}) / {self.cfg.domain.dx}), 
                jj{ni} = floor((st_y(vert{ni}) - {self.cfg.domain.origin_y}) / {self.cfg.domain.dy}), 
                kk{ni} = floor(st_z(vert{ni}) / {self.cfg.domain.dz})
            """
            self.execute(sqltext)

            verbose('\tupdating iline, jline, kline')
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set 
                iline = case when abs(st_x(vert{ni}) - ii{ni} * {self.cfg.domain.dx} - {self.cfg.domain.origin_x}) > 1e-8 then true else false end, 
                jline = case when abs(st_y(vert{ni}) - jj{ni} * {self.cfg.domain.dy} - {self.cfg.domain.origin_y}) > 1e-8 then true else false end, 
                kline = case when abs(st_z(vert{ni}) - kk{ni} * {self.cfg.domain.dz}) > 1e-8 then true else false end
            """
            self.execute(sqltext)

            verbose('\tupdating dir')
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set dir{ni} = 
                case when iline then case when nx{ni}_l > 0.0 then 4 
                                          when nx{ni}_l < 0.0 then 5 
                                          else 6 end 
                     when jline then case when ny{ni}_l > 0.0 then 2 
                                          when ny{ni}_l < 0.0 then 3
                                          else 6 end 
                     when kline then case when nz{ni}_l > 0.0 then 0 
                                          when nz{ni}_l < 0.0 then 1 
                                          else 6 end 
                     else 6 end
            """
            self.execute(sqltext)

            verbose('\tupdating ii,jj,kk')
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set 
                ii{ni} = case when dir{ni} = 5 then ii{ni}+1 else ii{ni} end, 
                jj{ni} = case when dir{ni} = 3 then jj{ni}+1 else jj{ni} end, 
                kk{ni} = case when dir{ni} = 1 then kk{ni}+1 else kk{ni} end
            """
            self.execute(sqltext)

            verbose('\tupdating len')
            sqltext = f"""
                update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set len{ni} = 
                sqrt(
                     ((st_x(vert{ni}) - {self.cfg.domain.origin_x} - ii{ni} * {self.cfg.domain.dx}) / {self.cfg.domain.dx} ) ^ 2 + 
                     ((st_y(vert{ni}) - {self.cfg.domain.origin_y} - jj{ni} * {self.cfg.domain.dy}) / {self.cfg.domain.dy} ) ^ 2 + 
                     ((st_z(vert{ni})       - kk{ni} * {self.cfg.domain.dz}) / {self.cfg.domain.dz} ) ^ 2
                     )
            """
            self.execute(sqltext)
            # 'case when dir{2} = 1 then (st_x(vert{2}) - {6} - ii{2} * {3}) / {3} ' \
            # '     when dir{2} = 0 then (st_x(vert{2}) - {6} - ii{2} * {3}) / {3}' \
            # '     when dir{2} = 3 then (st_y(vert{2}) - {7} - jj{2} * {4}) / {4} ' \
            # '     when dir{2} = 2 then (st_y(vert{2}) - {7} - jj{2} * {4}) / {4}' \
            # '     when dir{2} = 5 then (st_z(vert{2})       - kk{2} * {5}) / {5} ' \
            # '     when dir{2} = 4 then (st_z(vert{2})       - kk{2} * {5}) / {6}' \
            # 'end '

    def check_for_vertex_singularities(self):
        """ Check if there some vertices that lies in gridboxes corners and can have multiple vertices

            Each interface Air / Solid must have 1 Vertex, In case of singularity, there will be two point with the same z,y,x (kk,jj,ii) but different dir
        """
        # dirs = np.array([[[ 0, 1, 0], [ 1, 0, 0], [ 0, 0, 1]],
        #                  [[ 0, 0,-1], [ 1, 0, 0], [ 0, 1, 0]],
        #                  [[ 0,-1, 0], [ 1, 0, 0], [ 0, 0,-1]],
        #                  [[ 0, 0, 1], [ 1, 0, 0], [ 0,-1, 0]],
        #                  [[ 0, 1, 0], [-1, 0, 0], [ 0, 0, 1]],
        #                  [[ 0, 0,-1], [-1, 0, 0], [ 0, 1, 0]],
        #                  [[ 0,-1, 0], [-1, 0, 0], [ 0, 0,-1]],
        #                  [[ 0, 0, 1], [-1, 0, 0], [ 0,-1, 0]],
        #                  ])
        # exit(1)
        dirs_vect = np.array([[1, 0, 1],
                              [-1, 0, -1],
                              [0, 1, 0],
                              [0, -1, 0],
                              [0, 0, 1],
                              [0, 0, -1]])

        vert2dirs = np.array([[4, 0, 2],
                              [2, 0, 5],
                              [5, 0, 3],
                              [3, 0, 4],
                              [4, 1, 2],
                              [2, 1, 5],
                              [5, 1, 3],
                              [3, 1, 4], ])

        dir_corns = np.array([[1, 4, 3],
                              [2, 5, 0],
                              [3, 6, 1],
                              [0, 7, 2],
                              [5, 0, 7],
                              [6, 1, 4],
                              [7, 2, 5],
                              [4, 3, 6],
                              ])

        corners = np.array([[0, 0, 0],
                            [0, 0, 1],
                            [0, 1, 1],
                            [0, 1, 0],
                            [1, 0, 0],
                            [1, 0, 1],
                            [1, 1, 1],
                            [1, 1, 0]])
        progress('Checking for singularities')
        debug('Identification of polygons with singularities')
        sqltext = 'SELECT id, k, j, i, n_vert, ' \
                  '       wid, rid, lid, isterr, iswall, isroof, ' \
                  '       len1, len2, len3, len4, len5, len6, len7, ' \
                  '       dir1, dir2, dir3, dir4, dir5, dir6, dir7, ' \
                  '       normz, normy, normx, area, center, ' \
                  '       ii1, ii2, ii3, ii4, ii5, ii6, ii7, ' \
                  '       jj1, jj2, jj3, jj4, jj5, jj6, jj7, ' \
                  '       kk1, kk2, kk3, kk4, kk5, kk6, kk7, ' \
                  'ARRAY[ST_Z(vert1), ST_Y(vert1), ST_X(vert1)], ' \
                  'ARRAY[ST_Z(vert2), ST_Y(vert2), ST_X(vert2)], ' \
                  'ARRAY[ST_Z(vert3), ST_Y(vert3), ST_X(vert3)], ' \
                  'ARRAY[ST_Z(vert4), ST_Y(vert4), ST_X(vert4)], ' \
                  'ARRAY[ST_Z(vert5), ST_Y(vert5), ST_X(vert5)], ' \
                  'ARRAY[ST_Z(vert6), ST_Y(vert6), ST_X(vert6)], ' \
                  'ARRAY[ST_Z(vert7), ST_Y(vert7), ST_X(vert7)] ' \
                  ' ' \
                  'FROM "{0}"."{1}" ' \
                  'WHERE (len1=0 OR len2=0 OR len3=0 OR len4=0 OR len5=0 OR len6=0 OR' \
                  '       dir1=6 OR dir2=6 OR dir3=6 OR (dir4=6 AND ii4 IS NOT NULL) OR (dir5=6 AND ii5 IS NOT NULL) OR (dir6=6 AND ii6 IS NOT NULL)) ' \
                  '' \
            .format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
        singulars = self.execute(sqltext)

        to_delete = []
        to_insert = []

        for singular in singulars:
            ids, k, j, i, n_vert = singular[0], singular[1], singular[2], singular[3], singular[4]
            # if k == 15 and j == 19 and i == 25: # [25,19,15]
            #     break
            verbose('Processing singular id: {}', ids)
            wid, rid, lid, isterr, iswall, isroof = singular[5], singular[6], singular[7], singular[8], singular[9], \
            singular[10]
            lens = [irun for irun in singular[11:18]]
            dirs = [irun for irun in singular[18:25]]
            norm = [singular[25], singular[26], singular[27]]
            area = singular[28]
            center = singular[29]
            ii = [irun for irun in singular[30:37]]
            jj = [irun for irun in singular[37:44]]
            kk = [irun for irun in singular[44:51]]
            lastidx = 51
            x_vert, y_vert, z_vert = [], [], []
            for idx in range(n_vert):
                if singular[lastidx + idx][0] is not None:
                    z_vert.append(singular[lastidx + idx][0])
                    y_vert.append(singular[lastidx + idx][1])
                    x_vert.append(singular[lastidx + idx][2])

            x_vert_n, y_vert_n, z_vert_n, ii_n, jj_n, kk_n, dirs_n, lens_n = [], [], [], [], [], [], [], []
            for irun in range(len(x_vert) - 1):
                if x_vert[irun] == x_vert[irun + 1] and y_vert[irun] == y_vert[irun + 1] and z_vert[irun] == z_vert[
                    irun + 1]:
                    verbose('duplicate {}', irun)
                else:
                    x_vert_n.append(x_vert[irun])
                    y_vert_n.append(y_vert[irun])
                    z_vert_n.append(z_vert[irun])
                    ii_n.append(ii[irun])
                    jj_n.append(jj[irun])
                    kk_n.append(kk[irun])
                    dirs_n.append(dirs[irun])
                    lens_n.append(lens[irun])

            irun = len(x_vert) - 1
            if not (x_vert[irun] == x_vert[0] and y_vert[irun] == y_vert[0] and z_vert[irun] == z_vert[0]):
                x_vert_n.append(x_vert[irun])
                y_vert_n.append(y_vert[irun])
                z_vert_n.append(z_vert[irun])
                ii_n.append(ii[irun])
                jj_n.append(jj[irun])
                kk_n.append(kk[irun])
                dirs_n.append(dirs[irun])
                lens_n.append(lens[irun])

            x_vert, y_vert, z_vert, ii, jj, kk, dirs, lens = x_vert_n, y_vert_n, z_vert_n, ii_n, jj_n, kk_n, dirs_n, lens_n

            x_vert = np.asarray(x_vert)
            y_vert = np.asarray(y_vert)
            z_vert = np.asarray(z_vert)
            # ii = ((x_vert - self.cfg.domain.origin_x) / self.cfg.domain.dx).astype('int)
            # jj = ((y_vert - self.cfg.domain.origin_y) / self.cfg.domain.dy).astype('int)
            # kk = ((z_vert) / self.cfg.domain.dz).astype('int) + 1   # because k = 0 is flat ground
            k_temp = k - 1
            corner_id = -1 * np.ones(7, dtype='int')
            for idx in range(len(x_vert)):
                if (ii[idx] == i) & (jj[idx] == j) & (kk[idx] == k_temp) & (lens[idx] == 0):
                    corner_id[idx] = 0
                elif (ii[idx] == i + 1) & (jj[idx] == j) & (kk[idx] == k_temp) & (lens[idx] == 0):
                    corner_id[idx] = 1
                elif (ii[idx] == i + 1) & (jj[idx] == j + 1) & (kk[idx] == k_temp) & (lens[idx] == 0):
                    corner_id[idx] = 2
                elif (ii[idx] == i) & (jj[idx] == j + 1) & (kk[idx] == k_temp) & (lens[idx] == 0):
                    corner_id[idx] = 3
                elif (ii[idx] == i) & (jj[idx] == j) & (kk[idx] == k_temp + 1) & (lens[idx] == 0):
                    corner_id[idx] = 4
                elif (ii[idx] == i + 1) & (jj[idx] == j) & (kk[idx] == k_temp + 1) & (lens[idx] == 0):
                    corner_id[idx] = 5
                elif (ii[idx] == i + 1) & (jj[idx] == j + 1) & (kk[idx] == k_temp + 1) & (lens[idx] == 0):
                    corner_id[idx] = 6
                elif (ii[idx] == i) & (jj[idx] == j + 1) & (kk[idx] == k_temp + 1) & (lens[idx] == 0):
                    corner_id[idx] = 7

            # now the suspicious points has corner_id != -1 (in range 0 .. 7)

            # sa_corner = np.zeros(8, dtype='bool)
            # adj_corners = corners + np.array([k_temp, j, i])

            # assign SOLID/AIR corner, solid = True, Air = False
            sa_corner = np.ones(8, dtype='bool')
            adj_corners = corners + np.array([k_temp, j, i])
            for cidx in range(8):
                if norm[0] > 0:
                    less_z = adj_corners[cidx, 0] * self.cfg.domain.dz >= z_vert
                elif norm[0] < 0:
                    less_z = adj_corners[cidx, 0] * self.cfg.domain.dz < z_vert
                else:
                    less_z = adj_corners[cidx, 0] * self.cfg.domain.dz != z_vert
                if norm[1] > 0:
                    less_y = adj_corners[cidx, 1] * self.cfg.domain.dy >= y_vert - self.cfg.domain.origin_y
                elif norm[1] < 0:
                    less_y = adj_corners[cidx, 1] * self.cfg.domain.dy <= y_vert - self.cfg.domain.origin_y
                else:
                    less_y = adj_corners[cidx, 1] * self.cfg.domain.dy != y_vert - self.cfg.domain.origin_y
                if norm[2] > 0:
                    less_x = adj_corners[cidx, 2] * self.cfg.domain.dx >= x_vert - self.cfg.domain.origin_x
                elif norm[2] < 0:
                    less_x = adj_corners[cidx, 2] * self.cfg.domain.dx <= x_vert - self.cfg.domain.origin_x
                else:
                    less_x = adj_corners[cidx, 2] * self.cfg.domain.dx != x_vert - self.cfg.domain.origin_x

                less_all = np.any(less_z & less_y & less_x)
                if norm[0] == 1:
                    less_all = np.any(less_all | less_z)

                if less_all:
                    # print('corner: ', cidx, ' is Air')
                    sa_corner[cidx] = False

            # adjust singularities
            for idx in range(len(x_vert)):
                if corner_id[idx] != -1:
                    # print('corner: ', corner_id[idx], ' is Solid')
                    sa_corner[corner_id[idx]] = True

            # more detailed search is some obscure cases
            for cidx in range(8):
                for idx in range(len(x_vert)):
                    midx = idx  # middle point
                    lidx = idx - 1 if idx > 0 else len(x_vert) - 1
                    ridx = idx + 1 if idx < len(x_vert) - 1 else 0
                    p1, p2, p3 = np.array(
                        [x_vert[lidx] - self.cfg.domain.origin_x, y_vert[lidx] - self.cfg.domain.origin_y, z_vert[lidx]]), \
                        np.array(
                            [x_vert[midx] - self.cfg.domain.origin_x, y_vert[midx] - self.cfg.domain.origin_y, z_vert[midx]]), \
                        np.array([x_vert[ridx] - self.cfg.domain.origin_x, y_vert[ridx] - self.cfg.domain.origin_y, z_vert[ridx]])

                    # due to ordering RHS forcing
                    norm_temp = normal_vector_triangle(p3, p2, p1)
                    # print(idx)
                    # print(p1, p2, p3)
                    # print(norm_temp)
                    if corner_id[idx] != -1:
                        continue
                    air_x, air_y, air_z = False, False, False
                    sol_x, sol_y, sol_z = False, False, False
                    if np.abs(x_vert[idx] - self.cfg.domain.origin_x - ii[idx] * self.cfg.domain.dx) > 1.0e-8 and norm_temp[
                        2] != 0:
                        # lies on i-line, select which corner and look if air or solid -> create direction
                        if norm_temp[2] < 0:
                            air_x = adj_corners[cidx, 2] * self.cfg.domain.dx < x_vert[idx] - self.cfg.domain.origin_x
                            sol_x = adj_corners[cidx, 2] * self.cfg.domain.dx > x_vert[idx] - self.cfg.domain.origin_x
                        elif norm_temp[2] > 0:
                            air_x = adj_corners[cidx, 2] * self.cfg.domain.dx > x_vert[idx] - self.cfg.domain.origin_x
                            sol_x = adj_corners[cidx, 2] * self.cfg.domain.dx < x_vert[idx] - self.cfg.domain.origin_x
                        # also point must line on correct i/line
                        air_y = sol_y = adj_corners[cidx, 1] * self.cfg.domain.dy == y_vert[idx] - self.cfg.domain.origin_y
                        air_z = sol_z = adj_corners[cidx, 0] * self.cfg.domain.dz == z_vert[idx]

                    elif np.abs(y_vert[idx] - self.cfg.domain.origin_y - jj[idx] * self.cfg.domain.dy) > 1.0e-8 and norm_temp[
                        1] != 0:
                        # lies on j-line, select which corner and look if air or solid -> create direction
                        if norm_temp[1] < 0:
                            air_y = adj_corners[cidx, 1] * self.cfg.domain.dy < y_vert[idx] - self.cfg.domain.origin_y
                            sol_y = adj_corners[cidx, 1] * self.cfg.domain.dy > y_vert[idx] - self.cfg.domain.origin_y
                        elif norm_temp[1] > 0:
                            air_y = adj_corners[cidx, 1] * self.cfg.domain.dy > y_vert[idx] - self.cfg.domain.origin_y
                            sol_y = adj_corners[cidx, 1] * self.cfg.domain.dy < y_vert[idx] - self.cfg.domain.origin_y
                        air_x = sol_x = adj_corners[cidx, 2] * self.cfg.domain.dx == x_vert[idx] - self.cfg.domain.origin_x
                        air_z = sol_z = adj_corners[cidx, 0] * self.cfg.domain.dz == z_vert[idx]

                    elif np.abs(z_vert[idx] - kk[idx] * self.cfg.domain.dz) > 1.0e-8 and norm_temp[0] != 0:
                        # lies on k-line, select which corner and look if air or solid -> create direction
                        if norm_temp[0] < 0:
                            air_z = adj_corners[cidx, 0] * self.cfg.domain.dz < z_vert[idx]
                            sol_z = adj_corners[cidx, 0] * self.cfg.domain.dz > z_vert[idx]
                        elif norm_temp[0] > 0:
                            air_z = adj_corners[cidx, 0] * self.cfg.domain.dz > z_vert[idx]
                            sol_z = adj_corners[cidx, 0] * self.cfg.domain.dz < z_vert[idx]
                        air_x = sol_x = adj_corners[cidx, 2] * self.cfg.domain.dx == x_vert[idx] - self.cfg.domain.origin_x
                        air_y = sol_y = adj_corners[cidx, 1] * self.cfg.domain.dy == y_vert[idx] - self.cfg.domain.origin_y

                    if norm_temp[0] == 1:
                        air_x = sol_x = adj_corners[cidx, 2] * self.cfg.domain.dx == x_vert[idx] - self.cfg.domain.origin_x
                        air_y = sol_y = adj_corners[cidx, 1] * self.cfg.domain.dy == y_vert[idx] - self.cfg.domain.origin_y
                        air_z = adj_corners[cidx, 0] * self.cfg.domain.dz >= z_vert[idx]
                        sol_z = adj_corners[cidx, 0] * self.cfg.domain.dz <= z_vert[idx]

                    air_all = air_x & air_y & air_z
                    sol_all = sol_x & sol_y & sol_z
                    # print(idx, air_all)
                    if air_all:
                        # print(cidx)
                        sa_corner[cidx] = False
                    if sol_all:
                        sa_corner[cidx] = True

            # adjust singularities
            for idx in range(len(x_vert)):
                if corner_id[idx] != -1:
                    # print('corner: ', corner_id[idx], ' is Solid')
                    sa_corner[corner_id[idx]] = True

            # Due to approach that downward facing faces are forbiden, modify all point bellow.
            # If upper corner is solid and corner bellow is air, mark as solid
            if sa_corner[4]:
                sa_corner[0] = True
            if sa_corner[5]:
                sa_corner[1] = True
            if sa_corner[6]:
                sa_corner[2] = True
            if sa_corner[7]:
                sa_corner[3] = True

            # Loop over points, suspicious points are skipped
            #  Loop over direction and check if

            ii_new = [None for irun in range(10)]
            jj_new = [None for irun in range(10)]
            kk_new = [None for irun in range(10)]
            dir_new = [None for irun in range(10)]
            len_new = [None for irun in range(10)]
            x_vert_new = [None for irun in range(10)]
            y_vert_new = [None for irun in range(10)]
            z_vert_new = [None for irun in range(10)]
            ivert = 0
            for idx in range(len(x_vert)):
                if corner_id[idx] == -1:
                    x_vert_new[ivert] = x_vert[idx]
                    y_vert_new[ivert] = y_vert[idx]
                    z_vert_new[ivert] = z_vert[idx]

                    if 1 == 1:  # dirs[idx] == 6:
                        if np.abs(x_vert[idx] - self.cfg.domain.origin_x - ii[idx] * self.cfg.domain.dx) > 1.0e-8:
                            # lies on i-line, select which corner and look if air or solid -> create direction
                            f1 = False  # index if corner was found
                            for cidx in range(8):
                                if (ii[idx] == adj_corners[cidx, 2]) & (jj[idx] == adj_corners[cidx, 1]) & (
                                        kk[idx] == adj_corners[cidx, 0]):
                                    f1 = True
                                    break
                            cidx1 = cidx
                            f2 = False
                            for cidx in range(8):
                                if (ii[idx] + 1 == adj_corners[cidx, 2]) & (jj[idx] == adj_corners[cidx, 1]) & (
                                        kk[idx] == adj_corners[cidx, 0]):
                                    f2 = True
                                    break
                            cidx2 = cidx
                            f3 = False
                            for cidx in range(8):
                                if (ii[idx] - 1 == adj_corners[cidx, 2]) & (jj[idx] == adj_corners[cidx, 1]) & (
                                        kk[idx] == adj_corners[cidx, 0]):
                                    f3 = True
                                    break
                            cidx3 = cidx
                            if sa_corner[cidx1] and f1:
                                # corner is SOLID, take
                                ccidx = cidx1
                            elif sa_corner[cidx2] and f2:
                                # corner 2 is SOLID take corner 2
                                ccidx = cidx2
                            elif sa_corner[cidx3] and f3:
                                # corner 3 is SOLID, take
                                ccidx = cidx3
                            else:
                                verbose('Some issues with corner, [{},{},{}], [{},{},{}]', ii[idx], jj[idx], kk[idx], i,
                                        j, k)
                                sys.exit(1)
                            ii_new[ivert] = int(adj_corners[ccidx, 2])
                            jj_new[ivert] = int(adj_corners[ccidx, 1])
                            kk_new[ivert] = int(adj_corners[ccidx, 0])
                            len_new[ivert] = np.abs(
                                x_vert[idx] - self.cfg.domain.origin_x - ii_new[ivert] * self.cfg.domain.dx) / self.cfg.domain.dx
                            if x_vert[idx] - self.cfg.domain.origin_x > ii_new[ivert] * self.cfg.domain.dx:
                                dir_new[ivert] = 4
                            else:
                                dir_new[ivert] = 5
                        elif np.abs(y_vert[idx] - self.cfg.domain.origin_y - jj[idx] * self.cfg.domain.dy) > 1.0e-8:
                            # lies on j-line, select which corner and look if air or solid -> create direction
                            f1 = False
                            for cidx in range(8):
                                if (ii[idx] == adj_corners[cidx, 2]) & (jj[idx] == adj_corners[cidx, 1]) & (
                                        kk[idx] == adj_corners[cidx, 0]):
                                    f1 = True
                                    break
                            cidx1 = cidx
                            f2 = False
                            for cidx in range(8):
                                if (ii[idx] == adj_corners[cidx, 2]) & (jj[idx] + 1 == adj_corners[cidx, 1]) & (
                                        kk[idx] == adj_corners[cidx, 0]):
                                    f2 = True
                                    break
                            cidx2 = cidx
                            f3 = False
                            for cidx in range(8):
                                if (ii[idx] == adj_corners[cidx, 2]) & (jj[idx] - 1 == adj_corners[cidx, 1]) & (
                                        kk[idx] == adj_corners[cidx, 0]):
                                    f3 = True
                                    break
                            cidx3 = cidx
                            if sa_corner[cidx1] and f1:
                                # corner is SOLID, take
                                ccidx = cidx1
                            elif sa_corner[cidx2] and f2:
                                # corner 2 is SOLID take corner 2
                                ccidx = cidx2
                            elif sa_corner[cidx3] and f3:
                                # corner 3 is SOLID, take
                                ccidx = cidx3
                            else:
                                verbose('Some issues with corner, [{},{},{}], [{},{},{}]', ii[idx], jj[idx], kk[idx], i,
                                        j, k)
                                sys.exit(1)
                            ii_new[ivert] = int(adj_corners[ccidx, 2])
                            jj_new[ivert] = int(adj_corners[ccidx, 1])
                            kk_new[ivert] = int(adj_corners[ccidx, 0])
                            len_new[ivert] = np.abs(
                                y_vert[idx] - self.cfg.domain.origin_y - jj_new[ivert] * self.cfg.domain.dy) / self.cfg.domain.dy
                            if y_vert[idx] - self.cfg.domain.origin_y > jj_new[ivert] * self.cfg.domain.dy:
                                dir_new[ivert] = 2
                            else:
                                dir_new[ivert] = 3
                        elif z_vert[idx] - kk[idx] * self.cfg.domain.dz > 1.0e-8:
                            # lies on k-line, select which corner and look if air or solid -> create direction
                            for cidx in range(8):
                                if (ii[idx] == adj_corners[cidx, 2]) & (jj[idx] == adj_corners[cidx, 1]) & (
                                        kk[idx] == adj_corners[cidx, 0]):
                                    break
                            cidx1 = cidx
                            for cidx in range(8):
                                if (ii[idx] == adj_corners[cidx, 2]) & (jj[idx] == adj_corners[cidx, 1]) & (
                                        kk[idx] + 1 == adj_corners[cidx, 0]):
                                    break
                            cidx2 = cidx
                            if sa_corner[cidx1]:
                                # corner is SOLID, take
                                ccidx = cidx1
                            else:
                                # corner 1 is AIR take corner 2
                                ccidx = cidx2
                            ii_new[ivert] = int(adj_corners[ccidx, 2])
                            jj_new[ivert] = int(adj_corners[ccidx, 1])
                            kk_new[ivert] = int(adj_corners[ccidx, 0])
                            len_new[ivert] = np.abs(z_vert[idx] - kk_new[ivert] * self.cfg.domain.dz) / self.cfg.domain.dz
                            if z_vert[idx] > kk_new[ivert] * self.cfg.domain.dz:
                                dir_new[ivert] = 0
                            else:
                                dir_new[ivert] = 1
                    else:
                        ii_new[ivert] = int(ii[idx])
                        jj_new[ivert] = int(jj[idx])
                        kk_new[ivert] = int(kk[idx])
                        dir_new[ivert] = int(dirs[idx])
                        len_new[ivert] = lens[idx]
                    ivert += 1
                    continue
                interfaces = 0
                append_dirs = []
                for idir in range(3):
                    dirr = dir_corns[corner_id[idx], idir]

                    # is air cell in dir?
                    if not sa_corner[dirr]:
                        # print('there is Air cell', idx, corner_id[idx], dirr)
                        interfaces += 1
                        append_dirs.append(vert2dirs[corner_id[idx], idir])

                # add new vertex if interface > 1. case when interface == 1 is the already there
                for fidx in range(interfaces):
                    ii_new[ivert] = int(ii[idx])
                    jj_new[ivert] = int(jj[idx])
                    kk_new[ivert] = int(kk[idx])
                    x_vert_new[ivert] = x_vert[idx]
                    y_vert_new[ivert] = y_vert[idx]
                    z_vert_new[ivert] = z_vert[idx]
                    dir_new[ivert] = int(append_dirs[fidx])
                    len_new[ivert] = 0.0
                    ivert += 1

            n_vert = ivert

            # remove duplicates that has the same direction, but one has len0
            # or check if point is pointing to solid corner
            drop_idx = []
            for ivert in range(n_vert):
                if ii_new[ivert] is None:
                    drop_idx.append(ivert)
                    continue
                if ivert == 0:
                    ileft = n_vert - 1
                elif ivert == n_vert - 1:
                    ileft = ivert - 1
                else:
                    ileft = ivert - 1

                # check left
                if ii_new[ivert] == ii_new[ileft] and jj_new[ivert] == jj_new[ileft] and \
                        kk_new[ivert] == kk_new[ileft] and dir_new[ivert] == dir_new[ileft]:
                    # drop the one with zeros index
                    if len_new[ivert] == 0.0:
                        drop_idx.append(ivert)
                        # continue
                    else:
                        drop_idx.append(ileft)
                        # continue

                # check where point is pointing
                # idir = dir_new[ivert]
                # dirr = dirs_vect[idir]
                # ii_l, jj_l, kk_l = ii_new[ivert], jj_new[ivert], kk_new[ivert]
                # ii_t, jj_t, kk_t = ii_l + dirr[2], jj_l + dirr[1], kk_l + dirr[0]
                # cidx = np.argwhere(adj_corner == np.array([kk_t, jj_t, ii_t]))
                # if cidx.size > 0:
                #     verbose('Found corner that points to solid corner')
                # drop_idx.append(ivert)

            x_vert_n, y_vert_n, z_vert_n, ii_n, jj_n, kk_n, dir_n, len_n = [None for irun in range(10)], [None for irun
                                                                                                          in
                                                                                                          range(10)], [
                None for irun in range(10)], [None for irun in range(10)], [None for irun in range(10)], [None for irun
                                                                                                          in
                                                                                                          range(10)], [
                None for irun in range(10)], [None for irun in range(10)]
            irun = 0
            for ivert in range(n_vert):
                if not ivert in drop_idx:
                    x_vert_n[irun] = x_vert_new[ivert]
                    y_vert_n[irun] = y_vert_new[ivert]
                    z_vert_n[irun] = z_vert_new[ivert]
                    ii_n[irun] = ii_new[ivert]
                    jj_n[irun] = jj_new[ivert]
                    kk_n[irun] = kk_new[ivert]
                    dir_n[irun] = dir_new[ivert]
                    len_n[irun] = len_new[ivert]
                    irun += 1

            x_vert_new, y_vert_new, z_vert_new, ii_new, jj_new, kk_new, dir_new, len_new = x_vert_n, y_vert_n, z_vert_n, ii_n, jj_n, kk_n, dir_n, len_n
            x_vert_new[irun] = x_vert_new[0]
            y_vert_new[irun] = y_vert_new[0]
            z_vert_new[irun] = z_vert_new[0]
            ii_new[irun] = ii_new[0]
            jj_new[irun] = jj_new[0]
            kk_new[irun] = kk_new[0]
            dir_new[irun] = dir_new[0]
            len_new[irun] = len_new[0]

            n_vert = min([irun + 1, 7])
            # now delete old entry and create new entry
            to_delete.append(ids)
            to_insert.append((ids, k, j, i, n_vert,
                              wid, rid, lid,
                              isterr, iswall, isroof,
                              ii_new[0], ii_new[1], ii_new[2], ii_new[3], ii_new[4], ii_new[5], ii_new[6],
                              jj_new[0], jj_new[1], jj_new[2], jj_new[3], jj_new[4], jj_new[5], jj_new[6],
                              kk_new[0], kk_new[1], kk_new[2], kk_new[3], kk_new[4], kk_new[5], kk_new[6],
                              len_new[0], len_new[1], len_new[2], len_new[3], len_new[4], len_new[5], len_new[6],
                              dir_new[0], dir_new[1], dir_new[2], dir_new[3], dir_new[4], dir_new[5], dir_new[6],
                              norm[0], norm[1], norm[2], area,
                              center,
                              x_vert_new[0], y_vert_new[0], z_vert_new[0], self.cfg.srid_palm,
                              x_vert_new[1], y_vert_new[1], z_vert_new[1], self.cfg.srid_palm,
                              x_vert_new[2], y_vert_new[2], z_vert_new[2], self.cfg.srid_palm,
                              x_vert_new[3], y_vert_new[3], z_vert_new[3], self.cfg.srid_palm,
                              x_vert_new[4], y_vert_new[4], z_vert_new[4], self.cfg.srid_palm,
                              x_vert_new[5], y_vert_new[5], z_vert_new[5], self.cfg.srid_palm,
                              x_vert_new[6], y_vert_new[6], z_vert_new[6], self.cfg.srid_palm,))

        debug('Deleting all unwanted rows')
        # -- OPTIMIZE HERE
        sqltext = 'DELETE FROM "{0}"."{1}" ' \
                  'WHERE id = ANY(%s)'.format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
        self.execute(sqltext, (to_delete,))

        debug('Inserting all new entries into slanted faces table')
        sqltext = 'INSERT INTO "{0}"."{1}"  ' \
                  '   (id, k, j, i, n_vert, ' \
                  '    wid, rid, lid, ' \
                  '    isterr, iswall, isroof, ' \
                  '    ii1, ii2, ii3, ii4, ii5, ii6, ii7, ' \
                  '    jj1, jj2, jj3, jj4, jj5, jj6, jj7, ' \
                  '    kk1, kk2, kk3, kk4, kk5, kk6, kk7, ' \
                  '    len1, len2, len3, len4, len5, len6, len7, ' \
                  '    dir1, dir2, dir3, dir4, dir5, dir6, dir7, ' \
                  '    normz, normy, normx, area, ' \
                  '    center,  ' \
                  '    vert1, vert2, vert3, vert4, vert5, vert6, vert7) ' \
                  'VALUES (%s, %s, %s, %s, %s, ' \
                  '        %s, %s, %s, ' \
                  '        %s, %s, %s, ' \
                  '        %s, %s, %s, %s, %s, %s, %s, ' \
                  '        %s, %s, %s, %s, %s, %s, %s, ' \
                  '        %s, %s, %s, %s, %s, %s, %s, ' \
                  '        %s, %s, %s, %s, %s, %s, %s, ' \
                  '        %s, %s, %s, %s, %s, %s, %s, ' \
                  '        %s, %s, %s, %s, ' \
                  '        %s, ' \
                  '        ST_SetSRID(ST_MakePoint(%s, %s, %s), %s), ' \
                  '        ST_SetSRID(ST_MakePoint(%s, %s, %s), %s), ' \
                  '        ST_SetSRID(ST_MakePoint(%s, %s, %s), %s), ' \
                  '        ST_SetSRID(ST_MakePoint(%s, %s, %s), %s), ' \
                  '        ST_SetSRID(ST_MakePoint(%s, %s, %s), %s), ' \
                  '        ST_SetSRID(ST_MakePoint(%s, %s, %s), %s), ' \
                  '        ST_SetSRID(ST_MakePoint(%s, %s, %s), %s) ' \
                  '        )  '.format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)

        self.executemany(sqltext, to_insert)

        debug('Updating 3d polygon')
        sqltext = 'UPDATE "{0}"."{1}" SET geom =  ' \
                  'ST_ForceRHR(' \
                  'ST_SetSRID(ST_MakePolygon(ST_MakeLine(ARRAY[vert1, vert2, vert3, vert4, vert5, vert6, vert7,' \
                  '     CASE WHEN vert1 IS NOT NULL THEN vert1 ' \
                  '          WHEN vert2 IS NOT NULL THEN vert2 ' \
                  '          WHEN vert3 IS NOT NULL THEN vert3 ' \
                  '          WHEN vert4 IS NOT NULL THEN vert4 ' \
                  '          WHEN vert5 IS NOT NULL THEN vert5 ' \
                  '          WHEN vert6 IS NOT NULL THEN vert6 ' \
                  '          WHEN vert7 IS NOT NULL THEN vert7 END' \
                  '])), %s)) ' \
                  'WHERE geom IS NULL'.format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
        self.execute(sqltext, (self.cfg.srid_palm,))

    def slanted_surface_init(self):
        """ initialize slanted surfaces """
        self.preprocess_terrain_height()

        if self.cfg.has_buildings:
            self.preprocess_building_height()
            self.create_slanted_walls()
            self.calculate_aspect_slope()

        self.create_slanted_terrain()

        if self.cfg.has_buildings:
            self.create_slated_roof()

        # process slanted face into gridded form
        if self.cfg.has_buildings:
            self.create_grid_slanted_walls()

        self.create_grid_slanted_terrain()

        if self.cfg.has_buildings:
            self.create_grid_slanted_roof()

        self.initialize_slanted_faces()

        if self.cfg.has_buildings:
            self.merge_walls_terrain()
            self.merge_walls_roofs()

        # TODO: check if there triple duplicates wall/terrain/roof
        debug('add index on slanted geom')
        self.execute(
            f'create index slanted_face_geom_index on "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" using gist(geom)')

        # obtain number of vertices
        sqltext = f"""
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" set 
            n_vert = case when vert7 is not null then 7 
                          when vert6 is not null then 6 
                          when vert5 is not null then 5 
                          when vert4 is not null then 4 
                          when vert3 is not null then 3 
                          when vert2 is not null then 2 
                          when vert1 is not null then 1 end
        """
        self.execute(sqltext)

        # TODO: remove faces that are "under" terrain
        if self.cfg.domain.oro_min - self.cfg.domain.origin_z > 0:
            sqltext = f"""
                delete from "{self.cfg.domain.case_schema}"."{self.cfg.tables.slanted_faces}" 
                where iswall and (
                    st_z(vert1) = 0 or st_z(vert2) = 0 or st_z(vert3) = 0 or 
                    st_z(vert4) = 0 or st_z(vert5) = 0 or st_z(vert6) = 0 or st_z(vert7) = 0
                )
            """
            self.execute(sqltext)

        # calculate normal vector using triangulation
        self.normal_vector_trinagulation()

        self.create_integer_vertices()

        # TODO: find duplicates, there are some points with the same x,y,z
        self.check_for_vertex_singularities()