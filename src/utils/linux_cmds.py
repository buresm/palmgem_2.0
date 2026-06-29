import subprocess
import logging
import os
from pathlib import Path
from src.logger import progress, debug, warning, error, verbose

def run_shell(command):
    """Safely runs a linux command and logs output."""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, check=True)
        debug(f"Command success: {command}")
        return result.stdout
    except subprocess.CalledProcessError as e:
        error(f"Command failed: {e.stderr}")
        raise

class ShapefileImporter:
    """Handles vector data import using ogr2ogr."""

    def __init__(self, db_config):
        self.db = db_config
        # Connection string for OGR
        self.pg_conn = (
            f"PG:host={db_config['host']} "
            f"user={db_config['user']} "
            f"dbname={db_config['database']} "
            f"password={db_config['password']} "
            f"port={db_config.get('port', 5432)}"
        )

    def import_shp(self, file_path, schema_name, table_name, srid, idx='gid', ogr2ogr_exe='ogr2ogr', overwrite=True):
        """Executes ogr2ogr command."""
        cmd = [
            str(Path(ogr2ogr_exe)), # Convert to clean plain string for Windows
            "-f", "PostgreSQL",
            self.pg_conn,
            str(Path(file_path)),   # Convert file path to clean plain string too
            "-nln", f"{schema_name}.{table_name}",
            "-nlt", "PROMOTE_TO_MULTI",
            "-t_srs", f"EPSG:{srid}",
            "-lco", "GEOMETRY_NAME=geom",
            "-lco", "PRECISION=NO",
            "-lco", f"FID={idx}",
        ]

        if overwrite:
            cmd.append("-overwrite")

        debug(f"Importing vector: {file_path} to {schema_name}.{table_name}")
        verbose(cmd)
        return self._execute(cmd)

    def _execute(self, cmd):
        # 1. Clean out the conflicting global windows variables inside this call
        clean_env = os.environ.copy()
        clean_env.pop("PROJ_LIB", None)
        clean_env.pop("PROJ_DATA", None)

        # 2. Add the clean_env block to the execution parameters
        result = subprocess.run(cmd, env=clean_env, capture_output=True, text=True)

        # A non-zero exit is not always a real failure: benign dynamic-loader
        # warnings (e.g. "libpq.so.5: no version information available") can make
        # ogr2ogr exit non-zero on some Linux setups even though the table was
        # imported. Surface the detail and let the caller confirm against the DB
        # rather than aborting on the exit code alone.
        if result.returncode != 0:
            warning(f"ogr2ogr exited {result.returncode}: {result.stderr}")
            raise RuntimeError(result.stderr)
        return result.stdout


class RasterImporter:
    """Handles raster data import using raster2pgsql and psql."""

    def __init__(self, db_config):
        self.db = db_config
        # Set environment variable for psql password to avoid prompt
        self.env = {**os.environ, "PGPASSWORD": str(db_config['password'])}

    def import_tiff(self, file_path, table_name, schema_name, srid,
                    psql, raster2psql,
                    overwrite=True):
        """
        Runs: raster2pgsql -s <srid> -I -C -M -t <tile> <file> <table_name> | psql
        """
        # -I: Create spatial index
        # -C: Apply raster constraints
        # -M: Vacuum analyze
        target_table = f"{schema_name}.{table_name}"
        mode = "-d" if overwrite else "-a"

        r2p_cmd = [
            Path(raster2psql),
            "-s", str(srid),
            "-I", "-C", "-M",
            "-t", "auto",
            mode,
            str(Path(file_path).resolve()),
            target_table
        ]

        # 3. Build the psql command as a LIST
        psql_cmd = [
            Path(psql),
            "-h", self.db['host'],
            "-U", self.db['user'],
            "-d", self.db['database'],
            "-p", str(self.db.get('port', 5432)),
            "-q"  # Quiet mode to reduce clutter
        ]

        full_env = os.environ.copy()
        # Add the password directly to this specific subprocess environment
        full_env["PGPASSWORD"] = str(self.db.get('password', ''))

        debug(f"Importing raster: {file_path} to {table_name}")
        try:
            # Start the first process (raster2psql)
            # We don't use text=True here to keep the stream as binary bytes
            p1 = subprocess.Popen(r2p_cmd, stdout=subprocess.PIPE, env=full_env)

            # Start psql (Pipe 2) - It will automatically pick up PGPASSWORD from full_env
            p2 = subprocess.run(
                psql_cmd,
                stdin=p1.stdout,
                env=full_env,  # This is where the password "magic" happens
                capture_output=True,
                text=True
            )
            # Allow p1 to receive a SIGPIPE if p2 exits early
            p1.stdout.close()
            p1.wait()

            if p2.returncode != 0:
                debug(f"Raster Import Failed: {p2.stderr}")
                raise RuntimeError(f"PostgreSQL Error: {p2.stderr}")

            if p1.returncode != 0:
                # Note: raster2psql might fail if file doesn't exist
                raise RuntimeError(f"raster2psql failed with code {p1.returncode}")

            return p2.stdout

        except Exception as e:
            debug(f"Subprocess Execution Error: {str(e)}")
            raise