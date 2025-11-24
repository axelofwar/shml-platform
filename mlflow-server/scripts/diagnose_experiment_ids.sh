#!/bin/bash
# Fix experiment ID database schema and clean up invalid experiments
set -e

cd /home/axelofwar/Desktop/Projects/mlflow-server

# Ensure we're in docker group
if ! groups | grep -q docker; then
    exec sg docker "$0 $@"
fi
echo "🔍 Diagnosing experiment ID issue..."
echo ""

echo "1. Current experiments in database:"
docker exec mlflow-postgres psql -U mlflow -d mlflow_db -c "SELECT experiment_id, name, lifecycle_stage, creation_time FROM experiments ORDER BY creation_time;"

echo ""
echo "2. Checking data type of experiment_id:"
docker exec mlflow-postgres psql -U mlflow -d mlflow_db -c "\d experiments" | grep experiment_id

echo ""
echo "3. Checking for problematic IDs (outside integer range):"
docker exec mlflow-postgres psql -U mlflow -d mlflow_db -c "SELECT experiment_id, name FROM experiments WHERE CAST(experiment_id AS BIGINT) > 2147483647;"

echo ""
echo "4. Checking runs table for problematic references:"
docker exec mlflow-postgres psql -U mlflow -d mlflow_db -c "SELECT COUNT(*) as total_runs FROM runs;"

echo ""
echo "🔧 Solution Options:"
echo "  A) Delete all experiments and recreate with proper IDs"
echo "  B) Migrate data to new experiments with correct IDs"
echo "  C) Alter database schema to use BIGINT"
echo ""
