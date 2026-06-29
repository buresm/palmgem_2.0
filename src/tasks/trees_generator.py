from math import ceil
from .base import BaseTask
from src.logger import debug, progress, verbose, warning, error, sql_debug, sql_verbose
from src.utils.capabilities import ensure_capability_flags


class LadGenerator(BaseTask):
    def run(self):
        # has_trees is normally set by initialize_domain; re-derive it from the
        # schema for staged runs. Skip cleanly when there is no trees table so a
        # tree-free domain (or a misordered run) does not crash on max(treeh).
        ensure_capability_flags(self.cfg, self.db)
        if not self.cfg.has_trees:
            warning('no trees table in case schema; skipping leaf area density (LAD) generation')
            return
        self.process_trees()

    def process_trees(self):
        """
        processes individual tree point data into a 3d gridded structure,
        generating vertical layers for leaf area density (lad) and basal area density (bad).
        """
        progress('generating leaf area density (LAD) grid from tree points')

        # 1. create the trees_grid table based on the horizontal grid structure
        debug('creating new table trees_grid')
        sql_create = f"""
            create table "{self.cfg.domain.case_schema}"."{self.cfg.tables.trees_grid}" as
            select id, i, j
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}"
        """
        self.execute(sql_create)

        # 2. setup constraints and indices
        verbose('adding primary key and unique index to trees_grid')
        self.execute(f'alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.trees_grid}" add primary key (id)')
        self.execute(
            f'create unique index {self.cfg.tables.trees_grid}_i_j on "{self.cfg.domain.case_schema}"."{self.cfg.tables.trees_grid}" (i asc, j asc)')

        # 3. determine vertical canopy extent
        debug('calculating maximum tree height to define vertical resolution')
        res = self.execute(f'select max(treeh) from "{self.cfg.domain.case_schema}"."{self.cfg.tables.trees}"')
        thm = res[0][0] if res[0][0] is not None else 0

        # calculate number of vertical layers based on grid spacing (dz)
        nzlad = ceil(thm / self.cfg.domain.dz) + 1
        verbose(f'max tree height {thm} m -> {nzlad} vertical canopy layers (nzlad)')

        # 4. dynamically add lad and bad columns for each vertical level
        # keywords and types are strictly lower case
        debug('adding vertical density columns to trees_grid')
        if nzlad > 0:
            alter_parts = []
            for i in range(nzlad):
                alter_parts.append(f'add column "lad_{i}" double precision default 0')
                alter_parts.append(f'add column "bad_{i}" double precision default 0')

            sql_alter = f'alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.trees_grid}" {", ".join(alter_parts)}'
            self.execute(sql_alter)

        # 5. call the stored procedure to distribute tree properties into the grid
        progress('distributing tree properties into the 3d grid (palm_tree_grid)')
        sql_proc = "select palm_tree_grid(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        params = (
            self.cfg.domain.case_schema,
            self.cfg.tables.trees,
            self.cfg.tables.trees_grid,
            self.cfg.tables.grid,
            self.cfg.tables.buildings_grid,
            self.cfg.domain.dz,
            self.cfg.trees.nhv,
            self.cfg.trees.nump,
            self.cfg.trees.lad_reduction,
            self.cfg.trees.bad_coef,
            self.cfg.trees.ext_coef,
            self.cfg.logs.level_trees
        )

        self.execute(sql_proc, params)

        # 6. finalize ownership
        sql_owner = f'alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.trees_grid}" owner to {self.cfg.pg_owner}'
        self.execute(sql_owner)

        progress('LAD grid complete ({} vertical layers)', nzlad)
        return True


class LaiGenerator(BaseTask):
    def run(self):
        # skip cleanly when the LAI / canopy-height rasters are not present in the
        # case schema, rather than crashing on the raster intersection.
        if not self._lai_inputs_present():
            warning('lai / canopy_height rasters not in case schema; skipping LAI generation')
            return
        self.process_lai()

    def _lai_inputs_present(self):
        """True only if both rasters process_lai() reads exist in the case schema."""
        sql = ("select exists(select 1 from information_schema.tables "
               "where table_schema = %s and table_name = %s)")
        schema = self.cfg.domain.case_schema
        return all(
            self.fetchone(sql, (schema, table))
            for table in (self.cfg.tables.lai, self.cfg.tables.canopy_height)
        )

    def process_lai(self):
        """
        processes canopy data by intersecting the grid with lai and canopy height rasters,
        storing the result in the main grid table.
        """
        progress('processing LAI and canopy height onto the grid')
        debug('adding lai and canopy height columns into grid table')
        sql_init = f"""
            alter table "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}"
            add column if not exists lai double precision,
            add column if not exists canopy_height double precision
        """
        self.execute(sql_init)

        debug('intersecting grid with lai raster')
        # extracts lai values from raster tiles using grid point intersection
        # NOTE (perf): this lateral join does one raster lookup per grid point. On
        # large domains a set-based ST_Value over a clipped/mosaicked raster, or a
        # gist index on the raster tile_extent, would be substantially faster.
        sql_lai = f"""
            with lai_data as (
                select
                    lg.id as id,
                    r.val as lai_val
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" lg
                join lateral (
                    select st_value(rast, lg.point) as val
                    from "{self.cfg.domain.case_schema}"."{self.cfg.tables.lai}"
                    where st_intersects(tile_extent, lg.point)
                    limit 1
                ) r on true
            )
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" lg
            set lai = lai_data.lai_val * %s
            from lai_data
            where lai_data.id = lg.id
        """
        self.execute(sql_lai, (self.cfg.canopy.lai_mod,))

        debug('intersecting grid with canopy height raster')
        # extracts canopy height; values below 5.0m are ignored to filter low vegetation/noise
        sql_ch = f"""
            with ch_data as (
                select
                    lg.id as id,
                    r.val as height_val
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" lg
                join lateral (
                    select st_value(rast, lg.point) as val
                    from "{self.cfg.domain.case_schema}"."{self.cfg.tables.canopy_height}"
                    where st_intersects(tile_extent, lg.point)
                    limit 1
                ) r on true
            )
            update "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" lg
            set canopy_height = case when ch_data.height_val >= 5.0
                                     then ch_data.height_val * %s
                                     else 0.0 end
            from ch_data
            where ch_data.id = lg.id
        """
        self.execute(sql_ch, (self.cfg.canopy.canopy_height_mod,))

        progress('LAI / canopy height processing complete')
        return True
