-- Enable the PostGIS extensions PALM-GeM requires. Runs once, on first init of
-- an empty data volume. Idempotent: safe even though the base image already
-- creates postgis/postgis_topology.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS intarray;
CREATE EXTENSION IF NOT EXISTS postgis_raster;
