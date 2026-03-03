#!/bin/bash
# Initialize multiple databases for shared PostgreSQL instance
# This script runs automatically on first container start

set -e

# Function to create database and user
create_database() {
    local database=$1
    local user=$2

    echo "Creating database '$database' with user '$user'..."

    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        -- Create user if not exists
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$user') THEN
                CREATE USER $user WITH PASSWORD '$POSTGRES_PASSWORD';
            END IF;
        END
        \$\$;

        -- Create database if not exists
        SELECT 'CREATE DATABASE $database OWNER $user'
        WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$database')\gexec

        -- Grant privileges
        GRANT ALL PRIVILEGES ON DATABASE $database TO $user;
EOSQL

    echo "Database '$database' created successfully."
}

# Function to enable extensions on a database
enable_extensions() {
    local database=$1
    shift
    local extensions=("$@")

    for ext in "${extensions[@]}"; do
        echo "Enabling extension '$ext' on database '$database'..."
        psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$database" <<-EOSQL
            CREATE EXTENSION IF NOT EXISTS $ext;
EOSQL
    done
}

echo "========================================"
echo "Initializing shared PostgreSQL databases"
echo "========================================"

# Create MLflow database
create_database "mlflow_db" "mlflow"

# Create Ray Compute database
create_database "ray_compute" "ray_compute"

# Create Inference database (with pgvector for RAG memory)
create_database "inference" "inference"
enable_extensions "inference" "vector" "pg_trgm"

# Create Chat API database (with pgvector for codebase indexing)
create_database "chat_api" "chat_api"
enable_extensions "chat_api" "vector" "pg_trgm"

# Create FusionAuth database
create_database "fusionauth" "fusionauth"

# Create Nessie catalog database (Iceberg metadata + version control)
create_database "nessie" "nessie"

echo "========================================"
echo "All databases initialized successfully!"
echo "========================================"

# List all databases
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c "\l"
