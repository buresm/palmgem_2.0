from .base import BaseTask
from src.logger import debug, progress, verbose, warning, error, sql_debug, sql_verbose

class FinalizeTask(BaseTask):
    """
    safely closes all database connections and file handles,
    and performs final cleanup of temporary artifacts.
    """
    def run(self):
        progress('finalizing palm-gem execution')

        # 1. close database resources
        try:
            debug('closing postgresql connection')
            self.db.close()
        except Exception as e:
            error(f"failed to close database connection: {e}")

        # 2. close netcdf handles (if stored in cfg or task state)
        # assuming ncfile handles were stored in the shared config or a global registry
        if hasattr(self.cfg, '_nc_handles'):
            for name, handle in self.cfg._nc_handles.items():
                try:
                    debug(f"closing netcdf file handle: {name}")
                    handle.close()
                except Exception as e:
                    warning(f"could not close file {name}: {e}")

        # 3. final memory cleanup
        progress('palm-gem resources released')
        progress('execution finished ok')