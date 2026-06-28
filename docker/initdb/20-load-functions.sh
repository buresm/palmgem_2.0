#!/bin/bash
# Load PALM-GeM's custom PostGIS functions on first init of an empty data
# volume. The functions live in src/sql_function/ on the host and are mounted
# read-only at /sql_function by docker-compose.yml.
set -euo pipefail

for f in /sql_function/*.sql; do
    echo "PALM-GeM init: loading $f"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$f"
done
