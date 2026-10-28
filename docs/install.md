# Installation

## Prerequisites

### PostgreSQL + PostGIS

PALM-GeM requires PostgreSQL with the PostGIS, intarray, and PostGIS Raster extensions.

You can run the database in **Docker**, install it **natively** (Linux or Windows), or run a Linux install inside **WSL** on Windows. PALM-GeM itself does not care which: it only needs a host, port and credentials (see [Database credentials](#database-credentials)), so switching later is a configuration change. The GIS import tools (`ogr2ogr` / `raster2pgsql` / `psql`) always run on the host either way — see [GDAL tools](#gdal-tools) below.

| | Docker (A) | Native (B) | WSL (C) |
|---|---|---|---|
| Setup effort | one command; extensions + SQL functions load automatically | installer + enable extensions + load SQL functions once | Linux install inside WSL + same one-time steps as native |
| Platforms | Linux, macOS, Windows | all | Windows only |
| Matching `psql`/`raster2pgsql` | install separately on the host | come with the server install | install separately on Windows |
| Clean reset | `docker compose down -v` | drop/recreate the database | drop/recreate the database |
| Good fit | most users; reproducible, pinned PostGIS version | Windows users who already have PostgreSQL; servers/HPC where Docker is not allowed | developers already working in WSL |

Notes:
- Docker Desktop is free for personal, education and small-organisation use but needs a paid subscription in larger commercial organisations; Docker Engine on Linux is free.
- WSL may stop an idle distribution and restart its services, which can interrupt a long run. A native Windows service or Docker with `restart: unless-stopped` does not have this problem.
- Whichever you pick, keep one database per machine for real cases and tests, so test runs and case data do not end up on different servers.

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
6. Load the SQL functions (see [Load SQL functions](#load-sql-functions)). The `psql` and `raster2pgsql` from this install are the import tools to put in your config.

#### Option C — PostgreSQL inside WSL (Windows)

Install the Linux packages in your WSL distribution (Ubuntu shown) and let PostgreSQL listen for connections from Windows:

```bash
sudo apt install postgresql postgis postgresql-16-postgis-3
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';"
sudo -u postgres createdb palm_static
# listen_addresses = '*' in /etc/postgresql/16/main/postgresql.conf
# host all all 0.0.0.0/0 scram-sha-256  in /etc/postgresql/16/main/pg_hba.conf
sudo service postgresql restart
```

With WSL2's default localhost forwarding, Windows reaches it as `localhost:5432`; otherwise use the WSL address from `wsl hostname -I`. Then enable the extensions (same SQL as Option B) and [load the SQL functions](#load-sql-functions). The GDAL tools still run on Windows, so install them there as described below.

### GDAL tools

`ogr2ogr` (vector import) and `raster2pgsql` + `psql` (raster import) must be installed **on the host**. This is required even when the database runs in Docker: the import tools shell out on the host and connect to the database over `localhost`, so the raw GIS files never need to be copied into the container. They are only used by the `gis_import` task; staged runs that start from an already-imported input schema do not need them.

By default the tools are called by name (`ogr2ogr_path: ogr2ogr`, `psql_path: psql`, `raster2psql_path: raster2pgsql`), so they must be on your `PATH`; otherwise set full paths in your user config.

**Linux:** Usually available via `gdal-bin`, `postgresql-client` and `postgis` (for `raster2pgsql`).

**Windows:**
1. `psql` and `raster2pgsql` come with the PostgreSQL + PostGIS (StackBuilder) install in `C:\Program Files\PostgreSQL\<version>\bin\`. With a Docker database you still need this client install on Windows for the two tools.
2. `ogr2ogr`: install [OSGeo4W](https://trac.osgeo.org/osgeo4w/) (network installer, package `gdal`). It lands in `C:\OSGeo4W\bin\` or, for a per-user install, `C:\Users\<you>\AppData\Local\Programs\OSGeo4W\bin\`.

Set the paths in your user config YAML (adjust the PostgreSQL version):
```yaml
ogr2ogr_path: 'C:\OSGeo4W\bin\ogr2ogr.exe'
raster2psql_path: 'C:\Program Files\PostgreSQL\18\bin\raster2pgsql.exe'
psql_path: 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
```

---

## Python setup

Python 3.10–3.12 is required (the pinned numpy 2.0 / vtk 9.3 wheels are not available for 3.13; development uses 3.12).

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

---

## Database credentials

Two options — use whichever fits your workflow. If both are set, **the `.env` values win**: every `PALM_GEM_DB_*` variable that is present overrides the matching key in the `database:` section of the YAML (also for the test config in `tests/configs/`). A config that "ignores" its host or port is usually being overridden by `.env`; for a one-off run against another server, set the variable in the shell, e.g. `PALM_GEM_DB_PORT=5432`.

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

PALM-GeM requires four custom PostGIS functions loaded into your database. For a **native or WSL install**, run each file once:

```bash
psql -h localhost -p 5432 -U postgres -d palm_static -f src/sql_function/palm_create_grid.sql
psql -h localhost -p 5432 -U postgres -d palm_static -f src/sql_function/palm_fill_building_holes.sql
psql -h localhost -p 5432 -U postgres -d palm_static -f src/sql_function/palm_surfaces.sql
psql -h localhost -p 5432 -U postgres -d palm_static -f src/sql_function/palm_tree_grid.sql
```

On Windows (PowerShell, from the repository root), the extensions and all functions in one go:

```powershell
$psql = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
& $psql -h localhost -U postgres -d palm_static -v ON_ERROR_STOP=1 -f docker\initdb\10-extensions.sql
Get-ChildItem src\sql_function\*.sql | ForEach-Object { & $psql -h localhost -U postgres -d palm_static -v ON_ERROR_STOP=1 -f $_.FullName }
```

The functions use `CREATE OR REPLACE`, so re-running this after an update is safe.

---

## Running PALM-GeM

```bash
python main.py -c your_config.yaml
```

The config file is looked up in `config/` first; if it is not there, the path is taken as given (relative to the current directory, or absolute), so `-c config/your_config.yaml` and `-c examples/prague_lod2/prague_lod2.yaml` work too. The [Prague LOD2 example](../examples/prague_lod2/prague_lod2.md) ships all its input data and is the quickest first run.

A run executes `setup`, then the tasks in `run_tasks`, then `finalize`, and aborts at the first failing task. With `case_schema` = `<domain.name>_<domain.scenario>` (or just the name when the scenario is empty), it writes:

| What | Where |
|------|-------|
| static / SLURB driver | `output/<case_schema>_static.nc`, `output/<case_schema>_slurb.nc` (override with `domain.static_driver_file` / `slurb_driver_file`) |
| log of the last run | `logs/<case_schema>` (overwritten by the next run of the same case) |
| PNG previews (`visual_check.enabled`) | `visual_check/<case_schema>/` |
| QA report / QGIS snapshot (`qa_report`, `qgis_export` tasks) | `output/<case_schema>_qa_report.html`, `output/<case_schema>.gpkg` |

Every driver is validated against the PALM Input Data Standard right after it is written; findings are in the log (see [checking results](visualization.md)). See [tasks.md](tasks.md) for the task list and for splitting a pipeline across several runs, the [example configurations](../examples/), and the [configuration reference](configuration_docs.md).

---

## Testing

Install the development dependencies first:

```bash
pip install -r requirements-dev.txt   # pulls in requirements.txt + pytest
```

**Unit tests**: no database needed:

```bash
pytest -m "not integration"
```

**Integration tests** (`@pytest.mark.integration`) need a running PostGIS database with the extensions and [SQL functions](#load-sql-functions) loaded. They connect with the `database:` block of `tests/configs/test.yaml`. As everywhere, `PALM_GEM_DB_*` variables in `.env` or the shell override it. When no database is reachable they are **skipped** with the reason, not failed.

```bash
pytest -m integration                 # integration tests only
pytest                                # everything
pytest -k coherence                   # tests whose name matches
```

What the integration tests need:

| Test | Needs | Writes |
|------|-------|--------|
| `tests/integration/test_canyon_coherence.py` | the database only | creates and drops its own schema `pytest_pg74_coherence` |
| `tests/integration/test_workflow.py` | the input schema `inputs_carmine_prague_example` (landcover + DEM of the 1 × 1 km Prague test domain, EPSG:32633). These inputs are **not shipped** with the repository; ask the maintainers for them | **drops and rebuilds** the case schema `prague_example`; the driver goes to a pytest temp folder |

Use a dedicated database (or at least no real case called `prague_example`) for the workflow test. It runs the pipeline once like `main.py`, then checks the structure, PIDS compliance with the consistency rules, and the values against `tests/baselines/prague_example_static.nc`. The baseline comparison is currently an expected failure (xfail) until the baseline is regenerated.
