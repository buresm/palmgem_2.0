from .base import BaseTask
from src.logger import debug, progress, verbose, warning, error, sql_debug, sql_verbose


class SetupTask(BaseTask):
    """
    derives spatial metadata, handles unit conversions, and
    validates the configuration before processing begins.
    """

    def run(self):
        self.geospatial_initialization()

    def geospatial_initialization(self):

        progress('setting up domain configuration and spatial metadata')

        # 0. validate critical srid settings up front, before any query relies on them
        self.validate_projections()

        # 1. derive vertical resolution fallback
        if self.cfg.domain.dz <= 0.0:
            verbose("dz <= 0: setting vertical resolution to match dx")
            self.cfg.domain.update_setting('dz', self.cfg.domain.dx)

        # 2. calculate domain origins (lower-left corner)
        # origin = center - (size / 2)
        origin_x = self.cfg.domain.cent_x - self.cfg.domain.nx * self.cfg.domain.dx / 2.0
        origin_y = self.cfg.domain.cent_y - self.cfg.domain.ny * self.cfg.domain.dy / 2.0

        self.cfg.domain.update_setting('origin_x', origin_x)
        self.cfg.domain.update_setting('origin_y', origin_y)

        # define the transformation query using strictly lower case functions
        sql_transform = """
            select 
                st_x(st_transform(st_setsrid(st_point(%s, %s), %s), %s)), 
                st_y(st_transform(st_setsrid(st_point(%s, %s), %s), %s))
        """

        # execute using the task's execution handler and dot-notation configuration
        res = self.execute(sql_transform, (
            self.cfg.domain.origin_x, self.cfg.domain.origin_y, self.cfg.srid_palm, self.cfg.srid_wgs84,
            self.cfg.domain.origin_x, self.cfg.domain.origin_y, self.cfg.srid_palm, self.cfg.srid_wgs84
        ))

        # extract and store the results
        origin_lon, origin_lat = res[0]
        self.cfg.domain.update_setting('origin_lon', origin_lon)
        self.cfg.domain.update_setting('origin_lat', origin_lat)

        debug(f'domain origin lon,lat: {origin_lon}, {origin_lat}')

        progress("domain '{}' (scenario: '{}'): {}x{} cells @ {} m resolution, center ({}, {})",
                 self.cfg.domain.name, self.cfg.domain.scenario,
                 self.cfg.domain.nx, self.cfg.domain.ny, self.cfg.domain.dx,
                 self.cfg.domain.cent_x, self.cfg.domain.cent_y)
        debug(f'resolution (dx,dy,dz): ({self.cfg.domain.dx}, {self.cfg.domain.dy}, {self.cfg.domain.dz})')
        debug(f'origin coordinates (x,y): ({origin_x}, {origin_y})')

    def validate_projections(self):
        """ ensures required srid settings are present to avoid sql crashes later """
        # keys actually used downstream: srid_palm/srid_wgs84 here, srid/srid_utm in
        # the fishnet + envelope tasks.
        required = ['srid', 'srid_palm', 'srid_wgs84', 'srid_utm']
        for key in required:
            # using dot-notation as requested
            try:
                val = getattr(self.cfg, key)
                verbose(f"projection {key} confirmed as {val}")
            except AttributeError:
                error(f"missing critical projection setting: {key}")
                raise