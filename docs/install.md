# Installation

## Prerequisites

### PostgreSQL + PostGIS

PALM-GeM requires PostgreSQL with the PostGIS, intarray, and PostGIS Raster extensions.

You have two options for the database: run it in **Docker** (quickest, recommended) or install it **natively**. The GIS import tools (`ogr2ogr` / `raster2pgsql` / `psql`) always run on the host either way — see [GDAL tools](#gdal-tools) below.

#### Option A — Docker (recommended)

A `docker-compose.yml` at the repo root runs the database only, using the official `postgis/postgis` image. It reads its credentials from the same `.env` file the application uses, and on first start it **automatically enables the required extensions and loads the custom SQL functions** from `src/sql_function/` — so the "Load SQL functions" step below is not needed.

```bash
cp .env.example .env        # set PALM_GEM_DB_USER / _PASSWORD / _NAME / _PORT
docker compose up -d        # start PostGIS, published on localhost:5432
docker compose logs -f      # watch first-init progress (extensions + functions)
```

Data persists in the named volume `palm_gem_pgdata`. To start over from a clean database (re-running the init scripts):

```bash
docker compose down -v      # WARNING: deletes the data volume
docker compose up -d
```

Then jump to [Python setup](#python-setup).

#### Option B — Native install

**Linux:**
```bash
sudo apt install postgresql postgis  # Debian/Ubuntu
# or
sudo dnf install postgresql postgresql-contrib postgis  # Fedora/RHEL
systemctl start postgresql
```

**Windows:**
1. Download PostgreSQL from [enterprisedb.com](https://www.enterprisedb.com/downloads/postgres-postgresql-downloads) and run the installer.
2. During installation, launch **Stack Builder** and install **PostGIS** from the Spatial Extensions category.
3. Open pgAdmin 4 and connect to your server.
4. Create a database (e.g., `palm_static`) and set its owner.
5. In the query tool, enable extensions in your database:
```sql
CREATE EXTENSION postgis;
CREATE EXTENSION postgis_topology;
CREATE EXTENSION intarray;
CREATE EXTENSION postgis_raster;
GRANT ALL ON spatial_ref_sys TO your_user;
```

### GDAL tools

`ogr2ogr` (vector import) and `raster2pgsql` + `psql` (raster import) must be installed **on the host** and their paths set in your user config (see [Configuration](configuration_docs.md)). This is required even when the database runs in Docker: the import tools shell out on the host and connect to the database over `localhost`, so the raw GIS files never need to be copied into the container.

**Linux:** Usually available via `gdal-bin` and `postgresql-client`.

**Windows (OSGeo4W):**
1. Download [OSGeo4W](https://trac.osgeo.org/osgeo4w/) and run the network installer.
2. Install `gdal` and `gdal-ecw` packages.
3. Default tool paths:
   - `ogr2ogr`: `C:\OSGeo4W\bin\ogr2ogr.exe`
   - `psql`: `C:\Program Files\PostgreSQL\16\bin\psql.exe`
   - `raster2pgsql`: `C:\Program Files\PostgreSQL\16\bin\raster2pgsql.exe`

Set these in your user config YAML:
```yaml
ogr2ogr_path: 'C:\OSGeo4W\bin\ogr2ogr.exe'
raster2psql_path: 'C:\Program Files\PostgreSQL\16\bin\raster2pgsql.exe'
psql_path: 'C:\Program Files\PostgreSQL\16\bin\psql.exe'
```

---

## Python setup

Python 3.10+ is required.

```bash
# Create and activate virtual environment
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

To run the test suite, also install the development dependencies:

```bash
pip install -r requirements-dev.txt   # pulls in requirements.txt + pytest
pytest -m "not integration"           # unit tests (no database needed)
```

---

## Database credentials

Two options — use whichever fits your workflow:

**Option A — `.env` file** (recommended for local development):
```bash
cp .env.example .env
# Edit .env with your actual credentials
```
The same `.env` file is read by `docker-compose.yml`, so when you use the Docker database the application and the container share one set of credentials.

**Option B — user config YAML:**
```yaml
database:
  host: localhost
  port: 5432
  user: postgres
  password: yourpassword
  database: palm_static
pg_owner: postgres
```

---

## Load SQL functions

> **Skip this section if you used Docker (Option A)** — the container loads these functions automatically on first init.

PALM-GeM requires four custom PostGIS functions loaded into your database. For a **native install**, run each file once:

```bash
psql -h localhost -p 5432 -U postgres -d palm_static -f src/sql_function/palm_create_grid.sql
psql -h localhost -p 5432 -U postgres -d palm_static -f src/sql_function/palm_fill_building_holes.sql
psql -h localhost -p 5432 -U postgres -d palm_static -f src/sql_function/palm_surfaces.sql
psql -h localhost -p 5432 -U postgres -d palm_static -f src/sql_function/palm_tree_grid.sql
```

---

## Running PALM-GeM

Place your configuration file in the `config/` directory and run:

```bash
python main.py -c your_config.yaml
```

The config file path is relative to `config/`. Output files are written to `output/`, logs to `logs/`, and visual checks to `visual_check/`.

See the [example configurations](../examples/) and [configuration reference](configuration_docs.md) for details.
