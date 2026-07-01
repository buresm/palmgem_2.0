from .base import BaseTask
from src.logger import debug, extra_verbose, progress, verbose, warning, error, sql_debug, sql_verbose
import os
from netCDF4 import Dataset
import sys
from pathlib import Path
from datetime import datetime
import numpy as np
from math import ceil
from .share_utils import variable_visualization, create_slanted_vtk
from src.utils.capabilities import ensure_capability_flags, ensure_domain_geometry

class StaticDriverGen(BaseTask):
    """ task for generating the palm static driver netcdf file. """

    def run(self):
        """ """
        # Derive has_buildings / lod2 / ... and oro_min / origin_z from the schema
        # when this task runs on its own (staged run), so it does not require
        # initialize_domain in-process.
        ensure_capability_flags(self.cfg, self.db)
        ensure_domain_geometry(self.cfg, self.db)
        self.prepare_file()
        self.fill_file()
        self.finish_file()

    def prepare_file(self):
        """ Prepare netcdf file with dimension, attributes, ..."""
        self.nc_create_file(self.cfg.domain.static_driver_file)
        self.nc_write_global_attributes()
        self.nc_write_crs()
        self.create_dim_xy()

    def fill_file(self):
        """ Fill netcdf file with variables .... """
        self.write_terrain()

        # TODO: depricated
        if self.cfg.landcover.surface_fractions:
            warning('Surface fractions not implemented yet in PALM.')
            # self.write_surface_fractions()

        self.write_pavements()
        self.write_water()
        self.write_vegetation()
        self.write_soil()

        if not self.cfg.slurb:
            self.write_buildings_2d()

            if self.cfg.has_3d_buildings:
                self.write_buildings_3d()

            if self.cfg.lod2:
                self.test_building_insulation()

                if self.cfg.buildings_pars_depricated:
                    warning('You are using deprecated building pars!!!!!!')
                    self.write_building_pars_depricated()
                else:
                    self.write_building_pars()

                self.write_building_surface_pars()
                self.write_albedo_pars()

        if self.cfg.lod2:
            self.write_pavement_pars()
            self.write_subsurface_pars()
            self.write_water_pars()
            self.write_vegatation_pars()

        if self.cfg.has_trees:
            self.write_trees_grid()

        if self.cfg.canopy.using_lai:
            self.write_lad_grid()

        if not self.cfg.lod2 and self.cfg.prepare_albedo_type:
            self.write_albedo_pars_config()

        if self.cfg.slurb:
            self.write_mask_usm()

    def finish_file(self):
        self.check_consistency()
        self.ncfile.close()

    def nc_create_file(self, file):
        """
        initializes a new netcdf4 dataset. handles existing file cleanup
        and directory conflict checks before creation.
        """
        fp = Path(file)

        # 1. safety checks for existing paths
        if fp.exists():
            if fp.is_dir():
                error(f'error: {file} is an existing directory!')
                # notify system of failure via task state if applicable
                self.cfg.update_setting('nc_creation_status', 'failed_is_dir')
                sys.exit(1)
            else:
                debug(f'deleting existing file: {file}')
                fp.unlink()

        # 2. create the new dataset
        try:
            # keywords for format are kept lower case
            self.ncfile = Dataset(file, "w", format="NETCDF4")
            debug(f'created: {file}')
            self.cfg.update_setting('nc_last_created', str(fp))

        except FileNotFoundError:
            error(f'error: could not create file: {file}!')
            self.ncfile = None
            self.cfg.update_setting('nc_creation_status', 'failed_not_found')

    def nc_write_global_attributes(self):
        debug("Writing global attributes to file...")
        self.ncfile.setncattr('Conventions', "CF-1.7")
        self.ncfile.setncattr("origin_x", self.cfg.domain.origin_x)
        self.ncfile.setncattr("origin_y", self.cfg.domain.origin_y)
        self.ncfile.setncattr("origin_z", self.cfg.domain.origin_z)
        self.ncfile.setncattr("origin_time", self.cfg.origin_time)
        self.ncfile.setncattr("origin_lat", self.cfg.domain.origin_lat)
        self.ncfile.setncattr("origin_lon", self.cfg.domain.origin_lon)
        self.ncfile.setncattr("acronym", self.cfg.ncprops.acronym)
        self.ncfile.setncattr("author", self.cfg.ncprops.author)
        self.ncfile.setncattr("campaign", self.cfg.ncprops.campaign)
        self.ncfile.setncattr("contact_person", self.cfg.ncprops.contact_person)
        self.ncfile.setncattr("creation_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.ncfile.setncattr("comment", self.cfg.ncprops.comment)
        self.ncfile.setncattr("data_content", self.cfg.ncprops.data_content)
        self.ncfile.setncattr("dependencies", self.cfg.ncprops.dependencies)
        self.ncfile.setncattr("institution", self.cfg.ncprops.institution)
        self.ncfile.setncattr("keywords", self.cfg.ncprops.keywords)
        self.ncfile.setncattr("location", self.cfg.ncprops.location)
        self.ncfile.setncattr("palm_version", self.cfg.ncprops.palm_version)
        self.ncfile.setncattr("references", self.cfg.ncprops.references)
        self.ncfile.setncattr("rotation_angle", self.cfg.ncprops.rotation_angle)
        self.ncfile.setncattr("site", self.cfg.ncprops.site)
        self.ncfile.setncattr("source", self.cfg.ncprops.source)
        self.ncfile.setncattr("version", self.cfg.ncprops.version)

    def nc_write_crs(self):
        """
        extracts coordinate reference system information from the database
        and writes the corresponding attributes to the netcdf variable.
        """
        debug("Writing CRS to file...")

        # sql query is strictly lower case
        sql_crs = 'select srtext from "spatial_ref_sys" where srid = find_srid(%s, %s, %s)'

        # execute via task system
        res = self.execute(sql_crs, (self.cfg.domain.case_schema, self.cfg.tables.grid, 'geom'))
        srtext = res[0][0]

        # create netcdf variable
        temp = self.ncfile.createVariable("crs", "i")

        # default info (placeholders/fallbacks)
        temp.long_name = "coordinate reference system"
        temp.grid_mapping_name = "transverse_mercator"
        temp.semi_major_axis = 6378137.0
        temp.inverse_flattening = 298.257222101
        temp.longitude_of_prime_meridian = 0.0
        temp.longitude_of_central_meridian = 15.0
        temp.latitude_of_projection_origin = 0.0
        temp.scale_factor_at_central_meridian = 0.9996
        temp.false_easting = 500000.0
        temp.false_northing = 0.0
        temp.units = 'm'
        temp.epsg_code = 'EPSG: 25833'

        # parse projcs string for precise metadata
        try:
            proj = srtext.split(sep="PROJECTION[")[1]
            temp.grid_mapping_name = proj.split('],')[0].strip('"').lower().replace(" ", "_")

            # extract parameters
            params = proj.split('PARAMETER[')
            for i in range(1, len(params)):
                param = params[i].split(']')[0].split(',')
                param_key = param[0].strip('"')
                param_val = float(param[1].strip('"'))

                if param_key == 'latitude_of_origin':
                    temp.latitude_of_projection_origin = param_val
                elif param_key == 'scale_factor':
                    temp.scale_factor_at_central_meridian = param_val
                else:
                    temp.setncattr(param_key, param_val)

            # extract unit
            temp.units = proj.split('UNIT[')[1].split('],')[0].split(',')[0].strip('"')

            # extract authority (epsg)
            auths = proj.split('AUTHORITY[')
            auth = auths[len(auths) - 1].split(']')[0].split(',')
            authstr = f"{auth[0].replace('\"', '')}:{auth[1].replace('\"', '')}"
            temp.epsg_code = authstr

            # update task settings with the final crs
            self.cfg.update_setting('nc_crs_auth', authstr)

        except (IndexError, ValueError) as e:
            warning(f"could not fully parse srtext; using defaults. error: {e}")

        return temp

    def nc_create_dimension(self, dimname, dimlen):
        """
        creates a netcdf dimension in the active dataset.
        returns 0 on success or if the dimension already exists.
        """
        try:
            debug("Creating dimension {}", dimname)
            self.ncfile.createDimension(dimname, dimlen)
            return 0
        except Exception as e:
            # returns 0 to match previous logic, but logs the conflict
            verbose("Dimension {} already exists or failed to create: {}", dimname, e)
            return 0

    def nc_create_variable(self, var_name, precision, dims, fill_value=None):
        """
        creates a netcdf variable in the active dataset.
        returns the variable object regardless of whether it was just created or already exists.
        """
        try:
            # standard netcdf variable creation
            self.ncfile.createVariable(var_name, precision, dims, fill_value=fill_value)
        except Exception as e:
            verbose("Variable {} creation skipped (likely already exists): {}", var_name, e)
            pass
        return self.ncfile.variables[var_name]

    def create_var(self, var_name, v_type, dims, long_name='', units=''):
        """
        standardized helper to initialize a netcdf variable with standard
        palm-4u attributes including resolution and coordinate mapping.
        """
        # create variable using task's ncfile and config fill values
        self.ncfile.createVariable(
            var_name,
            v_type,
            dims,
            fill_value=self.cfg.fill_values[v_type]
        )

        # write mandatory metadata
        self.nc_write_attribute(var_name, 'long_name', long_name)
        self.nc_write_attribute(var_name, 'units', units)
        self.nc_write_attribute(var_name, 'res_orig', self.cfg.domain.dz)
        self.nc_write_attribute(var_name, 'coordinates', 'E_UTM N_UTM lon lat')

        # standardized to reference the 'crs' coordinate reference system variable
        self.nc_write_attribute(var_name, 'grid_mapping', 'crs')

        return True

    def nc_write_attribute(self, variable, attribute, value):
        """
        writes a metadata attribute to a specific variable if it doesn't already exist.
        """
        if not hasattr(self.ncfile[variable], attribute):
            var = self.ncfile.variables[variable]
            var.setncattr(attribute, value)
        return 0

    def create_dim_xy(self):
        """
        extracts grid coordinates and geographic metadata from the database
        and initializes the spatial dimensions and variables in the netcdf file.
        """
        # 1. extract 1d x and y coordinates relative to domain origin
        # sql queries are strictly lower case
        sql_x = f'select distinct xcen from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" order by xcen'
        res_x = self.execute(sql_x)
        x1d = [x[0] - self.cfg.domain.origin_x for x in res_x]

        sql_y = f'select distinct ycen from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" order by ycen'
        res_y = self.execute(sql_y)
        y1d = [y[0] - self.cfg.domain.origin_y for y in res_y]

        nxm, nym = len(x1d), len(y1d)

        # 2. write 1d coordinate variables (x, y)
        debug("Writing 2D variables x, y to file...")
        self.nc_create_dimension('x', nxm)
        self.nc_create_dimension('y', nym)

        vt_f8 = 'f8'
        temp_x = self.ncfile.createVariable('x', vt_f8, 'x')
        temp_y = self.ncfile.createVariable('y', vt_f8, 'y')
        temp_x[:] = x1d[:]
        temp_y[:] = y1d[:]
        del x1d, y1d

        self.nc_write_attribute('x', 'long_name', 'x')
        self.nc_write_attribute('x', 'standard_name', 'projection_x_coordinate')
        self.nc_write_attribute('x', 'units', 'm')
        self.nc_write_attribute('y', 'long_name', 'y')
        self.nc_write_attribute('y', 'standard_name', 'projection_y_coordinate')
        self.nc_write_attribute('y', 'units', 'm')

        # 3. transform and write 2d mapping variables (lon, lat, utm)
        debug("Writing 2D variables lon, lat, E_UTM, N_UTM to file...")
        sql_geo = f'select lon, lat, "E_UTM", "N_UTM" from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" order by j, i'
        res = self.execute(sql_geo)

        vt_f4 = 'f4'
        # longitude/latitude
        var_lon = self.ncfile.createVariable('lon', vt_f4, ('y', 'x'), fill_value=self.cfg.fill_values[vt_f4])
        var_lon[:, :] = np.reshape(np.asarray([x[0] for x in res], dtype=vt_f4), (nym, nxm))

        var_lat = self.ncfile.createVariable('lat', vt_f4, ('y', 'x'), fill_value=self.cfg.fill_values[vt_f4])
        var_lat[:, :] = np.reshape(np.asarray([x[1] for x in res], dtype=vt_f4), (nym, nxm))

        # utm coordinates
        var_e = self.ncfile.createVariable('E_UTM', vt_f8, ('y', 'x'), fill_value=self.cfg.fill_values[vt_f8])
        var_e[:, :] = np.reshape(np.asarray([x[2] for x in res], dtype=vt_f8), (nym, nxm))

        var_n = self.ncfile.createVariable('N_UTM', vt_f8, ('y', 'x'), fill_value=self.cfg.fill_values[vt_f8])
        var_n[:, :] = np.reshape(np.asarray([x[3] for x in res], dtype=vt_f8), (nym, nxm))
        del res

        # 4. assign attributes for geographic variables
        self.nc_write_attribute('lat', 'long_name', 'latitude')
        self.nc_write_attribute('lat', 'standard_name', 'latitude')
        self.nc_write_attribute('lat', 'units', 'degrees_north')

        self.nc_write_attribute('lon', 'long_name', 'longitude')
        self.nc_write_attribute('lon', 'standard_name', 'longitude')
        self.nc_write_attribute('lon', 'units', 'degrees_east')

        self.nc_write_attribute('E_UTM', 'long_name', 'easting')
        self.nc_write_attribute('E_UTM', 'standard_name', 'projection_x_coordinate')
        self.nc_write_attribute('E_UTM', 'units', 'm')

        self.nc_write_attribute('N_UTM', 'long_name', 'northing')
        self.nc_write_attribute('N_UTM', 'standard_name', 'projection_y_coordinate')
        self.nc_write_attribute('N_UTM', 'units', 'm')

        # 5. create any additional dimensions from configuration
        for name in self.cfg.ndims._settings.keys():
            d_len = self.cfg.ndims[name]
            self.nc_create_dimension(name, d_len)
            temp_dim = self.ncfile.createVariable(name, 'i', (name,))
            temp_dim[:] = np.arange(d_len)

    def write_type_variable(self, vn, vln, vt, fill, lod, sql_query=None, params=None):
        """
        standardized helper to create and fill a 2d netcdf classification variable.
        can take an optional sql_query to fetch results, or assume results are ready.
        """
        # execute query if provided, otherwise assume results are available from the last execute
        if sql_query:
            # sql_query is expected to be strictly lower case from the caller
            res_raw = self.execute(sql_query, params)
        else:
            raise ValueError(f"write_type_variable: sql_query is required for variable '{vn}'")

        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx

        # create the variable in self.ncfile
        self.ncfile.createVariable(vn, vt, ('y', 'x'), fill_value=fill[vt])

        # process results: handle nulls and convert to numpy array
        res = [fill[vt] if x[0] is None else x[0] for x in res_raw]
        var_data = np.reshape(np.asarray(res, dtype=vt), (ny, nx))
        del res_raw

        # ensure data sanity (no nans or infs)
        var_data = np.nan_to_num(
            var_data,
            copy=False,
            nan=fill[vt],
            posinf=fill[vt],
            neginf=fill[vt]
        )

        # write to netcdf
        self.ncfile[vn][...] = var_data

        # write standard attributes
        self.nc_write_attribute(vn, 'long_name', vln)
        self.nc_write_attribute(vn, 'units', '')
        self.nc_write_attribute(vn, 'res_orig', self.cfg.domain.dz)

        if lod is not None and lod != '' and lod != 0:
            self.nc_write_attribute(vn, 'lod', lod)

        self.nc_write_attribute(vn, 'coordinates', 'E_UTM N_UTM lon lat')
        self.nc_write_attribute(vn, 'grid_mapping', 'crs')  # standardized to crs variable

        debug(f'Variable {vn} ({vln}) has been written.')
        return True

    def write_terrain(self):
        """
        calculates and writes the topography height (zt) to the netcdf file,
        accounting for nesting adjustments relative to the domain origin.
        """
        nx = self.cfg.domain.nx
        ny = self.cfg.domain.ny

        # artificial adjustment: ensuring child and parent domains share a consistent origin
        if self.cfg.domain.origin_z > self.cfg.domain.oro_min:
            error(f'Origin z [{self.cfg.domain.origin_z} m] is higher than oro min [{self.cfg.domain.oro_min} m]')

        nesting_adjust = ceil((self.cfg.domain.oro_min - self.cfg.domain.origin_z) / self.cfg.domain.dz)

        # sql query is strictly lower case
        sql_topo = f'select (nz + %s) * %s from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" order by j, i'

        # execute via task system
        res = self.execute(sql_topo, (nesting_adjust, self.cfg.domain.dz))

        vn = 'zt'
        vt = 'f4'

        # create netcdf variable and populate with reshaped results
        var = self.ncfile.createVariable(vn, vt, ('y', 'x'), fill_value=self.cfg.fill_values[vt])
        var[:, :] = np.reshape(np.asarray([x[0] for x in res], dtype=vt), (ny, nx))
        del res

        # update task setting for terrain metadata
        self.cfg.update_setting('terrain_max_height', float(np.max(var)))

        # optional visual check
        if self.cfg.visual_check.enabled:
            variable_visualization(
                var=var,
                x=np.asarray(self.ncfile.variables['x']),
                y=np.asarray(self.ncfile.variables['y']),
                var_name=vn,
                par_id='',
                text_id='terrain_height',
                path=self.cfg.visual_check.path,
                show_plots=self.cfg.visual_check.show_plots
            )

        return True

    def write_surface_fractions(self):
        """
        writes surface fractions (vegetation, pavement, water) to the netcdf file.
        each fraction is stored as a layer in the 'surface_fraction' variable.
        """
        vn = 'surface_fraction'
        vt = 'f8'

        debug('Processing surface fractions')

        # 1. initialize the 3d variable (layers, y, x)
        # nsurface_fraction dimension should be defined in create_dim_xy or similar
        self.ncfile.createVariable(vn, vt, ('nsurface_fraction', 'y', 'x'), fill_value=self.cfg.fill_values[vt])

        self.nc_write_attribute(vn, 'long_name', 'Surface fractions 0 vegetation, 1 pavement, 2 water')
        self.nc_write_attribute(vn, 'units', '')
        self.nc_write_attribute(vn, 'res_orig', self.cfg.domain.dz)
        self.nc_write_attribute(vn, 'lod', 0)
        self.nc_write_attribute(vn, 'coordinates', 'E_UTM N_UTM lon lat')
        self.nc_write_attribute(vn, 'grid_mapping', 'crs')  # standardized to crs variable name

        # mapping of fraction index to grid column names
        fractions = [
            [0, 'veg_fraction'],
            [1, 'pav_fraction'],
            [2, 'wat_fraction']
        ]

        ny = self.cfg.domain.ny
        nx = self.cfg.domain.nx

        for it, col_name in fractions:
            verbose(f'Processing fraction index {it}: {col_name}')

            # sql query is strictly lower case
            sql_frac = f"""
                select 
                    case when g.{col_name} > 0.0 then g.{col_name} else 0.0 end 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g 
                order by g.j, g.i
            """

            res_raw = self.execute(sql_frac)

            # handle potential nulls and convert to numpy array
            res = [self.cfg.fill_values[vt] if x[0] is None else x[0] for x in res_raw]
            var_data = np.reshape(np.asarray(res, dtype=vt), (ny, nx))
            del res_raw

            # ensure data sanity (no nans or infs)
            var_data = np.nan_to_num(
                var_data,
                copy=False,
                nan=self.cfg.fill_values[vt],
                posinf=self.cfg.fill_values[vt],
                neginf=self.cfg.fill_values[vt]
            )

            # write the 2d slice into the 3d netcdf variable
            self.ncfile[vn][it, ...] = var_data

            # update setting for state tracking if needed
            self.cfg.update_setting(f'last_processed_{col_name}', float(np.mean(var_data)))

        debug(f'Variable {vn} (Surface fraction) has been written.')
        return True

    def write_pavements(self):
        """
        writes pavement types and their associated physical parameters (surface and subsurface)
        to the netcdf driver. handles both fraction-based and discrete landcover inputs.
        """
        vn = 'pavement_type'
        vt_b = 'b'

        # 1. process pavement types
        if self.cfg.landcover.surface_fractions:
            sql_type = f"""
                select 
                    case when g.pav_fraction > %s and g.pav_fract_type is not null 
                         then g.pav_fract_type - %s 
                         else null end
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g
                order by g.j, g.i
            """
            params = (self.cfg.landcover.min_fraction, self.cfg.type_range.pavement_min)
        else:
            sql_type = f"""
                select 
                    case when ic.id is not null then null else l.type - %s end 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l 
                    on l.lid = g.lid and l.type >= %s and l.type < %s
                left join impervious_correction ic on g.id = ic.id        
                order by g.j, g.i
            """
            params = (self.cfg.type_range.pavement_min, self.cfg.type_range.pavement_min,
                      self.cfg.type_range.pavement_max)

        # helper to write the classification variable
        self.write_type_variable(vn, 'pavement type', vt_b, self.cfg.fill_values, 0, sql_query=sql_type, params=params)

    def write_pavement_pars(self):
        """ LOD 2 option"""
        vt_f4 = 'f4'
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx
        # 2a. surface parameters (pavement_pars)
        vn_pars = "pavement_pars"
        self.nc_create_variable(vn_pars, vt_f4, ('npavement_pars', 'y', 'x'),
                                fill_value=self.cfg.fill_values[vt_f4])
        self.nc_write_attribute(vn_pars, 'long_name', 'pavement parameters')
        self.nc_write_attribute(vn_pars, 'units', '')
        self.nc_write_attribute(vn_pars, 'grid_mapping', 'crs')

        for par in self.cfg.pavement_pars._settings.keys():
            sql_p = f"""
                select case when l.type is not null then {self.cfg.pavement_pars[par]} else null end 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g    
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l 
                    on l.lid = g.lid and l.type >= %s and l.type < %s 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.surface_params}" p 
                    on p.code = l.catland 
                order by g.j, g.i
            """
            res_raw = self.execute(sql_p, (self.cfg.type_range.pavement_min, self.cfg.type_range.pavement_max))
            res = [self.cfg.fill_values[vt_f4] if x[0] is None else x[0] for x in res_raw]
            var_data = np.reshape(np.asarray(res, dtype=vt_f4), (ny, nx))
            var_data = np.nan_to_num(var_data, copy=False, nan=self.cfg.fill_values[vt_f4])
            self.ncfile.variables[vn_pars][par, ...] = var_data

    def write_subsurface_pars(self):
        # 2b. subsurface parameters (pavement_subsurface_pars)
        # setup soil vertical dimension
        vt_f4 = 'f4'
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx
        self.nc_create_dimension('zsoil', self.cfg.ground.nzsoil)
        zsoil_var = self.nc_create_variable('zsoil', vt_f4, ('zsoil',))

        zs = np.cumsum(self.cfg.ground.dz_soil)
        zsoil_var[:] = zs

        vn_sub = 'pavement_subsurface_pars'
        var_sub = self.nc_create_variable(vn_sub, vt_f4, ('npavement_subsurface_pars', 'zsoil', 'y', 'x'),
                                          fill_value=self.cfg.fill_values[vt_f4])
        self.nc_write_attribute(vn_sub, 'long_name', 'pavement subsurface parameters')

        # split layers into surface-influenced and deep soil
        lrange = [range(0, self.cfg.ground.nzsoil_surface),
                  range(self.cfg.ground.nzsoil_surface, self.cfg.ground.nzsoil)]

        for par in self.cfg.pavement_subsurface_pars._settings.keys():
            for k in range(2):  # 0: upper, 1: lower
                sql_sub = f"""
                    select case when l.type is not null then {self.cfg.pavement_subsurface_pars[par][k]} else null end 
                    from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g    
                    left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l 
                        on l.lid = g.lid and l.type >= %s and l.type < %s 
                    left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.surface_params}" p 
                        on p.code = l.catland 
                    order by g.j, g.i
                """
                res_raw = self.execute(sql_sub,
                                       (self.cfg.type_range.pavement_min, self.cfg.type_range.pavement_max))
                varp = np.reshape(np.asarray([x[0] for x in res_raw], dtype=vt_f4), (ny, nx))
                varp = np.nan_to_num(varp, copy=False, nan=self.cfg.fill_values[vt_f4])

                for p_idx in lrange[k]:
                    var_sub[par, p_idx, :, :] = varp
            debug(f'Variable {vn_sub}, parameter {par} written')

    def write_water(self):
        """
        writes water types and physical parameters to the netcdf driver.
        handles temperature initialization and additional lod2 surface parameters.
        """
        vn = "water_type"
        vt_b = 'b'
        vt_f4 = 'f4'
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx

        # 1. process water surface types
        if self.cfg.landcover.surface_fractions:
            # sql query is strictly lower case
            sql_type = f"""
                select 
                    case when g.wat_fraction > %s and g.wat_fract_type is not null 
                         then g.wat_fract_type - %s 
                         else null end
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g
                order by g.j, g.i
            """
            params = (self.cfg.landcover.min_fraction, self.cfg.type_range.water_min)
        else:
            sql_type = f"""
                select 
                    l.type - %s 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l 
                    on l.lid = g.lid and l.type >= %s and l.type < %s 
                order by g.j, g.i
            """
            params = (self.cfg.type_range.water_min, self.cfg.type_range.water_min, self.cfg.type_range.water_max)

        self.write_type_variable(vn, 'water type', vt_b, self.cfg.fill_values, 0, sql_query=sql_type, params=params)

        # 2. process water parameters (e.g., water body temperature)
        vn_pars = "water_pars"
        self.nc_create_variable(vn_pars, vt_f4, ('nwater_pars', 'y', 'x'), fill_value=self.cfg.fill_values[vt_f4])
        self.nc_write_attribute(vn_pars, 'long_name', 'water parameters')
        self.nc_write_attribute(vn_pars, 'units', '1')
        self.nc_write_attribute(vn_pars, 'res_orig', self.cfg.domain.dz)
        self.nc_write_attribute(vn_pars, 'grid_mapping', 'crs')

        # construct case statement for temperature based on type
        case_sql = 'case '
        for wtype, wtemp in self.cfg.water_pars_temp._settings.items():
            case_sql += f'when l.type = {wtype + self.cfg.type_range.water_min} then {wtemp} '
        case_sql += 'else null end'

        sql_temp = f"""
            select {case_sql} 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" as g 
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" as l 
                on l.lid = g.lid and l.type >= %s and l.type < %s 
            order by g.j, g.i
        """

        res_raw = self.execute(sql_temp, (self.cfg.type_range.water_min, self.cfg.type_range.water_max))
        res = [self.cfg.fill_values[vt_f4] if x[0] is None else x[0] for x in res_raw]
        var_data = np.reshape(np.asarray(res, dtype=vt_f4), (ny, nx))
        var_data = np.nan_to_num(var_data, copy=False, nan=self.cfg.fill_values[vt_f4])

        self.ncfile.variables[vn_pars][0, ...] = var_data
        debug(f'Variable {vn_pars}, parameter 0 written.')

    def write_water_pars(self):
        """ Write water pars """
        vt_f4 = 'f4'
        vn_pars = "water_pars"
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx
        for par in self.cfg.water_pars._settings.keys():
            sql_lod2 = f"""
                select 
                    case when l.type is not null then {self.cfg.water_pars[par]} else null end 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g    
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l 
                    on l.lid = g.lid and l.type >= %s and l.type < %s 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.surface_params}" p 
                    on p.code = l.catland 
                order by g.j, g.i
            """
            res_raw = self.execute(sql_lod2, (self.cfg.type_range.water_min, self.cfg.type_range.water_max))
            res = [self.cfg.fill_values[vt_f4] if x[0] is None else x[0] for x in res_raw]
            var_data = np.reshape(np.asarray(res, dtype=vt_f4), (ny, nx))
            var_data = np.nan_to_num(var_data, copy=False, nan=self.cfg.fill_values[vt_f4])

            self.ncfile.variables[vn_pars][par, ...] = var_data
            debug(f'Variable {vn_pars}, parameter {par} written.')

        return True

    def write_vegetation(self):
        """
        writes vegetation types and physical plant parameters to the netcdf driver.
        includes logic for landcover-to-vegetation correction based on imperviousness.
        """
        vn = "vegetation_type"
        vt_b = 'b'

        # 1. process vegetation surface types
        if self.cfg.landcover.surface_fractions:
            # sql query is strictly lower case
            sql_type = f"""
                select 
                    case when g.veg_fraction > %s and g.veg_fract_type is not null 
                         then g.veg_fract_type - %s 
                         else null end
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g
                order by g.j, g.i
            """
            params = (self.cfg.landcover.min_fraction, self.cfg.type_range.vegetation_min)
        else:
            # includes the impervious_correction temp table join
            sql_type = f"""
                select 
                    case when ic.id is not null then ic.new_type else l.type - %s end 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l 
                    on l.lid = g.lid and l.type >= %s and l.type < %s 
                left join impervious_correction ic on ic.id = g.id
                order by g.j, g.i
            """
            params = (
                self.cfg.type_range.vegetation_min,
                self.cfg.type_range.vegetation_min,
                self.cfg.type_range.vegetation_max
            )

        # helper handles variable creation and filling
        self.write_type_variable(vn, 'vegetation type', vt_b, self.cfg.fill_values, 0, sql_query=sql_type,
                                 params=params)

    def write_vegatation_pars(self):
        """ Write LOD2 vegatation parameters to the netcdf driver."""
        vt_f4 = 'f4'
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx
        vn_pars = "vegetation_pars"
        self.nc_create_variable(vn_pars, vt_f4, ('nvegetation_pars', 'y', 'x'),
                                fill_value=self.cfg.fill_values[vt_f4])
        self.nc_write_attribute(vn_pars, 'long_name', 'vegetation parameters')
        self.nc_write_attribute(vn_pars, 'units', '1')
        self.nc_write_attribute(vn_pars, 'res_orig', self.cfg.domain.dz)
        self.nc_write_attribute(vn_pars, 'grid_mapping', 'crs')

        for par in self.cfg.vegetation_pars._settings.keys():
            sql_p = f"""
                select 
                    case when l.type is not null then {self.cfg.vegetation_pars[par]} else null end 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g    
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l 
                    on l.lid = g.lid and l.type >= %s and l.type < %s 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.surface_params}" p 
                    on p.code = l.catland 
                order by g.j, g.i
            """
            res_raw = self.execute(sql_p, (self.cfg.type_range.vegetation_min, self.cfg.type_range.vegetation_max))

            # process results
            res = [self.cfg.fill_values[vt_f4] if x[0] is None else x[0] for x in res_raw]
            var_data = np.reshape(np.asarray(res, dtype=vt_f4), (ny, nx))
            var_data = np.nan_to_num(var_data, copy=False, nan=self.cfg.fill_values[vt_f4])

            self.ncfile.variables[vn_pars][par, ...] = var_data
            debug(f'Variable {vn_pars}, parameter {par} written')

            if self.cfg.visual_check.enabled:
                variable_visualization(
                    var=self.ncfile.variables[vn_pars][par, ...],
                    x=np.asarray(self.ncfile.variables['x']),
                    y=np.asarray(self.ncfile.variables['y']),
                    var_name=vn_pars,
                    par_id=par,
                    text_id='vegetation_pars',
                    path=self.cfg.visual_check.path,
                    show_plots=self.cfg.visual_check.show_plots
                )

    def write_soil(self):
        """
        writes soil types to the netcdf driver. handles soil classification
        for both vegetation and pavement surface categories.
        """
        vn = "soil_type"
        vt_b = 'b'

        # 1. process soil types
        # sql query is strictly lower case
        sql_soil = f"""
            select 
                case when l.type is not null then %s else null end 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g 
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l 
                on l.lid = g.lid and (
                    (l.type >= %s and l.type < %s) or 
                    (l.type >= %s and l.type < %s)
                ) 
            order by g.j, g.i
        """
        params = (
            self.cfg.ground.soil_type_default,
            self.cfg.type_range.vegetation_min, self.cfg.type_range.vegetation_max,
            self.cfg.type_range.pavement_min, self.cfg.type_range.pavement_max
        )

        # helper handles variable creation and filling
        self.write_type_variable(vn, 'soil type', vt_b, self.cfg.fill_values, 1, sql_query=sql_soil, params=params)

        if self.cfg.visual_check.enabled:
            variable_visualization(
                var=self.ncfile[vn],
                x=np.asarray(self.ncfile.variables['x']),
                y=np.asarray(self.ncfile.variables['y']),
                var_name=vn,
                par_id='',
                text_id='soil_type',
                path=self.cfg.visual_check.path,
                show_plots=self.cfg.visual_check.show_plots
            )

        # 2. soil moisture adjustments (custom extension)
        # rewritten and kept commented as requested
        # if self.cfg.lod2 and len(self.cfg.soil_moisture_adjust._settings) > 0:
        #     vn_sm = 'soil_moisture_adjust'
        #     vt_f4 = 'f4'
        #
        #     # construct calculation formula via strictly lower case sql
        #     sm_text = 'case '
        #     for lc in self.cfg.soil_moisture_adjust._settings:
        #         sm_text += f'when l."{self.cfg.landcover_params_var}" = {lc} then {self.cfg.soil_moisture_adjust._settings[lc]} '
        #     sm_text += 'else 1 end '
        #
        #     sql_sm = f"""
        #         select
        #             case when l.lid is not null then {sm_text} else null end
        #         from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g
        #         left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l
        #             on l.lid = g.lid and l.type >= %s and l.type < %s
        #         order by g.j, g.i
        #     """
        #
        #     self.write_type_variable(vn_sm, 'soil moisture adjust', vt_f4, self.cfg.fill_values, 0,
        #                              sql_query=sql_sm, params=(self.cfg.type_range.vegetation_min, self.cfg.type_range.vegetation_max))
        #
        #     if self.cfg.visual_check.enabled:
        #         variable_visualization(var=self.ncfile[vn_sm],
        #                                x=np.asarray(self.ncfile.variables['x']), y=np.asarray(self.ncfile.variables['y']),
        #                                var_name=vn_sm, par_id='', text_id='soil_moisture_adjust', path=self.cfg.visual_check.path,
        #                                show_plots=self.cfg.visual_check.show_plots)

    def write_buildings_2d(self):
        """
        writes building metadata, 2d heights, and 3d occupancy masks to the netcdf file.
        also handles surface type updates for grid cells located under 3d structures.
        """
        if self.cfg.force_lsm_only:
            return

        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx

        # 1. building_id
        sql_id = f"""
            select b.lid from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g 
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_grid}" b on b.id = g.id 
            order by g.j, g.i
        """
        self.write_type_variable('building_id', 'building_id', 'i', self.cfg.fill_values, 0, sql_query=sql_id)

        # 2. building_height (buildings_2d)
        sql_h = f"""
            select b.nz * %s from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g 
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_grid}" b on b.id = g.id 
            order by g.j, g.i
        """
        self.write_type_variable('buildings_2d', 'buildings_2d', 'f4', self.cfg.fill_values, 1,
                                 sql_query=sql_h, params=(self.cfg.domain.dz,))

        # 3. building_type
        sql_type = f"""
            select case when b.id is not null then 
                case when l.type >= %s and l.type < %s then l.type - %s 
                else 1 end else null end as type 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g 
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_grid}" b on b.id = g.id 
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l on l.lid = g.lid 
            order by g.j, g.i
        """
        params_type = (self.cfg.type_range.building_min, self.cfg.type_range.building_max,
                       self.cfg.type_range.building_min)
        self.write_type_variable('building_type', 'building_type', 'b', self.cfg.fill_values, 0,
                                 sql_query=sql_type, params=params_type)

    def write_buildings_3d(self):
        """ Write bridges, passages and overhanging structures. """
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx
        debug('Writing buildings_3d into static driver')

        sql_max_z = f'select max(nz) from "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_grid}"'
        max_nz = int(self.execute(sql_max_z)[0][0]) + 1

        # create z dimension and variable
        self.nc_create_dimension('z', max_nz)
        z_var = self.ncfile.createVariable('z', 'f4', ('z',))
        z_var[:] = np.append(0, np.arange(self.cfg.domain.dz / 2.0, (max_nz - 1) * self.cfg.domain.dz,
                                          self.cfg.domain.dz))
        self.nc_write_attribute('z', 'standard_name', 'projection_z_coordinate')
        self.nc_write_attribute('z', 'units', 'm')

        vn_3d = 'buildings_3d'
        vt_b = 'b'
        var_nc_3d = self.ncfile.createVariable(vn_3d, vt_b, ('z', 'y', 'x'), fill_value=self.cfg.fill_values[vt_b])
        self.nc_write_attribute(vn_3d, 'flag_meanings', 'no building, building')
        self.nc_write_attribute(vn_3d, 'lod', 2)

        # process top and bottom heights for 3d voxelization
        sql_top = f"""
            select b.nz from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g 
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_grid}" b on b.id = g.id 
            order by g.j, g.i
        """
        res_top = self.execute(sql_top)
        var_top = np.reshape(np.asarray([0 if x[0] is None else x[0] for x in res_top], dtype='i4'), (ny, nx))

        sql_bot = f"""
            select case when b.is_bridge or b.has_bottom then b.nz_min else 0 end 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g 
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_grid}" b on b.id = g.id 
            order by g.j, g.i
        """
        res_bot = self.execute(sql_bot)
        var_bottom = np.reshape(np.asarray([0 if x[0] is None else x[0] for x in res_bot], dtype='i4'), (ny, nx))

        # build 3d occupancy array
        var_3d = np.zeros((max_nz, ny, nx), dtype='i1')
        for j in range(ny):
            for i in range(nx):
                # +1 to handle index-to-level mapping
                var_3d[var_bottom[j, i] + 1: var_top[j, i] + 1, j, i] = 1

        # apply ground-level logic for buildings
        var_3d[0, :, :] = var_3d[1, :, :]

        sql_bot_check = f"""
            select case when (b.is_bridge or b.has_bottom) and b.nz = 0 then true else false end 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g 
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_grid}" b on b.id = g.id 
            order by g.j, g.i
        """
        res_check = self.execute(sql_bot_check)
        mask_ground = np.reshape(np.asarray([False if x[0] is None else x[0] for x in res_check], dtype='bool'),
                                 (ny, nx))
        var_3d[0, mask_ground] = 1

        var_nc_3d[:] = var_3d
        debug('Variable buildings 3d has been written')

        # 5. update surface types under 3d structures
        sql_under = f"""
            select ub.j, ub.i, ux.typed from "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_grid}" ub 
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.extras_shp}" ux on ux.gid = ub.lid_extra 
            where ub.under 
            order by ub.j, ub.i
        """
        res_under = self.execute(sql_under)
        for j, i, typeu in res_under:
            if self.cfg.type_range.pavement_min < typeu < self.cfg.type_range.pavement_max:
                self.ncfile.variables['pavement_type'][j, i] = typeu - self.cfg.type_range.pavement_min
                self.ncfile.variables['soil_type'][j, i] = self.cfg.ground.soil_type_default
            elif self.cfg.type_range.vegetation_min < typeu < self.cfg.type_range.vegetation_max:
                self.ncfile.variables['vegetation_type'][j, i] = typeu - self.cfg.type_range.vegetation_min
                self.ncfile.variables['soil_type'][j, i] = self.cfg.ground.soil_type_default
            elif self.cfg.type_range.water_min < typeu < self.cfg.type_range.water_max:
                self.ncfile.variables['water_type'][j, i] = typeu - self.cfg.type_range.water_min
            else:
                warning(f'unknown type {typeu} under 3d structure at [j,i] = [{j},{i}]')

        # 6. pavement parameters under 3d structures (placeholder logic)
        # if self.cfg.landcover_params_var:
        #     for par in self.cfg.pavement_pars._settings.keys():
        #         sql_p_under = f"""
        #             select br.j, br.i, {self.cfg.pavement_pars[par]}
        #             from "{self.cfg.domain.case_schema}"."{self.cfg.tables.bridge_grid}" br
        #             left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.bridge_shp}" l
        #                 on l.lid = br.lid and l.typed >= %s and l.typed < %s
        #             left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.surface_params}" p
        #                 on p.code = l."{self.cfg.landcover_params_var}d"
        #             where br.under
        #             order by br.j, br.i
        #         """
        #         res_p_under = self.execute(sql_p_under, (self.cfg.type_range.pavement_min, self.cfg.type_range.pavement_max))
        #         for j, i, ty in res_p_under:
        #             self.ncfile.variables['pavement_pars'][par, j, i] = ty

    def prepared_lad_netcdf(self, nzlad):
        """
        prepares vertical dimensions and 3d variables for leaf and basal area density.
        defines the 'zlad' staggered grid used for resolved vegetation.
        """
        vt = 'f4'
        debug('Creating zlad dimension and variables')

        # 1. calculate staggered vertical grid for lad
        # zlad[0] is at the surface, subsequent levels are at cell centers
        zlad = [0.0] + [x * self.cfg.domain.dz + 0.5 * self.cfg.domain.dz for x in range(nzlad)]

        self.nc_create_dimension('zlad', nzlad + 1)
        temp_z = self.ncfile.createVariable('zlad', vt, ('zlad',))
        temp_z[:] = zlad[:]

        # 2. initialize lad variable (leaf area density)
        vn_lad = 'lad'
        var_lad = self.ncfile.createVariable(vn_lad, vt, ('zlad', 'y', 'x'), fill_value=self.cfg.fill_values[vt])

        self.nc_write_attribute(vn_lad, 'long_name', 'leaf area density')
        self.nc_write_attribute(vn_lad, 'units', 'm2/m3')
        self.nc_write_attribute(vn_lad, 'res_orig', self.cfg.domain.dz)
        self.nc_write_attribute(vn_lad, 'coordinates', 'E_UTM N_UTM lon lat')
        self.nc_write_attribute(vn_lad, 'grid_mapping', 'crs')

        # 3. initialize bad variable (basal area density)
        vn_bad = 'bad'
        var_bad = self.ncfile.createVariable(vn_bad, vt, ('zlad', 'y', 'x'), fill_value=self.cfg.fill_values[vt])

        self.nc_write_attribute(vn_bad, 'long_name', 'branch area density')
        self.nc_write_attribute(vn_bad, 'units', 'm3/m3')
        self.nc_write_attribute(vn_bad, 'res_orig', self.cfg.domain.dz)
        self.nc_write_attribute(vn_bad, 'coordinates', 'E_UTM N_UTM lon lat')
        self.nc_write_attribute(vn_bad, 'grid_mapping', 'crs')

        return True

    def write_lad_grid(self):
        """
        writes lad and bad fields into netcdf based on canopy parameters from the grid table.
        calculates vertical distribution using a database-side least/greatest formula.
        """
        # 1. determine max canopy height to define the vertical dimension
        # sql query is strictly lower case
        sql_max_h = f'select max(canopy_height) from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}"'
        ret = self.execute(sql_max_h)

        if not ret or ret[0][0] is None or ret[0][0] == 0:
            debug("No canopy height data found in grid. Skipping lad_grid generation.")
            return True

        nzlad = ceil(ret[0][0] / self.cfg.domain.dz) + 1
        debug(f'nzlad = {nzlad}')

        vt = 'f4'
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx

        # 2. prepare netcdf dimensions and variables (zlad, lad, bad)
        self.prepared_lad_netcdf(nzlad)

        # 3. initialize surface level (k=0) to zero as per palm-4u requirements
        self.ncfile.variables['lad'][0, :, :] = 0.0
        self.ncfile.variables['bad'][0, :, :] = 0.0

        # 4. vertical loop to fill each layer of the canopy
        for nz in range(1, nzlad + 1):
            verbose(f'Processing lad layer nz: {nz}')

            # calculation parameters
            z_lower = (nz - 1) * self.cfg.domain.dz
            z_upper = nz * self.cfg.domain.dz
            z_center = (nz - 0.5) * self.cfg.domain.dz
            dz = self.cfg.domain.dz

            # sql query is strictly lower case
            # formula: calculates density based on lai/height ratio and vertical overlap
            sql_layer = f""" 
                select 
                    case when {z_center} between 0.0 and g.canopy_height and g.canopy_height > 0
                            then least(1.6, coalesce(lai / canopy_height, 0.0)) * greatest(0.0, least((canopy_height - {z_lower}) / {dz}, 1.0))
                        else 0.0 end
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g
                order by g.j, g.i
            """

            res_raw = self.execute(sql_layer)

            # reshape and write to netcdf
            lad_layer = np.reshape(np.asarray([x[0] for x in res_raw], dtype=vt), (ny, nx))
            self.ncfile.variables['lad'][nz, :, :] = lad_layer

            # branch area density is assumed to be 10% of lad
            bad_layer = 0.1 * lad_layer
            self.ncfile.variables['bad'][nz, :, :] = bad_layer

        debug(f'Variable lad and bad (grid-based) have been written for {nzlad} layers.')
        return True

    def write_trees_grid(self):
        """
        routine to generate resolved vegetation.
        extracts lad and bad profiles from the database and maps them to the 3d netcdf grid.
        """

        # 1. determine max height to define vertical grid size
        # sql query is strictly lower case
        sql_max_h = f'select max(treeh) from "{self.cfg.domain.case_schema}"."{self.cfg.tables.trees}"'
        ret = self.execute(sql_max_h)

        if not ret or ret[0][0] is None:
            debug("No trees found in the domain. Skipping tree grid generation.")
            return True

        nzlad = ceil(ret[0][0] / self.cfg.domain.dz) + 1
        debug(f'nzlad = {nzlad}')

        vt = 'f4'
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx
        lad_local = np.zeros((nzlad, ny, nx), dtype=vt)
        bad_local = np.zeros((nzlad, ny, nx), dtype=vt)

        # 2. construct dynamic query for all lad/bad layers
        # sql query is strictly lower case
        cols = ['i', 'j']
        for l in range(nzlad):
            cols.append(f'lad_{l}')
            cols.append(f'bad_{l}')

        col_str = ", ".join(cols)
        sql_trees = f'select {col_str} from "{self.cfg.domain.case_schema}"."{self.cfg.tables.trees_grid}"'

        tree_data = self.execute(sql_trees)

        # 3. populate local arrays from database records
        for row in tree_data:
            i, j = row[0], row[1]
            extra_verbose(f'tree cell: [j, i] = [{j}, {i}]')
            for l in range(nzlad):
                # mapping: lad is at index 2*l + 2, bad is at 2*l + 3
                lad_local[l, j, i] += row[2 * l + 2]
                bad_local[l, j, i] += row[2 * l + 3]

        # 4. prepare netcdf dimensions and variables
        self.prepared_lad_netcdf(nzlad)

        # 5. write to netcdf variables
        # palm requires lad/bad at k=0 (surface) to be 0
        self.ncfile.variables['lad'][1:, :, :] = lad_local
        self.ncfile.variables['bad'][1:, :, :] = bad_local

        self.ncfile.variables['lad'][0, :, :] = 0.0
        self.ncfile.variables['bad'][0, :, :] = 0.0

        # 6. optional visual validation
        if self.cfg.visual_check.enabled:
            for k in range(nzlad):
                variable_visualization(
                    var=self.ncfile['lad'][k, ...],
                    x=np.asarray(self.ncfile.variables['x']),
                    y=np.asarray(self.ncfile.variables['y']),
                    var_name='lad',
                    par_id=k,
                    text_id='leaf_area_density',
                    path=self.cfg.visual_check.path,
                    show_plots=self.cfg.visual_check.show_plots
                )
                variable_visualization(
                    var=self.ncfile['bad'][k, ...],
                    x=np.asarray(self.ncfile.variables['x']),
                    y=np.asarray(self.ncfile.variables['y']),
                    var_name='bad',
                    par_id=k,
                    text_id='trunk_area_density',
                    path=self.cfg.visual_check.path,
                    show_plots=self.cfg.visual_check.show_plots
                )

        return True

    def write_albedo_pars_config(self):
        """
        writes albedo parameters for different surface types and building fractions.
        processes broadband, longwave, and shortwave albedos from configuration settings.
        """
        debug('Processing albedo pars from config')
        vn = 'albedo_pars'
        vt = 'f4'
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx

        # create the 3d variable (nalbedo_pars, y, x)
        var = self.ncfile.createVariable(vn, vt, ('nalbedo_pars', 'y', 'x'), fill_value=self.cfg.fill_values[vt])
        self.nc_write_attribute(vn, 'long_name', 'building parameters')
        self.nc_write_attribute(vn, 'units', '')
        self.nc_write_attribute(vn, 'res_orig', self.cfg.domain.dz)
        self.nc_write_attribute(vn, 'coordinates', 'E_UTM N_UTM lon lat')
        self.nc_write_attribute(vn, 'grid_mapping', 'crs')

        # mapping of parameter index to radiation type and building component
        pars = [
            [0, 'broadband', 'wall'],
            [1, 'longwave', 'wall'],
            [2, 'shortwave', 'roof'],
            [3, 'longwave', 'win_wall'],
            [4, 'shortwave', 'win_roof'],
            [5, 'longwave', 'green_wall'],
            [6, 'shortwave', 'green_roof']
        ]

        for par, rad_type, build_case in pars:
            debug(f"processing albedo pars from config {par}, {rad_type}, {build_case}")

            # start case statement - sql must be lower case
            sql_case = 'case '

            # vegetation albedos
            for veg_type in self.cfg.vegetation_type_albedos._settings.keys():
                v_id = veg_type + self.cfg.type_range.vegetation_min
                v_val = self.cfg.vegetation_type_albedos[veg_type][rad_type]
                sql_case += f'when l.type = {v_id} then {v_val} '

            # pavement albedos
            for pav_type in self.cfg.pavement_type_albedos._settings.keys():
                p_id = pav_type + self.cfg.type_range.pavement_min
                p_val = self.cfg.pavement_type_albedos[pav_type][rad_type]
                sql_case += f'when l.type = {p_id} then {p_val} '

            # water albedos
            for wat_type in self.cfg.water_type_albedos._settings.keys():
                w_id = wat_type + self.cfg.type_range.water_min
                w_val = self.cfg.water_type_albedos[wat_type][rad_type]
                sql_case += f'when l.type = {w_id} then {w_val} '

            # building albedos
            for build_type in self.cfg.building_type_albedos._settings.keys():
                b_id = build_type + self.cfg.type_range.building_min
                b_val = self.cfg.building_type_albedos[build_type][build_case][rad_type]
                sql_case += f'when l.type = {b_id} then {b_val} '

            sql_case += 'else 0 end'

            # final sql query in lower case
            sql_albedo = f"""
                select 
                    distinct on (g.i, g.j) 
                    {sql_case}
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g
                join "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l on l.lid = g.lid
                order by g.j, g.i
            """

            res_raw = self.execute(sql_albedo)

            # reshape and sanitize data
            var_data = np.reshape(np.asarray([x[0] for x in res_raw], dtype=vt), (ny, nx))
            var[par, :, :] = np.nan_to_num(
                var_data,
                copy=False,
                nan=self.cfg.fill_values[vt],
                posinf=self.cfg.fill_values[vt],
                neginf=self.cfg.fill_values[vt]
            )

            debug(f'Variable {vn}, parameter {par} written.')

            if self.cfg.visual_check.enabled:
                variable_visualization(
                    var=var[par, ...],
                    x=np.asarray(self.ncfile.variables['x']),
                    y=np.asarray(self.ncfile.variables['y']),
                    var_name=vn,
                    par_id=par,
                    text_id='albedo_type',
                    path=self.cfg.visual_check.path,
                    show_plots=self.cfg.visual_check.show_plots
                )

        debug(f'Variable {vn} completely written.')
        return True

    def test_building_insulation(self):
        """
        tests for the existence of insulation columns in the walls table.
        updates the configuration state to guide subsequent building parameter processing.
        """
        # initialize the existence list in the config
        self.cfg.insulation._settings['exists'] = []
        debug('Testing buildings insulation fields in database schema')

        for f in self.cfg.insulation.fields:
            # sql query is strictly lower case
            sql_check = """
                select exists (
                    select 1 from information_schema.columns 
                    where table_schema = %s 
                    and table_name = %s 
                    and column_name = %s
                )
            """

            # execute using the task's execution wrapper
            res = self.execute(sql_check, (self.cfg.domain.case_schema, self.cfg.tables.walls, f))

            # append the boolean result to the config
            exists = res[0][0]
            self.cfg.insulation.exists.append(exists)
            verbose(f"Field '{f}' exists: {exists}")

        return True

    def correct_win_frac(self, vn, ipar_wi, ipar_wa, limit=0.95):
        """
        checks if window fraction exceeds the physical limit and adjusts
        the corresponding wall fraction to ensure a consistent surface sum of 1.0.
        """
        # create a boolean mask for cells exceeding the limit
        # ncfile.variables is the standard palm-4u netcdf variable access
        win_data = self.ncfile.variables[vn][ipar_wi, ...]
        mask = win_data > limit

        if np.any(mask):
            count = np.count_nonzero(mask)
            wall_val = round(1.0 - limit, 2)

            verbose(f'Modifying winfrac in {vn} where winfrac > {limit} ({count} cells). '
                    f'Setting winfrac = {limit} and wallfrac = {wall_val}')

            # apply corrections via 2-D numpy layers, then write each layer back
            # whole: netCDF4 rejects a scalar index combined with a 2-D boolean
            # mask (var[ipar, mask2d] -> "index cannot be multidimensional").
            win_data[mask] = limit
            self.ncfile.variables[vn][ipar_wi, ...] = win_data

            wall_data = self.ncfile.variables[vn][ipar_wa, ...]
            wall_data[mask] = wall_val
            self.ncfile.variables[vn][ipar_wa, ...] = wall_data

        return True

    def write_building_pars_depricated(self):
        """
        writes building parameters (roof and wall properties) to netcdf.
        integrates green fraction replacements and building insulation logic.
        """
        vn = 'building_pars'
        vt = 'f4'
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx

        # create 3d variable
        self.nc_create_variable(vn, vt, ('nbuilding_pars', 'y', 'x'), fill_value=self.cfg.fill_values[vt])
        self.nc_write_attribute(vn, 'long_name', 'building parameters')
        self.nc_write_attribute(vn, 'units', '')
        self.nc_write_attribute(vn, 'res_orig', self.cfg.domain.dz)
        self.nc_write_attribute(vn, 'coordinates', 'E_UTM N_UTM lon lat')
        self.nc_write_attribute(vn, 'grid_mapping', 'crs')

        # process individual parameters from configuration
        for par in self.cfg.building_pars._settings.keys():
            extra_verbose(f'Processing buildings pars, par index: {par}')

            # 1. handle green fraction replacements (sql must be lower case)
            if par in self.cfg.building_pars_repl._settings.keys():
                repl = self.cfg.building_pars_repl[par]
                g_text = 'case '
                for gf in repl:
                    g_text += f'when p.code = {gf[0]} then {gf[1]} '
                g_text += f'else {self.cfg.building_pars[par]} end '
            else:
                g_text = f'{self.cfg.building_pars[par]} '

            # 2. handle insulation logic (sql must be lower case)
            if self.cfg.insulation.enabled and par in self.cfg.insulation.building_pars:
                idx = self.cfg.insulation.building_pars.index(par)
                field_exists = self.cfg.insulation.exists[self.cfg.insulation.pars_fields[idx]]

                if field_exists:
                    col_name = self.cfg.insulation.fields[self.cfg.insulation.pars_fields[idx]]
                    val_insul = self.cfg.insulation.values[self.cfg.insulation.pars_items[idx]]
                    i_text = f'case when "{col_name}" <> 0 then {val_insul} else {g_text} end '
                else:
                    i_text = f'{g_text} '
            else:
                i_text = f'{g_text} '

            # 3. construct final sql query (strictly lower case)
            p_text = f'case when b.id is not null then {i_text} else null end'

            sql_building = f"""
                select distinct on (g.i, g.j) 
                    {p_text} 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_grid}" b on b.id = g.id 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.roofs}" r on r.{self.cfg.idx.roofs} = b.rid 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.surface_params}" p on p.code = cast(r.material as integer) + %s 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.building_walls}" bw on bw.id = g.id and not bw.isroof 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.walls}" w on w.{self.cfg.idx.walls} = bw.wid 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.surface_params}" pg on pg.code = w.wallcatd 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.surface_params}" pu on pu.code = w.wallcatu 
                order by g.j, g.i
            """

            res_raw = self.execute(sql_building, (self.cfg.surf_range.roof_min,))

            # reshape and sanitize
            var_data = np.reshape(np.asarray([x[0] for x in res_raw], dtype=vt), (ny, nx))
            var_data = np.nan_to_num(var_data, copy=False, nan=self.cfg.fill_values[vt])

            self.ncfile.variables[vn][par, ...] = var_data
            debug(f'Variable {vn}, parameter {par} written.')

            if self.cfg.visual_check.enabled:
                variable_visualization(
                    var=self.ncfile.variables[vn][par, ...],
                    x=np.asarray(self.ncfile.variables['x']),
                    y=np.asarray(self.ncfile.variables['y']),
                    var_name=vn, par_id=par, text_id='building_pars',
                    path=self.cfg.visual_check.path, show_plots=self.cfg.visual_check.show_plots
                )

        # 4. physical consistency check: window fraction capping
        # indexes 1 and 22 are typically window fractions in palm-4u
        # NOTE: netCDF4 cannot mix a scalar index with a 2-D boolean mask
        # (var[idx, mask2d] -> "index cannot be multidimensional"); read each
        # (y, x) layer into a numpy array, mask there, then write it back whole.
        for idx_win, idx_wall in [(1, 0), (22, 21)]:
            win_layer = self.ncfile.variables[vn][idx_win, ...]
            win_mask = win_layer > 0.95
            if np.any(win_mask):
                verbose(f'Capping window fraction at 0.95 for parameter index {idx_win}')
                win_layer[win_mask] = 0.95
                self.ncfile.variables[vn][idx_win, ...] = win_layer

                wall_layer = self.ncfile.variables[vn][idx_wall, ...]
                wall_layer[win_mask] = 0.05
                self.ncfile.variables[vn][idx_wall, ...] = wall_layer

        debug(f'Variable {vn} completely written.')
        return True

    def write_building_pars(self):
        """
        writes building physical parameters according to pids (palm input data standard).
        covers albedo, emissivity, thermal properties, and multi-layer wall/roof structures.
        """
        progress('Filling building parameters (PIDS standard)')
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx
        vt = 'f4'

        # 1. building albedo type
        vn = 'building_albedo_type'
        debug(f'Processing var: {vn}')
        self.create_var(vn, vt, ('building_surface_type', 'y', 'x'), long_name='building albedo type')
        for par in self.cfg[vn]._settings.keys():
            nc_var = self.fetch_building_parameters(vn, par, self.cfg[vn][par], vt)
            self.ncfile.variables[vn][par, :, :] = nc_var

        # 2. building emissivity
        vn = 'building_emissivity'
        debug(f'Processing var: {vn}')
        self.create_var(vn, vt, ('building_surface_type', 'y', 'x'), long_name='building emissivity')
        for par in self.cfg[vn]._settings.keys():
            nc_var = self.fetch_building_parameters(vn, par, self.cfg[vn][par], vt)
            self.ncfile.variables[vn][par, ...] = nc_var

        # check window fraction limits for surface types (e.g., window vs wall fractions)
        self.correct_win_frac(vn, 0, 3)
        self.correct_win_frac(vn, 1, 4)
        self.correct_win_frac(vn, 2, 5)

        # 3. building fraction
        vn = 'building_fraction'
        debug(f'Processing var: {vn}')
        self.create_var(vn, vt, ('building_surface_type', 'y', 'x'), long_name='building surface fraction')
        for par in self.cfg[vn]._settings.keys():
            nc_var = self.fetch_building_parameters(vn, par, self.cfg[vn][par], vt)
            self.ncfile.variables[vn][par, ...] = nc_var

        # 4. building general pars (non-surface specific)
        vn = 'building_general_pars'
        debug(f'Processing var: {vn}')
        self.create_var(vn, vt, ('building_general_par', 'y', 'x'), long_name='building general pars')
        for par in self.cfg[vn]._settings.keys():
            nc_var = self.fetch_building_parameters(vn, par, self.cfg[vn][par], vt)
            self.ncfile.variables[vn][par, ...] = nc_var

        # 5. multi-layer thermal properties (heat capacity, conductivity, thickness)
        # these variables use a 4d structure: (type, layer, y, x)
        thermal_vars = [
            ('building_heat_capacity', 'building heat capacity'),
            ('building_heat_conductivity', 'building heat conductivity'),
            ('building_thickness', 'building layers thickness')
        ]

        for vn, l_name in thermal_vars:
            debug(f'Processing multi-layer var: {vn}')
            self.create_var(vn, vt, ('building_surface_type', 'building_surface_layer', 'y', 'x'), long_name=l_name)
            for par in self.cfg[vn]._settings.keys():
                for ilayer, layer_val in enumerate(self.cfg[vn][par]):
                    nc_var = self.fetch_building_parameters(vn, layer_val, layer_val, vt)
                    self.ncfile.variables[vn][par, ilayer, ...] = nc_var

        # 6. aerodynamic and optical properties
        simple_vars = [
            ('building_roughness_length', 'building roughness length', 'building_surface_level'),
            ('building_roughness_length_qh', 'building roughness length for heat', 'building_surface_level'),
            ('building_transmissivity', 'building transmissivity', 'building_surface_level')
        ]

        for vn, l_name, dim_name in simple_vars:
            debug(f'Processing var: {vn}')
            self.create_var(vn, vt, (dim_name, 'y', 'x'), long_name=l_name)
            for par in self.cfg[vn]._settings.keys():
                nc_var = self.fetch_building_parameters(vn, par, self.cfg[vn][par], vt)
                self.ncfile.variables[vn][par, ...] = nc_var

        return True

    def write_building_surface_pars(self):
        """
        writes building surface parameters into a 1d list (s-dimension).
        handles orientation-specific properties for roofs, ground floors, upper floors,
        and bridge structures.
        """
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx
        case_schema = self.cfg.domain.case_schema

        # 1. acquire surface ids and create 's' dimension
        # sql query is strictly lower case
        sql_sid = f"""
            select sid from "{case_schema}"."{self.cfg.tables.surfaces}" as s 
            left outer join "{case_schema}"."{self.cfg.tables.grid}" as g on g.id = s.gid 
            order by g.j asc, g.i asc, s.direction asc, s.zs desc
        """
        sid_res = self.execute(sql_sid)
        ns = len(sid_res)
        self.nc_create_dimension('s', ns)
        sid_var = self.ncfile.createVariable('s', 'i', ('s',))
        sid_var[:] = np.asarray([x[0] for x in sid_res], dtype='i')

        # 2. write coordinate and orientation metadata for surfaces
        sql_meta = f"""
            select xs, ys, zs, azimuth, zenith, lons, lats, "Es_UTM", "Ns_UTM" 
            from "{case_schema}"."{self.cfg.tables.surfaces}" as s 
            left outer join "{case_schema}"."{self.cfg.tables.grid}" as g on g.id = s.gid 
            order by g.j asc, g.i asc, s.direction asc, s.zs desc
        """
        meta_res = self.execute(sql_meta)

        # process f4 metadata
        vi = ['xs', 'ys', 'zs', 'azimuth', 'zenith', 'lons', 'lats']
        for i, vn_meta in enumerate(vi):
            vt = 'f4'
            self.nc_create_dimension(vn_meta, ns)  # standard pids requires dimension per variable
            temp_var = self.ncfile.createVariable(vn_meta, vt, ('s',))
            temp_var[:] = np.asarray([self.cfg.fill_values[vt] if x[i] is None else x[i] for x in meta_res], dtype=vt)

        # process f8 coordinate metadata
        vj = ['Es_UTM', 'Ns_UTM']
        for i, vn_coord in enumerate(vj, start=len(vi)):
            vt = 'f8'
            self.nc_create_dimension(vn_coord, ns)
            temp_var = self.ncfile.createVariable(vn_coord, vt, ('s',))
            temp_var[:] = np.asarray([self.cfg.fill_values[vt] if x[i] is None else x[i] for x in meta_res], dtype=vt)

        # 3. initialize the main building_surface_pars variable
        vn_sp = 'building_surface_pars'
        vt_sp = 'f4'
        sp_var = self.ncfile.createVariable(vn_sp, vt_sp, ('nbuilding_surface_pars', 's'),
                                            fill_value=self.cfg.fill_values[vt_sp])
        self.nc_write_attribute(vn_sp, 'long_name', 'building parameters')
        self.nc_write_attribute(vn_sp, 'coordinates', 'Es_UTM Ns_UTM lons lats')

        # 4. fill individual parameters based on configuration
        for par in self.cfg.building_surface_pars._settings.keys():
            has_extras = self.cfg.tables.extras_shp in self.cfg.vtabs
            p_configs = self.cfg.building_surface_pars[par]

            # normalize parameter lists
            if not isinstance(p_configs, list):
                p_configs = [p_configs] * (5 if has_extras else 3)
            pt_keys = ['pr', 'pg', 'pu', 'pd', 'b'] if has_extras else ['pr', 'pg', 'pu']

            # generate case logic for green fractions and insulation (sql lower case)
            g_text_map = {}
            for pk, p_val in enumerate(p_configs):
                if par in self.cfg.building_surface_pars_repl._settings.keys():
                    repl = self.cfg.building_surface_pars_repl[par]
                    case_str = 'case '
                    for gf_code, gf_val in repl:
                        case_str += f'when {pt_keys[pk]}.code = {gf_code} then {gf_val} '
                    case_str += f'else {p_val} end '
                    g_text_map[pk] = case_str
                else:
                    g_text_map[pk] = f'{p_val} '

                # wall insulation (skips roof pk=0)
                if self.cfg.insulation.enabled and par in self.cfg.insulation.building_surface_pars:
                    ins_idx = self.cfg.insulation.building_surface_pars.index(par)
                    if 1 <= pk <= 2 and self.cfg.insulation.exists[pk - 1]:
                        f_name = self.cfg.insulation.fields[pk - 1]
                        i_val = self.cfg.insulation.values[self.cfg.insulation.surface_pars_items[ins_idx]]
                        g_text_map[pk] = f'case when "{f_name}" <> 0 then {i_val} else {g_text_map[pk]} end '

            # 5. build final selection logic (sql lower case)
            if has_extras:
                p_text = f"""
                    case when s.isroof then 
                        case when s.eid is not null then {g_text_map[4]} else {g_text_map[0]} end 
                    when not s.isroof and s.ishorizontal then {g_text_map[3]} 
                    else 
                        case when s.zs <= {self.cfg.ground.ground_floor_height} + wart.nz_min_art * {self.cfg.domain.dz} 
                        then {g_text_map[1]} else {g_text_map[2]} end 
                    end
                """
                extra_joins = f"""
                    left outer join "{case_schema}"."{self.cfg.tables.extras_shp}" d on s.eid = d.gid 
                    left outer join "{case_schema}"."{self.cfg.tables.extras_shp}" be on s.eid = be.gid 
                    left outer join "{case_schema}"."{self.cfg.tables.surface_params}" pd on pd.code = d.katlandd 
                    left outer join "{case_schema}"."{self.cfg.tables.surface_params}" b on b.code = be.katlandd 
                """
            else:
                p_text = f"""
                    case when s.isroof then {g_text_map[0]} 
                    else 
                        case when s.zs <= {self.cfg.ground.ground_floor_height} + wart.nz_min_art * {self.cfg.domain.dz} 
                        then {g_text_map[1]} else {g_text_map[2]} end 
                    end
                """
                extra_joins = ""

            # main surface parameter query (strictly lower case)
            sql_final = f"""
                select {p_text} from "{case_schema}"."{self.cfg.tables.surfaces}" s 
                left outer join "{case_schema}"."{self.cfg.tables.roofs}" r on r.{self.cfg.idx.roofs} = s.rid 
                left outer join "{case_schema}"."{self.cfg.tables.surface_params}" pr on pr.code = cast(r.material as integer) + {self.cfg.surf_range.roof_min} 
                left outer join "{case_schema}"."{self.cfg.tables.walls}" w on w.{self.cfg.idx.walls} = s.wid 
                {extra_joins} 
                left outer join "{case_schema}"."{self.cfg.tables.surface_params}" pg on pg.code = w.wallcatd 
                left outer join "{case_schema}"."{self.cfg.tables.surface_params}" pu on pu.code = w.wallcatu 
                left outer join "{case_schema}"."{self.cfg.tables.grid}" g on g.id = s.gid 
                left outer join (
                    select id, direction, nz_min_art from "{case_schema}"."{self.cfg.tables.building_walls}" 
                    group by id, direction, nz_min_art
                ) as wart on wart.id = g.id and wart.direction = s.direction 
                order by g.j asc, g.i asc, s.direction asc, s.zs desc
            """

            raw_res = self.execute(sql_final)
            var_data = np.asarray([x[0] for x in raw_res], dtype=vt_sp)

            # finalize and write to netcdf
            sp_var[par, :] = np.nan_to_num(
                var_data,
                copy=False,
                nan=self.cfg.fill_values[vt_sp],
                posinf=self.cfg.fill_values[vt_sp],
                neginf=self.cfg.fill_values[vt_sp]
            )
            debug(f'Variable {vn_sp}, parameter {par} written.')

        # 6. final winfrac correction for surface data
        self.correct_win_frac(vn_sp, 1, 0, limit=0.95)

        debug(f'Variable {vn_sp} completely written.')
        return True

    def write_albedo_pars(self):
        """
        writes albedo parameters to netcdf.
        combines land surface, roof, and wall albedo values based on grid classification.
        """
        vn = 'albedo_pars'
        vt = 'f4'
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx

        # create the albedo parameters variable
        self.nc_create_variable(vn, vt, ('nalbedo_pars', 'y', 'x'), fill_value=self.cfg.fill_values[vt])
        self.nc_write_attribute(vn, 'long_name', 'building parameters')
        self.nc_write_attribute(vn, 'units', '')
        self.nc_write_attribute(vn, 'res_orig', self.cfg.domain.dz)
        self.nc_write_attribute(vn, 'coordinates', 'E_UTM N_UTM lon lat')
        self.nc_write_attribute(vn, 'grid_mapping', 'crs')

        # fill individual parameters
        for par in self.cfg.albedo_pars._settings.keys():
            debug(f'Processing albedo parameter: {par}')

            # 1. check if albedo column exists in the landcover table (sql lower case)
            al_col = self.cfg.albedo_pars[par][0]
            sql_check = f'select {al_col} from "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" limit 1'

            try:
                self.execute(sql_check)
                al4l = al_col
            except Exception:
                al4l = 'null'

            # 2. process land and roof albedo (sql lower case)
            sql_land_roof = f"""
                select case when b.id is null then {al4l} else {self.cfg.albedo_pars[par][1]} end 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.landcover}" l on l.lid = g.lid 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_grid}" b on b.id = g.id 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.roofs}" r on r.{self.cfg.idx.roofs} = b.rid 
                order by g.j, g.i
            """
            res_land = self.execute(sql_land_roof)
            var_arr = np.reshape(np.asarray([x[0] for x in res_land], dtype=vt), (ny, nx))

            # 3. process wall albedo (sql lower case)
            sql_wall = f"""
                select distinct on (g.i, g.j) 
                    case when bw.id is not null then {self.cfg.albedo_pars[par][2]} else null end 
                from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.building_walls}" bw on bw.id = g.id and not bw.isroof 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.walls}" w on w.{self.cfg.idx.walls} = bw.wid 
                left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.surface_params}" pw on pw.code = w.wallcatu 
                order by g.j, g.i
            """
            res_wall = self.execute(sql_wall)
            var_wall = np.reshape(np.asarray([x[0] for x in res_wall], dtype=vt), (ny, nx))

            # 4. combine arrays: favor wall values where they exist, otherwise use land/roof
            var_combined = np.where(np.isnan(var_wall), var_arr, var_wall)

            # sanitize and write to netcdf
            self.ncfile.variables[vn][par, :, :] = np.nan_to_num(
                var_combined,
                copy=False,
                nan=self.cfg.fill_values[vt],
                posinf=self.cfg.fill_values[vt],
                neginf=self.cfg.fill_values[vt]
            )

            debug(f'Variable {vn}, parameter {par} written.')

            if self.cfg.visual_check.enabled:
                variable_visualization(
                    var=self.ncfile.variables[vn][par, ...],
                    x=np.asarray(self.ncfile.variables['x']),
                    y=np.asarray(self.ncfile.variables['y']),
                    var_name=vn, par_id=par, text_id='albedo_type',
                    path=self.cfg.visual_check.path, show_plots=self.cfg.visual_check.show_plots
                )

        debug(f'Variable {vn} completely written.')
        return True

    def fetch_building_parameters(self, vn, par, cfg_par, vt):
        """
        fetches physical parameters for buildings by joining grid, roof, and wall datasets.
        uses a database-side case statement to resolve properties based on material codes.
        """
        # sql query is strictly lower case
        # joins grid to building geometry and material-specific parameter tables
        sql_fetch = f"""
            select 
                distinct on (g.i, g.j)
                case when b.id is not null then {cfg_par} else null end
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_grid}" b on b.id = g.id
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.roofs}" r on r.{self.cfg.idx.roofs} = b.rid
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.surface_params}" pr on pr.code = cast(r.material as integer) + %s
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.building_walls}" bw on bw.id = g.id and not bw.isroof 
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.walls}" w on w.{self.cfg.idx.walls} = bw.wid 
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.surface_params}" pg on pg.code = w.wallcatd
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.surface_params}" pu on pu.code = w.wallcatu
            order by g.j, g.i
        """

        # execute using the task's wrapper, passing the roof minimum offset
        res_raw = self.execute(sql_fetch, (self.cfg.surf_range.roof_min,))

        # reshape and sanitize
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx
        var_data = np.reshape(np.asarray([x[0] for x in res_raw], dtype=vt), (ny, nx))

        var_sanitized = np.nan_to_num(
            var_data,
            copy=False,
            nan=self.cfg.fill_values[vt],
            posinf=self.cfg.fill_values[vt],
            neginf=self.cfg.fill_values[vt]
        )

        debug(f'Variable {vn}, parameter {par} written.')

        # perform visual check if enabled in configuration
        if self.cfg.visual_check.enabled:
            variable_visualization(
                var=var_sanitized,
                x=np.asarray(self.ncfile.variables['x']),
                y=np.asarray(self.ncfile.variables['y']),
                var_name=vn,
                par_id=par,
                text_id=vn,
                path=self.cfg.visual_check.path,
                show_plots=self.cfg.visual_check.show_plots
            )

        return var_sanitized

    def write_mask_usm(self):
        """
        masks building footprints with vegetation types and resets surface fractions.
        used in slurb configurations to ensure urban canopy compatibility.
        """
        progress('Masking buildings for slurb')
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx

        # 1. query the building presence mask
        # sql query is strictly lower case
        sql_mask = f"""
            select case when b.lid is not null then true else false end 
            from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" g 
            left outer join "{self.cfg.domain.case_schema}"."{self.cfg.tables.buildings_grid}" b on b.id = g.id 
            order by g.j, g.i
        """

        res = self.execute(sql_mask)
        slurb_mask = np.reshape(np.asarray([x[0] for x in res], dtype='bool_'), (ny, nx))

        # 2. apply mask to vegetation_type variable
        # 1 typically represents the vegetation type assigned for slurb masking
        veg_type = self.ncfile.variables['vegetation_type'][:, :]
        veg_type[slurb_mask] = 1
        self.ncfile.variables['vegetation_type'][:, :] = veg_type

        # 3. reset surface fractions if enabled in configuration
        if self.cfg.landcover.surface_fractions:
            debug('Replacing surface fractions in building mask areas')
            veg_frac = self.ncfile.variables['surface_fraction'][:, :, :]

            # indices 0, 1, 2 correspond to specific fraction types (e.g., vegetation, pavement, building)
            veg_frac[0, slurb_mask] = 1.0  # assign full vegetation fraction
            veg_frac[1, slurb_mask] = 0.0  # clear pavement fraction
            veg_frac[2, slurb_mask] = 0.0  # clear building fraction

            self.ncfile.variables['surface_fraction'][:, :, :] = veg_frac

        debug('SLURB building mask successfully applied.')
        return True

    def check_consistency(self):
        """
        validates the final netcdf file for missing values and physical consistency.
        repairs orphaned grid points and checks all variables against defined bounds.
        """
        progress('Checking consistency and repairing orphaned grid cells...')

        # 1. repair surface types (orphaned grid cells)
        pavement_def = self.cfg._settings.get('pavement_type_default', 2)

        # determine cells where no type (veg, pave, water, or building) is assigned
        if self.cfg.force_lsm_only or self.cfg.slurb:
            mask = (self.ncfile.variables['vegetation_type'][:, :].mask &
                    self.ncfile.variables['pavement_type'][:, :].mask &
                    self.ncfile.variables['water_type'][:, :].mask)
        else:
            mask = (self.ncfile.variables['vegetation_type'][:, :].mask &
                    self.ncfile.variables['pavement_type'][:, :].mask &
                    self.ncfile.variables['building_type'][:, :].mask &
                    self.ncfile.variables['water_type'][:, :].mask)

        # check for 3d building specific consistency (structure with empty base)
        if self.cfg.has_3d_buildings:
            mask_3d = np.logical_and(
                np.logical_and(~self.ncfile.variables['building_id'][:].mask,
                               self.ncfile.variables['buildings_3d'][0, :, :] == 0),
                ~np.logical_or(
                    np.logical_or(~self.ncfile.variables['pavement_type'][:, :].mask,
                                  ~self.ncfile.variables['water_type'][:, :].mask),
                    ~self.ncfile.variables['vegetation_type'][:, :].mask
                )
            )
            mask = np.logical_or(mask, mask_3d)

        missing_count = np.sum(mask)
        if missing_count > 0:
            warning(f'Filling {missing_count} missing cells with default pavement type {pavement_def}')
            pt = self.ncfile.variables['pavement_type'][:, :]
            pt = np.where(mask, pavement_def, pt)
            self.ncfile.variables['pavement_type'][:, :] = pt

        # 2. repair soil type consistency
        soil_def = self.cfg.ground.soil_type_default
        soil_mask = np.logical_and(
            np.logical_or(~self.ncfile.variables['vegetation_type'][:, :].mask,
                          ~self.ncfile.variables['pavement_type'][:, :].mask),
            self.ncfile.variables['soil_type'][:, :].mask
        )

        if np.sum(soil_mask) > 0:
            warning(f'Filling {np.sum(soil_mask)} missing soil values with default {soil_def}')
            st = self.ncfile.variables['soil_type'][:, :]
            st[soil_mask] = soil_def
            self.ncfile.variables['soil_type'][:, :] = st

        # 3. physical boundary and NaN checking
        # loops through all variables to find outliers or corrupted values
        for var_name in self.ncfile.variables.keys():
            verbose(f'Checking integrity: {var_name}')
            nc_var = self.ncfile.variables[var_name]

            # determine if bounds are defined in yaml
            bound_key = f"{var_name}_bounds"
            has_bound = bound_key in self.cfg._settings

            # access data as masked array for stat calculation
            vals = np.asarray(nc_var[...])
            if hasattr(nc_var, 'mask'):
                vals = np.ma.masked_array(vals, nc_var[...].mask)

            # skip if array is entirely empty
            if vals.count() == 0:
                continue

            # boundary check logic
            if has_bound:
                bounds = self.cfg[bound_key]
                # determine number of parameters (e.g., albedo_pars has 4)
                npars = nc_var.shape[0] if len(nc_var.shape) > 2 else 1

                for ipar in range(npars):
                    min_b, max_b, sub_name = bounds[ipar]
                    # slice data for multi-parameter variables
                    p_vals = vals[ipar, ...] if npars > 1 else vals

                    v_min, v_max = np.min(p_vals), np.max(p_vals)

                    if v_min < min_b or v_max > max_b:
                        # check if it's just fill values or a real violation
                        if not (np.ma.is_masked(v_min) or np.ma.is_masked(v_max)):
                            warning(
                                f'Out of bounds in {var_name}.{sub_name}: [{v_min}, {v_max}] vs expected [{min_b}, {max_b}]')

            # NaN detection
            if np.any(np.isnan(vals)):
                n_nans = np.sum(np.isnan(vals))
                warning(f'Variable {var_name} contains {n_nans} NaN values!')

        debug('Consistency check complete.')

class SlurbDriverGen(StaticDriverGen):
    """ task for generating the palm static driver netcdf file. """

    def run(self):
        """ """
        ensure_capability_flags(self.cfg, self.db)
        ensure_domain_geometry(self.cfg, self.db)
        self.prepare()
        self.fill_file()
        self.finish_file()

    def prepare(self):
        """ """
        self.nc_create_file(self.cfg.domain.slurb_driver_file)
        self.nc_write_global_attributes()
        self.nc_write_crs()
        self.create_slurb_dims()

    def fill_file(self):
        """ """
        self.create_slurb_vars()

    def finish_file(self):
        """ """
        self.check_consitency_slurb()
        self.ncfile.close()

    def create_slurb_dims(self):
        """
        creates horizontal dimensions and auxiliary slurb dimensions.
        calculates local x and y coordinates relative to the domain origin.
        """
        # 1. fetch distinct x and y coordinates from the grid table
        # sql queries are strictly lower case
        sql_x = f'select distinct xcen from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" order by xcen'
        res_x = self.execute(sql_x)
        x1d = [x[0] - self.cfg.domain.origin_x for x in res_x]

        sql_y = f'select distinct ycen from "{self.cfg.domain.case_schema}"."{self.cfg.tables.grid}" order by ycen'
        res_y = self.execute(sql_y)
        y1d = [y[0] - self.cfg.domain.origin_y for y in res_y]

        nxm, nym = len(x1d), len(y1d)

        # 2. create and write horizontal dimensions
        debug("Writing 2D variables x, y to file...")
        self.nc_create_dimension('x', nxm)
        self.nc_create_dimension('y', nym)

        vt = 'f8'
        temp_x = self.ncfile.createVariable('x', vt, ('x',))
        temp_y = self.ncfile.createVariable('y', vt, ('y',))

        temp_x[:] = x1d[:]
        temp_y[:] = y1d[:]

        # 3. write horizontal coordinate attributes
        self.nc_write_attribute('x', 'long_name', 'x')
        self.nc_write_attribute('x', 'standard_name', 'projection_x_coordinate')
        self.nc_write_attribute('x', 'units', 'm')

        self.nc_write_attribute('y', 'long_name', 'y')
        self.nc_write_attribute('y', 'standard_name', 'projection_y_coordinate')
        self.nc_write_attribute('y', 'units', 'm')

        # 4. create auxiliary dimensions for slurb parameters
        debug('Creating auxiliary SLURB dimensions...')
        for name in self.cfg.ndims_slurb._settings.keys():
            d_size = self.cfg.ndims_slurb[name]
            self.nc_create_dimension(name, d_size)

            # coordinate variable for the dimension (integer index)
            temp_dim = self.ncfile.createVariable(name, 'i4', (name,))
            temp_dim[:] = np.arange(d_size, dtype='i4')

        return True

    def create_slurb_vars(self):
        """
        generates all necessary fields for the slurb (urban canopy) model.
        calculates spatial building fractions, canyon geometries, and thermal properties.
        """
        progress('Initializing SLURB grid and variables')
        ny, nx = self.cfg.domain.ny, self.cfg.domain.nx
        schema = self.cfg.domain.case_schema

        # 1. create the slurb grid table (sql lower case)
        sql_init = f"""
            drop table if exists "{schema}"."{self.cfg.tables.grid_slurb}";
            create table "{schema}"."{self.cfg.tables.grid_slurb}" as 
            select 
                g.id, g.i, g.j, g.xcen, g.ycen, g.geom, g.point,
                0.0 as building_plan_area_fraction,
                0.0 as urban_fraction,
                273.15 as deep_soil_temperature,
                {self.cfg.default_building_height} :: double precision as building_height,
                273.15 as building_indoor_temperature,
                1 as building_type,
                1 as pavement_type,
                null :: double precision as building_frontal_area_fraction,
                null :: double precision as street_canyon_aspect_ratio,
                null :: double precision as street_canyon_orientation
            from "{schema}"."{self.cfg.tables.grid}" g
        """
        self.execute(sql_init)

        # 2. calculate building and urban fractions (sql lower case)
        area_factor = self.cfg.domain.dx * self.cfg.domain.dy

        sql_fractions = f"""
            update "{schema}"."{self.cfg.tables.grid_slurb}" g set 
                building_plan_area_fraction = least(0.988, coalesce(s.sum_area)) 
            from (
                select g.id as gid, sum(st_area(st_intersection(g.geom, l.geom))) / {area_factor} as sum_area 
                from "{schema}"."{self.cfg.tables.grid_slurb}" g
                join "{schema}"."{self.cfg.tables.landcover}" l on st_intersects(l.geom, g.geom) 
                where l.type between {self.cfg.type_range.building_min} and {self.cfg.type_range.building_max}
                group by g.id
            ) as s where g.id = s.gid;

            update "{schema}"."{self.cfg.tables.grid_slurb}" g set 
                urban_fraction = least(1.0, s.sum_area) 
            from (
                select g.id as gid, sum(st_area(st_intersection(g.geom, l.geom))) / {area_factor} as sum_area 
                from "{schema}"."{self.cfg.tables.grid_slurb}" g
                join "{schema}"."{self.cfg.tables.landcover}" l on st_intersects(l.geom, g.geom) 
                where l.type between {self.cfg.type_range.building_min} and {self.cfg.type_range.building_max} or l.type between {self.cfg.type_range.pavement_min} and {self.cfg.type_range.pavement_max}
                group by g.id
            ) as s where g.id = s.gid;
        """
        self.execute(sql_fractions)

        # delete cells with negligible building fraction
        sql_cleanup = f'delete from "{schema}"."{self.cfg.tables.grid_slurb}" where building_plan_area_fraction < {self.cfg.min_plan_area}'
        self.execute(sql_cleanup)

        # 3. process building geometries (height, frontal area, canyon orientation)
        if self.cfg.has_buildings:
            debug('Calculating building height from raster/geometry')
            sql_height = f"""
                with grid_height as (
                    select gs.id, a.height
                    from "{schema}"."{self.cfg.tables.grid_slurb}" gs
                    join lateral (
                        select avg(st_nearestvalue(rast, gs.point)) as height
                        from "{schema}"."{self.cfg.tables.buildings_height}"
                        where st_intersects(rast, gs.geom)
                    ) a on true
                )
                update "{schema}"."{self.cfg.tables.grid_slurb}" gs 
                set building_height = gh.height from grid_height gh
                where gh.id = gs.id and gh.height is not null
            """
            self.execute(sql_height)

        # frontal area fraction (sql lower case)
        sql_frontal = f"""
            with fraction as (
                select gs.id, sum(st_area(st_intersection(ba.geom, gs.geom)) / ba.roof_area * (wall_area + roof_area) / {area_factor}) as f_area
                from "{schema}"."{self.cfg.tables.grid_slurb}" gs
                join "{schema}"."{self.cfg.tables.building_area}" ba on st_intersects(ba.geom, gs.geom) 
                group by gs.id
            )
            update "{schema}"."{self.cfg.tables.grid_slurb}" gs set building_frontal_area_fraction = least(f.f_area, 0.99)
            from fraction f where f.id = gs.id
        """
        self.execute(sql_frontal)

        # 4. street canyon aspect ratio and orientation
        sql_canyon = f"""
            with subq as (
                select gs.id, a.hw, a.orientation
                from "{schema}"."{self.cfg.tables.grid_slurb}" gs
                join lateral (
                    select 
                        avg(((c.val_1 + c.val_2) / 2) / c.width) as hw,
                        atan2(avg(sin(orientation * pi() / 180.0)), avg(cos(orientation * pi() / 180.0))) * 180.0 / pi() as orientation
                    from "{schema}"."{self.cfg.tables.centerline}" c where st_intersects(c.geom, gs.geom)
                ) a on true
            )
            update "{schema}"."{self.cfg.tables.grid_slurb}" gs 
            set street_canyon_aspect_ratio = s.hw,
                street_canyon_orientation = case 
                    when s.orientation < 0.0 then s.orientation + 360.0
                    when s.orientation > 360.0 then s.orientation - 360.0
                    else s.orientation end
            from subq s where s.id = gs.id
        """
        self.execute(sql_canyon)

        # 5. insert variables into netcdf
        progress('Inserting SLURB variables into NetCDF')
        for vn in self.cfg.slurb_vars_done:
            var_cfg = self.cfg.slurb_vars[vn]
            sql_fetch = f'select sg.{vn} from "{schema}"."{self.cfg.tables.grid}" g left join "{schema}"."{self.cfg.tables.grid_slurb}" sg on sg.id = g.id order by g.j, g.i'
            self.write_type_variable(vn, var_cfg.long_name, var_cfg.vt, self.cfg.fill_values, 0, sql_query=sql_fetch)

        # 6. create 3d multi-layer variables (road, roof, wall, window)
        slurb_layers = [
            ('road', 'nroad_3d'), ('roof', 'nroof_3d'),
            ('wall', 'nwall_3d'), ('window', 'nwin_3d')
        ]

        # fetch slurb mask for efficient numpy operations
        sql_mask = f'select case when sg.id is not null then true else false end from "{schema}"."{self.cfg.tables.grid}" g left join "{schema}"."{self.cfg.tables.grid_slurb}" sg on sg.id = g.id order by g.j, g.i'
        mask_res = self.execute(sql_mask)
        slurb_mask = np.reshape(np.asarray([x[0] for x in mask_res], dtype='bool_'), (ny, nx))

        for suffix, dim_name in slurb_layers:
            for prefix in ['c_', 'dz_', 'lambda_']:
                vn = f"{prefix}{suffix}"
                v_cfg = self.cfg.slurb_vars[vn]

                # create variable with 3d dimension (layer, y, x)
                self.ncfile.createVariable(vn, v_cfg.vt, (dim_name, 'y', 'x'),
                                           fill_value=self.cfg.fill_values[v_cfg.vt])

                # prepare data slice
                fill_val = self.cfg.slurb_vars_defaults.get(vn, 0.5)  # simplified default handling
                data_slice = np.full((ny, nx), self.cfg.fill_values[v_cfg.vt], dtype=v_cfg.vt)
                data_slice[slurb_mask] = fill_val

                # fill all layers
                for i in range(self.cfg.ndims_slurb[dim_name]):
                    self.ncfile.variables[vn][i, :, :] = data_slice

                self.nc_write_attribute(vn, 'long_name', self.cfg.slurb_vars[vn].long_name)
                self.nc_write_attribute(vn, 'units', self.cfg.slurb_vars[vn].vn_units)
                self.nc_write_attribute(vn, 'res_orig', self.cfg.domain.dz)
                self.nc_write_attribute(vn, 'grid_mapping', 'crs')
                self.nc_write_attribute(vn, 'coordinates', 'E_UTM N_UTM lon lat')

        return True

    def check_consitency_slurb(self):
        """ """

class CCTDriverGen(StaticDriverGen):
    """ task for generating the palm cut cell (slant) static driver netcdf file. """

    def run(self):
        """ """



    def fill_file(self):
        """ """

    def finish_file(self):
        """ """
        self.check_cct_consistency(self.ncfile)
        self.cct_continuity_check(self.ncfile)
        self.ncfile.close()

    def slanted_surface_init(self):
        """ initialize slanted surfaces utilizing task class properties """
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

        # index creation
        debug('add index on slanted geom')
        sqltext = 'create index slanted_face_geom_index on "{0}"."{1}" using gist(geom)' \
            .format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
        self.execute(sqltext)

        # obtain number of vertices
        sqltext = 'update "{0}"."{1}" set ' \
                  'n_vert = case when vert7 is not null then 7 ' \
                  '              when vert6 is not null then 6 ' \
                  '              when vert5 is not null then 5 ' \
                  '              when vert4 is not null then 4 ' \
                  '              when vert3 is not null then 3 ' \
                  '              when vert2 is not null then 2 ' \
                  '              when vert1 is not null then 1 end '.format(self.cfg.domain.case_schema,
                                                                            self.cfg.tables.slanted_faces)
        self.execute(sqltext)

        # remove faces under terrain
        if self.cfg.domain.oro_min - self.cfg.domain.origin_z > 0:
            sqltext = 'delete from "{0}"."{1}" ' \
                      'where iswall and (' \
                      '                  st_z(vert1) = 0 or ' \
                      '                  st_z(vert2) = 0 or ' \
                      '                  st_z(vert3) = 0 or ' \
                      '                  st_z(vert4) = 0 or ' \
                      '                  st_z(vert5) = 0 or ' \
                      '                  st_z(vert6) = 0 or ' \
                      '                  st_z(vert7) = 0' \
                      ')'.format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
            self.execute(sqltext)

        self.normal_vector_trinagulation()
        self.create_integer_vertices()
        self.check_for_vertex_singularities()
        self.create_vertices_indexes()

        # additional indices
        sqltext = 'create index if not exists slanted_faces_rid_idx on "{0}"."{1}" (rid); ' \
                  'create index if not exists slanted_faces_lid_idx on "{0}"."{1}" (lid); ' \
                  'create index if not exists slanted_faces_wid_idx on "{0}"."{1}" (wid)' \
            .format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces)
        self.execute(sqltext)

        self.normal_vector_trinagulation()

        if self.cfg.slanted_pars.do_vtk:
            create_slanted_vtk(self.db, self.cfg)

        # final touch: remove extra vertex
        debug('removing extra vertex')
        verbose('decreasing n_vert by 1')
        sqltext = 'update "{0}"."{1}" set n_vert = n_vert - 1'.format(self.cfg.domain.case_schema,
                                                                      self.cfg.tables.slanted_faces)
        self.execute(sqltext)

        for iv in range(1, 8):
            verbose(f'removing extra vertices, {iv}')
            sqltext = 'update "{0}"."{1}" set vert{2}i = null ' \
                      'where n_vert < {2}'.format(self.cfg.domain.case_schema, self.cfg.tables.slanted_faces, iv)
            self.execute(sqltext)

    def check_cct_consistency(self, ncfile):
        """ Routine to check if each cct surface has it own type (land, wall, roof),
            And if land cct surface has at least (exactly) one type (vegetation, pavement, water) defined,
            and if wall or roof has building type defined.
        """
        cct_surface_type_classification = ncfile.variables['cct_surface_type_classification'][:]
        cct_vegetation_type_classification = ncfile.variables['cct_vegetation_type_classification'][:]
        cct_pavement_type_classification = ncfile.variables['cct_pavement_type_classification'][:]
        cct_water_type_classification = ncfile.variables['cct_water_type_classification'][:]
        cct_building_type_classification = ncfile.variables['cct_building_type_classification'][:]
        kji_locs = ncfile.variables['cct_3d_grid_indices'][:]

        n_surfs = cct_surface_type_classification.size
        allok = True
        for n_surf in range(n_surfs):
            k, j, i = kji_locs[:, n_surf]
            land = True if cct_surface_type_classification[n_surf] == 0 else False
            wall = True if cct_surface_type_classification[n_surf] == 1 else False
            roof = True if cct_surface_type_classification[n_surf] == 2 else False

            vege = True if cct_vegetation_type_classification[n_surf] > 0 else False
            vege_type = cct_vegetation_type_classification[n_surf]
            pave = True if cct_pavement_type_classification[n_surf] > 0 else False
            pave_type = cct_pavement_type_classification[n_surf]
            wate = True if cct_water_type_classification[n_surf] > 0 else False
            wate_type = cct_water_type_classification[n_surf]
            build = True if cct_building_type_classification[n_surf] > 0 else False
            build_type = cct_building_type_classification[n_surf]

            if not land and not wall and not roof:
                allok = False
                warning('Surf id: {}, kji: [{},{},{}], '
                        'does not have cct_surface_type_classification defined correcly',
                        n_surf, k, j, i)

            if not vege and not pave and not wate and not build:
                allok = False
                warning('Surf id: {}, kji: [{},{},{}], '
                        'does not have any type defined.',
                        n_surf, k, j, i)

            if land and not (vege or pave or wate):
                allok = False
                warning('Surf id: {}, kji: [{},{},{}], '
                        'is defined as land but vege, water, pavement types are mismatched. '
                        'Vege: {}, Pave: {}, Water: {}',
                        n_surf, k, j, i, vege_type, pave_type, wate_type)

            if (wall or roof) and not build:
                allok = False
                warning('Surf id: {}, kji: [{},{},{}], '
                        'is defined as urban but building type is mismatched. '
                        'Build type: {}',
                        n_surf, k, j, i, build_type)
        if allok:
            verbose('CCT check finished without a problem')
        else:
            error('CCT check finished with a problem')

    def check_singular(self, edge_faces, faces, vert_kji, vert_len, ie):
        """ Check if vertex is singular, or vertex with the same [k,j,i] coordinate is singular"""
        if vert_len[ie - 1] == 0.0:
            return True
        adj_verts = []
        for iface in edge_faces:
            verts = faces[:, iface]
            for vt in verts:
                if vt > 0 and vt not in adj_verts and vt != ie:
                    # print(vt, vert_kji[:, vt-1], '||||', vert_kji[:, ie])
                    if (vert_kji[:, vt - 1] == vert_kji[:, ie]).all():
                        # print(vt, vert_kji[:, vt-1])
                        if vert_len[vt - 1] == 0.0:
                            # print('Possible singular point')
                            return True
                    adj_verts.append(vt)
        return False

    def cct_continuity_check(self, ncfile):
        """
        Function to check continuity in CCT. Check if structures are water-tight.
        Also check, if all TOPO / AIR gridcell corners are consitently defined thought out all surface.
        The condition that each vertex must have exactly 4 adjacent CCT surface is check.
        (Except the ones at domain boundary and singular points - only warning is printed
        """
        na_ = np.newaxis

        vertex_shift_nvect = np.array([[1, 0, 0],
                                       [-1, 0, 0],
                                       [0, 1, 0],
                                       [0, -1, 0],
                                       [0, 0, 1],
                                       [0, 0, -1]])

        extra_verbose('NOTE: All indices printed here are counted from 0!')
        progress('Checking cct consistency')

        debug('Loading static cct data')

        nx = len(ncfile.dimensions['x'])
        ny = len(ncfile.dimensions['y'])

        faces = ncfile.variables['cct_vertices_per_face'][:, :]
        face_nvert = ncfile.variables['cct_num_vertices_per_face'][:]

        vv = ncfile.variables['cct_vertex_coords']
        vert_kji = vv[0:3, :]
        vert_dir = vv[3, :]
        vv = ncfile.variables['cct_vertex_shifts']
        vert_len = vv[:].squeeze()

        kji_locs = ncfile.variables['cct_3d_grid_indices'][:]

        nfaces = faces.shape[1]
        nvert = vert_dir.shape[0]
        verbose('Loaded {} faces and {} vertices.', nfaces, nvert)

        allok = True

        debug('Checking stable assignment of corners')
        corners = {}
        for iv in range(nvert):
            full_corner = vert_kji[:, iv]
            shift = vertex_shift_nvect[vert_dir[iv]]  # from full corner towards vertex
            free_corner = tuple(full_corner + shift)
            full_corner = tuple(full_corner)

            full, last = corners.setdefault(full_corner, (True, iv))
            if not full:
                warning('Corner (k,j,i) {} is specified as full by vertex {}, '
                        'although it was already specified as free by vertex {}.', full_corner, iv + 1, last + 1)
                allok = False

            free, last = corners.setdefault(free_corner, (False, iv))
            if free:
                warning('Corner (k,j,i) {} is specified as full by vertex {}, '
                        'although it was already specified as free by vertex {}.', free_corner, iv + 1, last + 1)
                allok = False
        if allok:
            debug('Checked {} corners as correct.', len(corners))
        del corners

        debug('Checking continuity of face edges')
        for jf in range(nfaces):
            verts = faces[:, jf] - 1
            nv = face_nvert[jf]

            if verts[0] == verts[nv - 1]:
                warning('Face {} first and last vertex are same: {}.', jf, verts[:nv])
                allok = False

            full_corners = vert_kji[:, verts].T
            shifts = vertex_shift_nvect[vert_dir[verts]]  # from full corner towards vertex
            free_corners = full_corners + shifts

            for iv in range(nv - 1):
                iv2 = iv + 1
                if all(shifts[iv, :] == shifts[iv2, :]):
                    # Identical vertex direction, edges must be 1 apart in
                    # a different dimension.
                    edge_diff = full_corners[iv2, :] - full_corners[iv, :]
                    if (edge_diff[:] * shifts[iv, :]).sum():
                        warning(
                            'Face {} has consecutive edges with equal directions whose relative shift is nonzero in that direction: '
                            '({}, {}) -> ({}, {})',
                            jf, full_corners[iv], free_corners[iv], full_corners[iv2], free_corners[iv2])
                        allok = False

                    if np.count_nonzero(edge_diff) != 1:
                        warning(
                            'Face {} has consecutive edges with equal directions that are not shifted in exactly one dimension: '
                            '({}, {}) -> ({}, {})',
                            jf, full_corners[iv], free_corners[iv], full_corners[iv2], free_corners[iv2])
                        allok = False

                    if np.abs(edge_diff.sum()) != 1:
                        warning(
                            'Face {} has consecutive edges with equal directions that are not shifted exactly by one: '
                            '({}, {}) -> ({}, {})',
                            jf, full_corners[iv], free_corners[iv], full_corners[iv2], free_corners[iv2])
                        allok = False

                else:
                    # Different directions, edges must share either inner or outer
                    # corner.
                    common_full = all(full_corners[iv, :] == full_corners[iv2, :])
                    common_free = all(free_corners[iv, :] == free_corners[iv2, :])
                    if not common_full and not common_free:
                        warning(
                            'Face {} has consecutive edges with different directions that do not have a common corner: '
                            '({}, {}) -> ({}, {})',
                            jf, full_corners[iv], free_corners[iv], full_corners[iv2], free_corners[iv2])
                        allok = False
            else:
                continue
        if allok:
            debug('Face edges are continuous.')

        debug('Checking number of adjacent faces per edge')
        edges = [[] for ie in range(nvert)]
        for jf in range(nfaces):
            verts = faces[:, jf] - 1
            nv = face_nvert[jf]

            for iv in range(nv):
                if not 0 <= verts[iv] < nvert:
                    error('Face {} has {}. vertex = {} which is out of range.', jf, iv, verts[iv])
                edges[verts[iv]].append(jf)
        extra_verbose('... calculating sums')
        faces_per_edge = np.array(list(map(len, edges)))
        fhist = np.bincount(faces_per_edge, minlength=5)
        verbose('Number of edges adjacent to X faces: ' + ', '.join(f'{n}: {ne}' for n, ne in enumerate(fhist)))
        corner_edges = bnd_edges = 0
        for ie, edge_faces in enumerate(edges):
            c1 = vert_kji[:, ie]
            shift = vertex_shift_nvect[vert_dir[ie]]  # from full corner towards vertex
            c2 = c1 + shift

            nbound = 0
            if (c1[2] == c2[2] == 0) or (c1[2] == c2[2] == nx):
                nbound += 1
            if (c1[1] == c2[1] == 0) or (c1[1] == c2[1] == ny):
                nbound += 1
            if (c1[0] == c2[0] == 0):
                nbound += 1

            if nbound == 0:
                if len(edge_faces) != 4:
                    msg = f'Standard edge with vertex {ie} [i,j,k; {c1[2], c1[1], c1[0]}] has {len(edge_faces)} adjacent faces instead of 4: {edge_faces}.'
                    singular = self.check_singular(edge_faces, faces, vert_kji, vert_len, ie)
                    if singular:
                        extra_verbose('Singular edge')
                        extra_verbose('Singular edge; ' + msg)
                    else:
                        warning(msg)
                        allok = False
            elif nbound == 1:
                if len(edge_faces) != 2:
                    msg = f'Edge at domain boundary with vertex {ie} has {len(edge_faces)} adjacent faces instead of 2: {edge_faces}.'
                    singular = self.check_singular(edge_faces, faces, vert_kji, vert_len, ie)
                    if singular:
                        extra_verbose('Singular edge')
                        extra_verbose('Singular edge; ' + msg)
                    else:
                        warning(msg)
                        allok = False
            elif nbound == 2:
                if len(edge_faces) != 1:
                    msg = f'Edge with vertex {ie} at domain edge has {len(edge_faces)} adjacent faces instead of 1: {edge_faces}.'
                    singular = self.check_singular(edge_faces, faces, vert_kji, vert_len, ie)
                    if singular:
                        extra_verbose('Singular edge')
                        extra_verbose('Singular edge; ' + msg)
                    else:
                        warning(msg)
                        allok = False
            else:
                error('Unexpected number of boundaries, this should never happen.')
        if allok:
            debug('Number of adjacent faces per edge is correct everywhere.')

        verbose('Examined {} cell edges along domain edges and {} edges on domain boundaries.', corner_edges, bnd_edges)

        if allok:
            progress('The file is fully consistent.')
        else:
            error('There were consistency errors (see above).')

    def slanted_write_nc(self):
        """
        writes whole slanted surface geometry (lod2) to the netcdf file.
        handles vertices (coords, indices, shifts), face centers, normals,
        areas, and pids surface type classifications.
        """
        progress('Creating slanted surface geometry (lod2) - complete transfer')
        schema = self.cfg.domain.case_schema
        origin_x, origin_y = self.cfg.domain.origin_x, self.cfg.domain.origin_y
        empty_vert = self.cfg.slanted_pars.empty_vert

        # 1. count vertices and create dimensions
        sql_count_vert = f'select count(*) from "{schema}"."{self.cfg.tables.vertices}"'
        num_vert = self.execute(sql_count_vert)[0][0]

        self.nc_create_dimension('cct_num_vert', num_vert)
        self.ncfile.setncattr('LOD', 2)
        self.ncfile.setncattr('empty_vert', empty_vert)

        # 2. build vertices: coordinates [z, y, x]
        vn = 'cct_vertices'
        nc_v = self.ncfile.createVariable(vn, 'f8', ('dim_3d', 'cct_num_vert'))
        self.nc_write_attribute(vn, 'long_name', '[z,y,x] coordinates of vertices')

        sql_v = f'select cast(st_z(point) as float), cast(st_y(point) as float), cast(st_x(point) as float) from "{schema}"."{self.cfg.tables.vertices}" order by id'
        res_v = self.execute(sql_v)
        nc_v[0, :] = [x[0] for x in res_v]
        nc_v[1, :] = [x[1] - origin_y for x in res_v]
        nc_v[2, :] = [x[2] - origin_x for x in res_v]

        # 3. build vertices 2: vertex coords [k, j, i, dir]
        vn = 'cct_vertex_coords'
        nc_vc = self.ncfile.createVariable(vn, 'i4', ('cct_dim_vertex_coords', 'cct_num_vert'))
        self.nc_write_attribute(vn, 'long_name',
                                'type of vertices coordinates for radiation module. order: [k;j;i;dir], kji index of corner, dir direction: [0.+z, 1.-z, 2.+y, 3.-y, 4.+x, 5.-x]')

        sql_vc = f'select k, j, i, dir from "{schema}"."{self.cfg.tables.vertices}" order by id'
        res_vc = self.execute(sql_vc)
        for i in range(4):
            nc_vc[i, :] = [x[i] for x in res_vc]

        # 4. build vertex shifts [len]
        vn = 'cct_vertex_shifts'
        nc_vs = self.ncfile.createVariable(vn, 'f8', ('cct_dim_vertex_shifts', 'cct_num_vert'))
        self.nc_write_attribute(vn, 'long_name',
                                'type of vertices coordinates for radiation module. order: [len], len distance [corner; vertex]')

        sql_vs = f'select len from "{schema}"."{self.cfg.tables.vertices}" order by id'
        res_vs = self.execute(sql_vs)
        nc_vs[:] = [x[0] for x in res_vs]

        # 5. faces initialization
        sql_count_faces = f'select count(*) from "{schema}"."{self.cfg.tables.slanted_faces}"'
        num_faces = self.execute(sql_count_faces)[0][0]
        self.nc_create_dimension('cct_num_faces', num_faces)

        # create face-related variables
        faces = self.ncfile.createVariable('cct_vertices_per_face', 'i4',
                                           ('cct_max_num_vertices_per_face', 'cct_num_faces'))
        self.nc_write_attribute('cct_vertices_per_face', 'long_name',
                                'list of vertices for each face, ordered by right-hand-rule')

        centers = self.ncfile.createVariable('cct_face_center', 'f8', ('dim_3d', 'cct_num_faces'))
        self.nc_write_attribute('cct_face_center', 'long_name', 'positions of slanted faces centers, [z;y;x]')

        kji_locs = self.ncfile.createVariable('cct_3d_grid_indices', 'i4', ('dim_3d', 'cct_num_faces'))
        self.nc_write_attribute('cct_3d_grid_indices', 'long_name', '[kji] locations of slanted faces')

        offs = self.ncfile.createVariable('cct_offsets', 'i4', ('dim_3d', 'cct_num_faces'))
        self.nc_write_attribute('cct_offsets', 'long_name',
                                '[kji] offsets for slanted faces, relates each surfaces to its building (need for properties)')

        normals = self.ncfile.createVariable('cct_face_normal_vector', 'f8', ('dim_3d', 'cct_num_faces'))
        self.nc_write_attribute('cct_face_normal_vector', 'long_name', '[z;y;x] components of normalized normal vector')

        area_var = self.ncfile.createVariable('cct_face_area', 'f8', ('cct_num_faces',))
        self.nc_write_attribute('cct_face_area', 'long_name', 'area of slanted face surface')

        num_edges = self.ncfile.createVariable('cct_num_vertices_per_face', 'i4', ('cct_num_faces',))
        self.nc_write_attribute('cct_num_vertices_per_face', 'long_name', 'number of vertices in each face')

        types = self.ncfile.createVariable('cct_surface_type_classification', 'i4', ('cct_num_faces',))
        self.nc_write_attribute('cct_surface_type_classification', 'long_name',
                                'index for separating lsm=0, usm wall=1, usm roof=2 surfaces')

        # 6. fetch base face data
        sql_f_base = f"""
            select vert1i, vert2i, vert3i, vert4i, vert5i, vert6i, vert7i, n_vert, 
                   case when isterr then 0 when iswall then 1 else 2 end  
            from "{schema}"."{self.cfg.tables.slanted_faces}" order by k, j, i
        """
        res_f = self.execute(sql_f_base)
        for i in range(7):
            faces[i, :] = [empty_vert if x[i] is None else x[i] for x in res_f]
        num_edges[:] = [x[7] for x in res_f]
        types[:] = [x[8] for x in res_f]

        # 7. fetch type classifications (veg, pav, wat)
        type_configs = [
            ('cct_vegetation_type_classification', self.cfg.type_range.vegetation_min,
             self.cfg.type_range.vegetation_max, 'vegetation'),
            ('cct_pavement_type_classification', self.cfg.type_range.pavement_min, self.cfg.type_range.pavement_max,
             'pavement'),
            ('cct_water_type_classification', self.cfg.type_range.water_min, self.cfg.type_range.water_max, 'water')
        ]

        for vn, t_min, t_max, long_part in type_configs:
            v_type = self.ncfile.createVariable(vn, 'i4', ('cct_num_faces',), fill_value=self.cfg.fill_values.i4)
            self.nc_write_attribute(vn, 'long_name', f'palm pids {long_part} type')
            sql_t = f"""
                select l.type - {t_min} from "{schema}"."{self.cfg.tables.slanted_faces}" as s 
                left outer join "{schema}"."{self.cfg.tables.landcover}" as l on l.lid = s.lid and l.type between {t_min} and {t_max}
                order by k, j, i
            """
            res_t = self.execute(sql_t)
            v_type[:] = [self.cfg.fill_values.i4 if x[0] is None else x[0] for x in res_t]

        # 8. fetch building types and ids
        if self.cfg.has_buildings:
            build_configs = [
                ('cct_building_type_classification', 'palm pids buildings type', 'lw.type - {6}'),
                ('cct_building_id_classification', 'palm pids buildings id', 'lw.lid')
            ]
            for vn, long_name, col_logic in build_configs:
                v_build = self.ncfile.createVariable(vn, 'i4', ('cct_num_faces',), fill_value=self.cfg.fill_values.i4)
                self.nc_write_attribute(vn, 'long_name', long_name)

                sql_b = f"""
                    select case when iswall then {col_logic.format(None, None, None, None, None, None, self.cfg.type_range.building_min)}
                                when isroof then {col_logic.replace('lw', 'lr').format(None, None, None, None, None, None, self.cfg.type_range.building_min)}
                                else null end
                    from "{schema}"."{self.cfg.tables.slanted_faces}" as s 
                    left outer join "{schema}"."{self.cfg.tables.walls}" as w on w.wid = s.wid 
                    left outer join "{schema}"."{self.cfg.tables.landcover}" as lw on lw.lid = w.lid and lw.type between {self.cfg.type_range.building_min} and {self.cfg.type_range.building_max}
                    left outer join "{schema}"."{self.cfg.tables.roofs}" as r on r.rid = s.rid 
                    left outer join "{schema}"."{self.cfg.tables.landcover}" as lr on lr.lid = r.lid and lr.type between {self.cfg.type_range.building_min} and {self.cfg.type_range.building_max}
                    order by k, j, i
                """
                res_b = self.execute(sql_b)
                v_build[:] = [self.cfg.fill_values.i4 if x[0] is None else x[0] for x in res_b]

        # 9. fetch centers, normals, and area
        sql_geom = f'select st_x(center), st_y(center), st_z(center), normz, normy, normx, area from "{schema}"."{self.cfg.tables.slanted_faces}" order by k, j, i'
        res_g = self.execute(sql_geom)
        centers[2, :] = [x[0] - origin_x for x in res_g]
        centers[1, :] = [x[1] - origin_y for x in res_g]
        centers[0, :] = [x[2] for x in res_g]

        for i in range(3):
            normals[i, :] = [x[i + 3] for x in res_g]  # normz, normy, normx
        area_var[:] = [x[6] for x in res_g]

        # 10. kji locations and offsets (nearest neighbor search)
        debug('Calculating face locations and building/terrain offsets')
        off_dist = self.cfg.slanted_pars.off_dist * self.cfg.domain.dx

        if self.cfg.has_buildings:
            sql_off = f"""
                select js.koff, js.joff, js.ioff, js.k, js.j, js.i from (
                    select gg.nz as koff, gg.j as joff, gg.i as ioff, s.k, s.j, s.i from "{schema}"."{self.cfg.tables.slanted_faces}" as s 
                    join lateral (select i, j, nz from "{schema}"."{self.cfg.tables.grid}" as g join "{schema}"."{self.cfg.tables.landcover}" l on l.lid = g.lid 
                                  where abs(l.type - (select type from "{schema}"."{self.cfg.tables.landcover}" where lid = s.lid)) < 50 
                                  and st_dwithin(s.center, g.geom, {off_dist}) order by st_distance(g.geom, s.center) limit 1) as gg on true where isterr
                    union all
                    select bb.k as koff, bb.j as joff, bb.i as ioff, s.k, s.j, s.i from "{schema}"."{self.cfg.tables.slanted_faces}" as s 
                    join lateral (select i, j, k from "{schema}"."{self.cfg.tables.buildings_grid}" as b where st_dwithin(s.center, b.geom, {off_dist}) order by st_distance(s.center, b.geom) limit 1) as bb on true where iswall
                    union all
                    select bb.k as koff, bb.j as joff, bb.i as ioff, s.k, s.j, s.i from "{schema}"."{self.cfg.tables.slanted_faces}" as s 
                    join lateral (select i, j, k from "{schema}"."{self.cfg.tables.buildings_grid}" as b where st_dwithin(s.center, b.geom, {off_dist}) order by st_distance(b.geom, s.geom) limit 1) as bb on true where isroof
                ) as js order by k, j, i
            """
        else:
            sql_off = f"""
                select gg.nz as koff, gg.j as joff, gg.i as ioff, s.k, s.j, s.i from "{schema}"."{self.cfg.tables.slanted_faces}" as s 
                join lateral (select i, j, nz from "{schema}"."{self.cfg.tables.grid}" as g where s.lid = g.lid and st_dwithin(g.geom, s.center, {off_dist}) 
                              order by st_distance(g.geom, s.center) limit 1) as gg on true where isterr order by k, j, i
            """

        res_o = self.execute(sql_off)
        kji_locs[0, :] = [x[3] for x in res_o]
        kji_locs[1, :] = [x[4] for x in res_o]
        kji_locs[2, :] = [x[5] for x in res_o]
        offs[0, :] = [x[0] - x[3] for x in res_o]
        offs[1, :] = [x[1] - x[4] for x in res_o]
        offs[2, :] = [x[2] - x[5] for x in res_o]

        return True

    def normal_vector_trinagulation(self):
        """ calculate face normal vector using triangulation """
        schema = self.cfg.domain.case_schema
        table = self.cfg.tables.slanted_faces

        sqltext = f'alter table "{schema}"."{table}" ' \
                  'add column if not exists norm_line geometry("linestringz", %s), ' \
                  'add column if not exists normx double precision, ' \
                  'add column if not exists normy double precision, ' \
                  'add column if not exists normz double precision, ' \
                  'add column if not exists area double precision, ' \
                  'add column if not exists n1x double precision, ' \
                  'add column if not exists n1y double precision, ' \
                  'add column if not exists n1z double precision, ' \
                  'add column if not exists area1 double precision, ' \
                  'add column if not exists n2x double precision, ' \
                  'add column if not exists n2y double precision, ' \
                  'add column if not exists n2z double precision, ' \
                  'add column if not exists area2 double precision, ' \
                  'add column if not exists n3x double precision, ' \
                  'add column if not exists n3y double precision, ' \
                  'add column if not exists n3z double precision, ' \
                  'add column if not exists area3 double precision, ' \
                  'add column if not exists n4x double precision, ' \
                  'add column if not exists n4y double precision, ' \
                  'add column if not exists n4z double precision, ' \
                  'add column if not exists area4 double precision, ' \
                  'add column if not exists n5x double precision, ' \
                  'add column if not exists n5y double precision, ' \
                  'add column if not exists n5z double precision, ' \
                  'add column if not exists area5 double precision, ' \
                  'add column if not exists n6x double precision, ' \
                  'add column if not exists n6y double precision, ' \
                  'add column if not exists n6z double precision, ' \
                  'add column if not exists area6 double precision, ' \
                  'add column if not exists n7x double precision, ' \
                  'add column if not exists n7y double precision, ' \
                  'add column if not exists n7z double precision, ' \
                  'add column if not exists area7 double precision'
        self.execute(sqltext, (self.cfg.srid_palm,))

        for ni in range(1, 7):
            debug(f'trinagulating normal vector, {ni}')
            nxt = ni + 1
            sqltext = f'update "{schema}"."{table}" set (n{ni}x, n{ni}y, n{ni}z) = (' \
                      f'case when {ni} < n_vert then ((st_y(vert{nxt})-st_y(center))*(st_z(vert{ni})-st_z(center)) - (st_z(vert{nxt})-st_z(center))*(st_y(vert{ni})-st_y(center))) ' \
                      'else null end, ' \
                      f'case when {ni} < n_vert then ((st_z(vert{nxt})-st_z(center))*(st_x(vert{ni})-st_x(center)) - (st_x(vert{nxt})-st_x(center))*(st_z(vert{ni})-st_z(center))) ' \
                      'else null end, ' \
                      f'case when {ni} < n_vert then ((st_x(vert{nxt})-st_x(center))*(st_y(vert{ni})-st_y(center)) - (st_y(vert{nxt})-st_y(center))*(st_x(vert{ni})-st_x(center))) ' \
                      'else null end ' \
                      ')'
            self.execute(sqltext)

            sqltext = f'update "{schema}"."{table}" set area{ni} = ' \
                      f'case when {ni} < n_vert then sqrt((n{ni}x)^2 + (n{ni}y)^2 + (n{ni}z)^2) / 2.0 ' \
                      'else null end'
            self.execute(sqltext)

        # get overall area
        debug('calculation of overall face area')
        sqltext = f'update "{schema}"."{table}" set ' \
                  'area = area1 + coalesce(area2, 0.0) + coalesce(area3, 0.0) + coalesce(area4, 0.0) + ' \
                  '               coalesce(area5, 0.0) + coalesce(area6, 0.0) + coalesce(area7, 0.0)'
        self.execute(sqltext)

        # get average normal vector
        debug('normal vector for faces with zero area')
        sqltext = f'update "{schema}"."{table}" set normx = 0, normy = 0, normz = 1 where area = 0.0 and norm is null'
        self.execute(sqltext)

        debug('calculating average unit normal vector')
        sqltext = f'update "{schema}"."{table}" set ' \
                  'normx = (n1x*area1 + coalesce(n2x, 0.0)*coalesce(area2, 0.0) + coalesce(n3x, 0.0)*coalesce(area3, 0.0) + ' \
                  '         coalesce(n4x, 0.0)*coalesce(area4, 0.0) + coalesce(n5x, 0.0)*coalesce(area5, 0.0) + ' \
                  '         coalesce(n6x, 0.0)*coalesce(area6, 0.0) + coalesce(n7x, 0.0)*coalesce(area7, 0.0))/area, ' \
                  'normy = (n1y*area1 + coalesce(n2y, 0.0)*coalesce(area2, 0.0) + coalesce(n3y, 0.0)*coalesce(area3, 0.0) + ' \
                  '         coalesce(n4y, 0.0)*coalesce(area4, 0.0) + coalesce(n5y, 0.0)*coalesce(area5, 0.0) + ' \
                  '         coalesce(n6y, 0.0)*coalesce(area6, 0.0) + coalesce(n7y, 0.0)*coalesce(area7, 0.0))/area, ' \
                  'normz = (n1z*area1 + coalesce(n2z, 0.0)*coalesce(area2, 0.0) + coalesce(n3z, 0.0)*coalesce(area3, 0.0) + ' \
                  '         coalesce(n4z, 0.0)*coalesce(area4, 0.0) + coalesce(n5z, 0.0)*coalesce(area5, 0.0) + ' \
                  '         coalesce(n6z, 0.0)*coalesce(area6, 0.0) + coalesce(n7z, 0.0)*coalesce(area7, 0.0))/area ' \
                  'where norm is null and area > 0.0'
        self.execute(sqltext)

        verbose('calculate normals from vertical walls norm')
        sqltext = f'update "{schema}"."{table}" set ' \
                  'normx = st_x(norm) - st_x(center), ' \
                  'normy = st_y(norm) - st_y(center), ' \
                  'normz = st_z(norm) - st_z(center) ' \
                  'where norm is not null'
        self.execute(sqltext)

        debug('normal vector for faces with zero area')
        sqltext = f'update "{schema}"."{table}" set normx = 0, normy = 0, normz = 1 ' \
                  'where norm is null and normx^2 + normy^2 + normz^2 = 0'
        self.execute(sqltext)

        verbose('correct normal vector, z component for vertical faces')
        sqltext = f'update "{schema}"."{table}" set normz = 0.0 ' \
                  'where abs(normz/area) < 1e-8 and area > 0.0'
        self.execute(sqltext)

        # normalize vector
        debug('normalizing normal vector')
        sqltext = f'update "{schema}"."{table}" set ' \
                  'normx = normx / sqrt(normx^2 + normy^2 + normz^2), ' \
                  'normy = normy / sqrt(normx^2 + normy^2 + normz^2), ' \
                  'normz = normz / sqrt(normx^2 + normy^2 + normz^2)'
        self.execute(sqltext)

        # create point and line for normal vector
        debug('calculation of normal point')
        sqltext = f'update "{schema}"."{table}" set norm = ' \
                  'st_setsrid(st_makepoint(st_x(center)+normx, st_y(center)+normy, st_z(center)+normz),%s) ' \
                  'where norm is null'
        self.execute(sqltext, (self.cfg.srid_palm,))

        debug('calculation of normal line')
        sqltext = f'update "{schema}"."{table}" set norm_line = ' \
                  'st_setsrid(st_makeline(center, norm), %s)'
        self.execute(sqltext, (self.cfg.srid_palm,))

    def create_vertices_indexes(self):
        """ join all vertices and create back index to faces """
        schema = self.cfg.domain.case_schema
        table_v = self.cfg.tables.vertices
        table_f = self.cfg.tables.slanted_faces

        progress('creating vertices table and back indexing')
        sqltext = f'drop table if exists "{schema}"."{table_v}" cascade '
        self.execute(sqltext)

        debug('create table of individual vertices 2, based on kjidir index')
        sqltext = f'create table "{schema}"."{table_v}" as ' \
                  'select row_number() over () as id, k, j, i, dir, len, point ' \
                  'from (' \
                  f'      select kk1 as k, jj1 as j, ii1 as i, dir1 as dir, len1 as len, vert1 as point from "{schema}"."{table_f}" as v2_1 where ii1 is not null ' \
                  '      union all ' \
                  f'      select kk2 as k, jj2 as j, ii2 as i, dir2 as dir, len2 as len, vert2 as point from "{schema}"."{table_f}" as v2_2 where ii2 is not null ' \
                  '      union all ' \
                  f'      select kk3 as k, jj3 as j, ii3 as i, dir3 as dir, len3 as len, vert3 as point from "{schema}"."{table_f}" as v2_3 where ii3 is not null ' \
                  '      union all ' \
                  f'      select kk4 as k, jj4 as j, ii4 as i, dir4 as dir, len4 as len, vert4 as point from "{schema}"."{table_f}" as v2_4 where ii4 is not null ' \
                  '      union all ' \
                  f'      select kk5 as k, jj5 as j, ii5 as i, dir5 as dir, len5 as len, vert5 as point from "{schema}"."{table_f}" as v2_5 where ii5 is not null ' \
                  '      union all ' \
                  f'      select kk6 as k, jj6 as j, ii6 as i, dir6 as dir, len6 as len, vert6 as point from "{schema}"."{table_f}" as v2_6 where ii6 is not null ' \
                  '      union all ' \
                  f'      select kk7 as k, jj7 as j, ii7 as i, dir7 as dir, len7 as len, vert7 as point from "{schema}"."{table_f}" as v2_7 where ii7 is not null ' \
                  '      ) as s ' \
                  'group by k,j,i,dir,len,point'
        self.execute(sqltext)

        verbose('\tadding kjidir index')
        sqltext = f'create index if not exists vert2_kjidir_idx on "{schema}"."{table_v}" (k,j,i,dir)'
        self.execute(sqltext)

        for i in range(1, 8):
            verbose(f'creating kjidir {i} index on slanted faces table')
            sqltext = f'create index if not exists vert2_kjidur_{i}_geom_idx on "{schema}"."{table_f}" (kk{i},jj{i},ii{i},dir{i})'
            self.execute(sqltext)

        verbose('\tadding integer index')
        sqltext = f'create index if not exists index_id on "{schema}"."{table_v}" (id)'
        self.execute(sqltext)

        for i in range(1, 8):
            debug(f'joining vertices n. {i}')
            sqltext = f'update "{schema}"."{table_f}" set ' \
                      f'vert{i}i = v.id from "{schema}"."{table_v}" as v ' \
                      f'where ii{i} = v.i and jj{i} = v.j and kk{i} = v.k and dir{i} = v.dir'
            self.execute(sqltext)
            debug(f'end joining vertices n. {i}')

        debug('renewing id column on slanted faces table')
        sqltext = f'alter table "{schema}"."{table_f}" drop column if exists id; ' \
                  f'alter table "{schema}"."{table_f}" add column id serial'
        self.execute(sqltext)

        # debug('creating vertices tables from individual vertices')
        # sqltext = f'create table "{schema}"."{table_v}" as ' \
        #           'select row_number() over () as id, point  ' \
        #           'from ( ' \
        #           f'    select v1.vert1 as point from "{schema}"."{table_f}" as v1  where v1.vert1 is not null ' \
        #           '    union all ' \
        #           f'    select v2.vert2 as point from "{schema}"."{table_f}" as v2  where v2.vert2 is not null ' \
        #           '    union all ' \
        #           f'    select v3.vert3 as point from "{schema}"."{table_f}" as v3  where v3.vert3 is not null ' \
        #           '    union all ' \
        #           f'    select v4.vert4 as point from "{schema}"."{table_f}" as v4  where v4.vert4 is not null ' \
        #           '    union all ' \
        #           f'    select v5.vert5 as point from "{schema}"."{table_f}" as v5  where v5.vert5 is not null ' \
        #           '    union all ' \
        #           f'    select v6.vert6 as point from "{schema}"."{table_f}" as v6  where v6.vert6 is not null ' \
        #           '    union all ' \
        #           f'    select v7.vert7 as point from "{schema}"."{table_f}" as v7  where v7.vert7 is not null ' \
        #           ') as s ' \
        #           'group by point'
        # self.execute(sqltext)

        # verbose('add extra columns for new coordinate system')
        # sqltext = f'alter table "{schema}"."{table_v}" ' \
        #           'add column if not exists ii integer, ' \
        #           'add column if not exists jj integer, ' \
        #           'add column if not exists kk integer, ' \
        #           'add column if not exists dir integer, ' \
        #           'add column if not exists len double precision'
        # self.execute(sqltext)

        # # todo: merge point based on ii,jj,kk,dir index
        # verbose('\tadding hash indexes')
        # sqltext = f'create index if not exists hash_geom_idx on "{schema}"."{table_v}" using hash(point)'
        # self.execute(sqltext)

        # for i in range(1, 8):
        #     sqltext = f'create index vert_hash_{i}_geom_idx on "{schema}"."{table_f}" using hash(vert{i})'
        #     self.execute(sqltext)

        # verbose('\tadding integer index')
        # sqltext = f'create index if not exists index_id on "{schema}"."{table_v}" (id)'
        # self.execute(sqltext)

        # for i in range(1, 8):
        #     sqltext = f'create index if not exists index_vert_{i} on "{schema}"."{table_f}" (vert{i}i)'
        #     self.execute(sqltext)

        # for i in range(1, 8):
        #     debug(f'joining vertices n. {i}')
        #     sqltext = f'update "{schema}"."{table_f}" set ' \
        #               f'vert{i}i = v.id from "{schema}"."{table_v}" as v ' \
        #               f'where vert{i} = v.point'
        #     self.execute(sqltext)
        #     debug(f'end joining vertices n. {i}')

        # debug(f'updating ii, jj, kk, dir, len in table: {table_v}')
        # for i in range(1, 8):
        #     verbose(f'\tprocessing n. {i}')
        #     sqltext = f'update "{schema}"."{table_v}" as v set ' \
        #               '(ii, jj, kk, dir, len) = ' \
        #               '(select ii{i}, jj{i}, kk{i}, dir{i}, len{i} ' \
        #               f' from "{schema}"."{table_f}" as s ' \
        #               f' where v.id = s.vert{i}i ' \
        #               ' limit 1' \
        #               ') ' \
        #               'where ii is null'
        #     self.execute(sqltext)

        # sqltext = f'alter table "{schema}"."{table_f}" drop column if exists id; ' \
        #           f'alter table "{schema}"."{table_f}" add column id serial'
        # self.execute(sqltext)

    def check_for_vertex_singularities2(self):
        """ Singularity check / repair for slanted faces (alternate implementation).

        Not currently wired into the CCT pipeline — the active path uses
        check_for_vertex_singularities(). Kept functional for future use.
        """
        cfg = self.cfg
        dirs_singular = np.array([[[+1, 0, 0], [+1, -1, 0], [+1, 0, -1], [+1, -1, -1]],
                                  [[0, 0, 0], [0, -1, 0], [0, 0, -1], [0, -1, -1]],
                                  [[0, 0, 0], [0, 0, -1], [+1, 0, 0], [+1, 0, -1]],
                                  [[0, -1, 0], [0, -1, -1], [+1, -1, 0], [+1, -1, -1]],
                                  [[0, 0, 0], [0, -1, 0], [+1, 0, 0], [+1, -1, 0]],
                                  [[0, 0, -1], [0, -1, -1], [+1, 0, -1], [1, -1, -1]]
                                  ])
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

        sqltext = 'CREATE INDEX IF NOT EXISTS slanted_faces_kji_idx ON "{0}"."{1}" (k,j,i); ' \
            .format(cfg.domain.case_schema, cfg.tables.slanted_faces)
        self.execute(sqltext)
        # exit(1)
        progress('Checking if vertices has 4 adjacent faces')
        sqltext = 'SELECT id, i,j,k, normx, normy, normz, ' \
                  '       wid, rid, lid, isterr, iswall, isroof,' \
                  '       ii1, ii2, ii3, ii4, ii5, ii6, ' \
                  '       jj1, jj2, jj3, jj4, jj5, jj6, ' \
                  '       kk1, kk2, kk3, kk4, kk5, kk6, ' \
                  '       dir1, dir2, dir3, dir4, dir5, dir6, ' \
                  '       CASE WHEN len1 = 0              THEN 1 ELSE NULL END, ' \
                  '       CASE WHEN len2 = 0              THEN 2 ELSE NULL END, ' \
                  '       CASE WHEN len3 = 0              THEN 3 ELSE NULL END, ' \
                  '       CASE WHEN len4 = 0 AND n_vert>4 THEN 4 ELSE NULL END, ' \
                  '       CASE WHEN len5 = 0 AND n_vert>5 THEN 5 ELSE NULL END, ' \
                  '       CASE WHEN len6 = 0 AND n_vert>6 THEN 6 ELSE NULL END,  ' \
                  '       ARRAY[ST_Z(vert1), ST_Y(vert1), ST_X(vert1)], ' \
                  '       ARRAY[ST_Z(vert2), ST_Y(vert2), ST_X(vert2)], ' \
                  '       ARRAY[ST_Z(vert3), ST_Y(vert3), ST_X(vert3)], ' \
                  '       ARRAY[ST_Z(vert4), ST_Y(vert4), ST_X(vert4)], ' \
                  '       ARRAY[ST_Z(vert5), ST_Y(vert5), ST_X(vert5)], ' \
                  '       ARRAY[ST_Z(vert6), ST_Y(vert6), ST_X(vert6)]' \
                  '       ' \
                  '  FROM "{0}"."{1}" ' \
                  '  WHERE (' \
                  '  len1 = 0 OR' \
                  '  len2 = 0 OR' \
                  '  len3 = 0 OR' \
                  '  len4 = 0 OR' \
                  '  len5 = 0 OR' \
                  '  len6 = 0) ' \
                  ''.format(cfg.domain.case_schema, cfg.tables.slanted_faces)
        singulars = self.execute(sqltext)

        # max id of slanted faces
        sqltext = 'SELECT MAX(id) FROM "{0}"."{1}"'.format(cfg.domain.case_schema, cfg.tables.slanted_faces)
        max_id = self.execute(sqltext)[0][0]

        to_insert = []
        polygons = []
        polygons_props = []
        polygons2 = {}
        for singular in singulars:
            id, i, j, k, normx, normy, normz = singular[0], singular[1], singular[2], singular[3], singular[4], \
            singular[5], singular[6]
            wid, rid, lid, isterr, iswall, isroof = singular[7], singular[8], singular[9], singular[10], singular[11], \
            singular[12]
            ii0 = [irun for irun in singular[13:19]]
            jj0 = [irun for irun in singular[19:25]]
            kk0 = [irun for irun in singular[25:31]]
            dirs0 = [irun for irun in singular[31:37]]
            sidx = [irun for irun in singular[37:43]]
            lastidx = 43
            x_vert, y_vert, z_vert = [], [], []
            ii, jj, kk, dirs = [], [], [], []
            for idx in range(6):
                if sidx[idx] is not None:
                    z_vert.append(singular[lastidx + idx][0])
                    y_vert.append(singular[lastidx + idx][1])
                    x_vert.append(singular[lastidx + idx][2])
                    ii.append(ii0[idx])
                    jj.append(jj0[idx])
                    kk.append(kk0[idx])
                    dirs.append(dirs0[idx])

            # check surrounding face of the vertex, there has to be 4 of them
            sqltext = 'SELECT COUNT(*) FROM "{0}"."{1}" ' \
                      'WHERE i={2} AND j={3} AND k={4} '

            for vidx in range(len(ii)):
                counter = 0
                for ndirs in range(4):
                    dk, dj, di = dirs_singular[dirs[vidx], ndirs]
                    count = self.execute(
                        sqltext.format(cfg.domain.case_schema, cfg.tables.slanted_faces, ii[vidx] + di, jj[vidx] + dj,
                                       kk[vidx] + dk))[0]
                    if count[0] == 0:
                        # new polygon, if not exists must be created
                        if not [ii[vidx] + di, jj[vidx] + dj, kk[vidx] + dk] in polygons:
                            # print('new polygon', ii[vidx]+di, jj[vidx]+dj, kk[vidx]+dk)

                            polygons.append([ii[vidx] + di, jj[vidx] + dj, kk[vidx] + dk])
                            polygons_props.append([wid, rid, lid, isterr, iswall, isroof, normx, normy, normz])
                            pidx = polygons.index([ii[vidx] + di, jj[vidx] + dj, kk[vidx] + dk])
                            polygons2[pidx] = []
                            polygons2[pidx].append(
                                [z_vert[vidx], y_vert[vidx], x_vert[vidx], kk[vidx], jj[vidx], ii[vidx]])
                        else:
                            # print('existing polygon', ii[vidx]+di, jj[vidx]+dj, kk[vidx]+dk)
                            pidx = polygons.index([ii[vidx] + di, jj[vidx] + dj, kk[vidx] + dk])
                            # check if vertex in not there already
                            if not [z_vert[vidx], y_vert[vidx], x_vert[vidx], kk[vidx], jj[vidx], ii[vidx]] in \
                                   polygons2[pidx]:
                                polygons2[pidx].append(
                                    [z_vert[vidx], y_vert[vidx], x_vert[vidx], kk[vidx], jj[vidx], ii[vidx]])
                    # counter += count[0]
                    # print(count, ii[vidx]+di, jj[vidx]+dj, kk[vidx]+dk)

        n_new_polygons = len(polygons)
        for npol in range(n_new_polygons):
            x_vert_new, y_vert_new, z_vert_new, ii_new, jj_new, kk_new, dir_new, len_new = [None for irun in
                                                                                            range(7)], [None for irun in
                                                                                                        range(7)], [None
                                                                                                                    for
                                                                                                                    irun
                                                                                                                    in
                                                                                                                    range(
                                                                                                                        7)], [
                None for irun in range(7)], [None for irun in range(7)], [None for irun in range(7)], [None for irun in
                                                                                                       range(7)], [None
                                                                                                                   for
                                                                                                                   irun
                                                                                                                   in
                                                                                                                   range(
                                                                                                                       7)]
            n_vert = len(polygons2[npol])
            i, j, k = polygons[npol]
            wid, rid, lid, isterr, iswall, isroof, normx, normy, normz = polygons_props[npol]
            # print(max_id+npol+1, k,j,i, n_vert,)
            for nv in range(n_vert):
                x_vert_new[nv] = polygons2[npol][nv][2]
                y_vert_new[nv] = polygons2[npol][nv][1]
                z_vert_new[nv] = polygons2[npol][nv][0]
                ii_new[nv] = polygons2[npol][nv][5]
                jj_new[nv] = polygons2[npol][nv][4]
                kk_new[nv] = polygons2[npol][nv][3]

            # Sort the point, no duplicity
            sa_corner = np.zeros(8, dtype='bool')
            k_temp = k - 1
            corner_id = -1 * np.ones(7, dtype='int')
            for idx in range(n_vert):
                if (ii_new[idx] == i) & (jj_new[idx] == j) & (kk_new[idx] == k_temp):
                    corner_id[idx] = 0
                elif (ii_new[idx] == i + 1) & (jj_new[idx] == j) & (kk_new[idx] == k_temp):
                    corner_id[idx] = 1
                elif (ii_new[idx] == i + 1) & (jj_new[idx] == j + 1) & (kk_new[idx] == k_temp):
                    corner_id[idx] = 2
                elif (ii_new[idx] == i) & (jj_new[idx] == j + 1) & (kk_new[idx] == k_temp):
                    corner_id[idx] = 3
                elif (ii_new[idx] == i) & (jj_new[idx] == j) & (kk_new[idx] == k_temp + 1):
                    corner_id[idx] = 4
                elif (ii_new[idx] == i + 1) & (jj_new[idx] == j) & (kk_new[idx] == k_temp + 1):
                    corner_id[idx] = 5
                elif (ii_new[idx] == i + 1) & (jj_new[idx] == j + 1) & (kk_new[idx] == k_temp + 1):
                    corner_id[idx] = 6
                elif (ii_new[idx] == i) & (jj_new[idx] == j + 1) & (kk_new[idx] == k_temp + 1):
                    corner_id[idx] = 7
            adj_corners = corners + np.array([k_temp, j, i])
            for idx in range(n_vert):
                if corner_id[idx] != -1:
                    # print('corner: ', corner_id[idx], ' is Solid')
                    sa_corner[corner_id[idx]] = True

            ii, jj, kk, dirs, lens, x_vert, y_vert, z_vert = [None for irun in range(7)], [None for irun in range(7)], [
                None for irun in range(7)], [None for irun in range(7)], [None for irun in range(7)], [None for irun in
                                                                                                       range(7)], [None
                                                                                                                   for
                                                                                                                   irun
                                                                                                                   in
                                                                                                                   range(
                                                                                                                       7)], [
                None for irun in range(7)]
            ivert = 0
            for idx in range(n_vert):
                interfaces = 0
                for idir in range(3):
                    dirr = dir_corns[corner_id[idx], idir]
                    # is air cell in dir?
                    if not sa_corner[dirr]:
                        interfaces += 1
                        ii[ivert] = int(ii_new[idx])
                        jj[ivert] = int(jj_new[idx])
                        kk[ivert] = int(kk_new[idx])
                        x_vert[ivert] = x_vert_new[idx]
                        y_vert[ivert] = y_vert_new[idx]
                        z_vert[ivert] = z_vert_new[idx]
                        dirs[ivert] = int(vert2dirs[corner_id[idx], idir])
                        lens[ivert] = 0.0
                        ivert += 1

            n_vert = ivert + 1
            x_vert[ivert] = x_vert[0]
            y_vert[ivert] = y_vert[0]
            z_vert[ivert] = z_vert[0]
            ii[ivert] = ii[0]
            jj[ivert] = jj[0]
            kk[ivert] = kk[0]
            dirs[ivert] = dirs[0]
            lens[ivert] = lens[0]

            to_insert.append((max_id + npol + 1, int(k), int(j), int(i), int(n_vert),
                              wid, rid, lid,
                              isterr, iswall, isroof,
                              ii[0], ii[1], ii[2], ii[3], ii[4], ii[5], ii[6],
                              jj[0], jj[1], jj[2], jj[3], jj[4], jj[5], jj[6],
                              kk[0], kk[1], kk[2], kk[3], kk[4], kk[5], kk[6],
                              lens[0], lens[1], lens[2], lens[3], lens[4], lens[5], lens[6],
                              dirs[0], dirs[1], dirs[2], dirs[3], dirs[4], dirs[5], dirs[6],
                              normz, normy, normx, 0.0,
                              x_vert[0], y_vert[0], z_vert[0], cfg.srid_palm,
                              x_vert[1], y_vert[1], z_vert[1], cfg.srid_palm,
                              x_vert[2], y_vert[2], z_vert[2], cfg.srid_palm,
                              x_vert[3], y_vert[3], z_vert[3], cfg.srid_palm,
                              x_vert[4], y_vert[4], z_vert[4], cfg.srid_palm,
                              x_vert[5], y_vert[5], z_vert[5], cfg.srid_palm,
                              x_vert[6], y_vert[6], z_vert[6], cfg.srid_palm,))
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
                  '        ST_SetSRID(ST_MakePoint(%s, %s, %s), %s), ' \
                  '        ST_SetSRID(ST_MakePoint(%s, %s, %s), %s), ' \
                  '        ST_SetSRID(ST_MakePoint(%s, %s, %s), %s), ' \
                  '        ST_SetSRID(ST_MakePoint(%s, %s, %s), %s), ' \
                  '        ST_SetSRID(ST_MakePoint(%s, %s, %s), %s), ' \
                  '        ST_SetSRID(ST_MakePoint(%s, %s, %s), %s), ' \
                  '        ST_SetSRID(ST_MakePoint(%s, %s, %s), %s) ' \
                  '        )  '.format(cfg.domain.case_schema, cfg.tables.slanted_faces)

        self.execute_batch(sqltext, to_insert)
        self.conn.commit()

        debug('Updating empty centers')
        sqltext = 'UPDATE "{0}"."{1}" SET center = ' \
                  'ST_SetSRID(ST_MakePoint(' \
                  ' (ST_X(vert1) + ST_X(vert2) + ' \
                  '       CASE WHEN n_vert > 3 THEN ST_X(vert3) ELSE 0.0 END + ' \
                  '       CASE WHEN n_vert > 4 THEN ST_X(vert4) ELSE 0.0 END + ' \
                  '       CASE WHEN n_vert > 5 THEN ST_X(vert5) ELSE 0.0 END + ' \
                  '       CASE WHEN n_vert > 6 THEN ST_X(vert6) ELSE 0.0 END) / (n_vert - 1), ' \
                  ' (ST_Y(vert1) + ST_Y(vert2) + ' \
                  '       CASE WHEN n_vert > 3 THEN ST_Y(vert3) ELSE 0.0 END + ' \
                  '       CASE WHEN n_vert > 4 THEN ST_Y(vert4) ELSE 0.0 END + ' \
                  '       CASE WHEN n_vert > 5 THEN ST_Y(vert5) ELSE 0.0 END + ' \
                  '       CASE WHEN n_vert > 6 THEN ST_Y(vert6) ELSE 0.0 END) / (n_vert - 1),' \
                  ' (ST_Z(vert1) + ST_Z(vert2) + ' \
                  '       CASE WHEN n_vert > 3 THEN ST_Z(vert3) ELSE 0.0 END + ' \
                  '       CASE WHEN n_vert > 4 THEN ST_Z(vert4) ELSE 0.0 END + ' \
                  '       CASE WHEN n_vert > 5 THEN ST_Z(vert5) ELSE 0.0 END + ' \
                  '       CASE WHEN n_vert > 6 THEN ST_Z(vert6) ELSE 0.0 END) / (n_vert - 1)' \
                  '), %s) ' \
                  'WHERE center IS NULL '.format(cfg.domain.case_schema, cfg.tables.slanted_faces)
        self.execute(sqltext, (cfg.srid_palm,))
