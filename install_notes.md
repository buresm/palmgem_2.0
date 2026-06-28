install wsl ubuntu

run WSL

cd /home/bures/

sudo apt-get install postgresql git postgis
sudo apt-get install python3.12
sudo apt install python3.12-venv

sudo apt-get install gdal-bin libgdal-dev
export CPLUS_INCLUDE_PATH=/usr/include/gdal
export C_INCLUDE_PATH=/usr/include/gdal



mkdir palm
sudo chown -R $user:$user palm
cd palm

sudo git clone https://github.com/PALM-tools/palmgem.git

cd palmgem

sudo python3 -m venv .venv

source .venv/bin/activate

# psycopg is quite problematic and problem with ownership in wsl
# Remove from requirement psycopg2
sudo .venv/bin/pip install psycopg2-binary
sudo .venv/bin/pip install -r requirements.txt
sudo .venv/bin/pip install GDAL==$(gdal-config --version)

sudo -u postgres -i

psql -U postgres -d postgres -c "CREATE DATABASE palm_static;"

psql -U postgres -d palm_static -c "CREATE EXTENSION postgis;"
psql -U postgres -d palm_static -c "CREATE EXTENSION postgis_topology;"
psql -U postgres -d palm_static -c "CREATE EXTENSION intarray;"
psql -U postgres -d palm_static -c "CREATE EXTENSION postgis_raster;"

psql -U postgres -d palm_static -c "GRANT ALL ON DATABASE palm_static TO postgres WITH GRANT OPTION;"
psql -U postgres -d palm_static -c "GRANT ALL ON spatial_ref_sys TO postgres;"

psql -U postgres -d palm_static -c "GRANT ALL ON DATABASE palm_static TO postgres WITH GRANT OPTION;"
psql -U postgres -d palm_static -c "GRANT ALL ON spatial_ref_sys TO postgres;"

psql -c "ALTER USER postgres PASSWORD 'postgres';"

psql -h localhost -U postgres -d palm_static -f utils/palm_create_grid.sql
psql -h localhost -U postgres -d palm_static -f utils/palm_fill_building_holes.sql
psql -h localhost -U postgres -d palm_static -f utils/palm_surfaces.sql
psql -h localhost -U postgres -d palm_static -f utils/palm_tree_grid.sql


sudo apt-get install ncview


[//]: # (-- database extensions)

[//]: # (create extension postgis;)

[//]: # (create extension postgis_topology;)

[//]: # (create extension intarray;)

[//]: # (create extension postgis_raster;)

[//]: # ()
[//]: # (-- permissions and password)

[//]: # (alter user postgres password 'postgres';)

[//]: # (grant all on database palm_static to postgres with grant option;)

[//]: # (grant all on spatial_ref_sys to postgres;)


# Windows 11
* Download and install https://www.enterprisedb.com/downloads/postgres-postgresql-downloads v18
* install via stack builder postgis extension
* https://trac.osgeo.org/osgeo4w/ -- express install
* C:\Users\bures\AppData\Local\Programs\OSGeo4W\bin
* C:\Program Files\PostgreSQL\18\bin

* add paths to config

# Run postgresql in wsl
* sudo service postgresql start

# Connect from windows to wsl postgresql
- needs to know host and port
- default port is 5432
- host is localhost or 127.0.0.1   172.31.196.234


files 
bures@burespc:~$ sudo nano /etc/postgresql/16/main/postgresql.conf
bures@burespc:~$ sudo nano /etc/postgresql/16/main/pg_hba.conf

needs to be modified to allow connections from windows host
- add line: host    all             all 0.0.0.0/0
- listen_addresses = '*'
- restart postgresql: sudo service postgresql restart