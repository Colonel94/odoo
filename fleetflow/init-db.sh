#!/bin/sh
set -eu
# psql variable quoting keeps the generated secret out of SQL interpolation.
psql --username postgres --dbname postgres --set=ON_ERROR_STOP=1 --set=db_password="$FLEETFLOW_DB_PASSWORD" <<'SQL'
CREATE ROLE fleetflow LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'db_password';
CREATE DATABASE fleetflow OWNER fleetflow;
SQL
