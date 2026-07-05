#!/bin/bash
set -e

# Data directory for local Postgres inside container
PGDATA="/app/postgres_data"

# Ensure PGDATA exists and is empty before initdb if it doesn't exist
if [ ! -d "$PGDATA/base" ]; then
    echo "Initializing database..."
    mkdir -p "$PGDATA"
    initdb -D "$PGDATA" --auth-local=trust --auth-host=trust
fi

# Start PostgreSQL listening on localhost:5432
# Using /tmp as unix socket directory to avoid permission issues in /var/run/postgresql
postgres -D "$PGDATA" -h 127.0.0.1 -k /tmp > /tmp/postgres.log 2>&1 &
PG_PID=$!

echo "Waiting for PostgreSQL to start..."
until pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; do
    sleep 1
done
echo "PostgreSQL started."

# Create database 'andavar' and user 'andavar' if they do not exist
# Since initdb was run by the 'andavar' user, that user is already a superuser.
# We set its password to 'andavar' so connections using the connection string succeed.
psql -h 127.0.0.1 -p 5432 -d postgres -c "ALTER USER andavar WITH PASSWORD 'andavar';" || true
psql -h 127.0.0.1 -p 5432 -d postgres -c "SELECT 1 FROM pg_database WHERE datname = 'andavar'" | grep -q 1 || \
    psql -h 127.0.0.1 -p 5432 -d postgres -c "CREATE DATABASE andavar OWNER andavar;"

# Execute CMD passed to docker run
exec "$@"
