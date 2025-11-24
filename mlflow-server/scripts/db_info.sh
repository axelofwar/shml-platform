#!/bin/bash
# Quick database inspection script

# Get password from secure file or use default
if [ -f /opt/mlflow/.mlflow_db_pass ]; then
    MLFLOW_DB_PASS=$(sudo cat /opt/mlflow/.mlflow_db_pass 2>/dev/null)
fi
if [ -z "$MLFLOW_DB_PASS" ]; then
    MLFLOW_DB_PASS="YOUR_PASSWORD_HERE"
fi

echo "======================================================================"
echo "MLflow PostgreSQL Database Overview"
echo "======================================================================"
echo ""

# Connection test
echo "Testing connection..."
if PGPASSWORD="$MLFLOW_DB_PASS" psql -h localhost -U mlflow -d mlflow_db -c "SELECT 1;" > /dev/null 2>&1; then
    echo "✓ Database connection successful"
else
    echo "✗ Database connection failed"
    exit 1
fi
echo ""

# Record counts
echo "Record Counts:"
echo "----------------------------------------------------------------------"
PGPASSWORD="$MLFLOW_DB_PASS" psql -h localhost -U mlflow -d mlflow_db -t -c "
SELECT 
    'Experiments:      ' || LPAD(COUNT(*)::text, 6) FROM experiments
UNION ALL
SELECT 'Runs:             ' || LPAD(COUNT(*)::text, 6) FROM runs
UNION ALL
SELECT 'Metrics:          ' || LPAD(COUNT(*)::text, 6) FROM metrics
UNION ALL
SELECT 'Parameters:       ' || LPAD(COUNT(*)::text, 6) FROM params
UNION ALL
SELECT 'Tags:             ' || LPAD(COUNT(*)::text, 6) FROM tags
UNION ALL
SELECT 'Registered Models:' || LPAD(COUNT(*)::text, 6) FROM registered_models
UNION ALL
SELECT 'Model Versions:   ' || LPAD(COUNT(*)::text, 6) FROM model_versions;
"
echo ""

# Recent experiments
echo "Recent Experiments:"
echo "----------------------------------------------------------------------"
PGPASSWORD="$MLFLOW_DB_PASS" psql -h localhost -U mlflow -d mlflow_db -c "
SELECT 
    experiment_id as id,
    name,
    lifecycle_stage as status,
    TO_CHAR(TO_TIMESTAMP(creation_time/1000), 'YYYY-MM-DD HH24:MI') as created
FROM experiments 
ORDER BY creation_time DESC 
LIMIT 5;
"
echo ""

# Recent runs
echo "Recent Runs:"
echo "----------------------------------------------------------------------"
PGPASSWORD="$MLFLOW_DB_PASS" psql -h localhost -U mlflow -d mlflow_db -c "
SELECT 
    SUBSTRING(run_uuid, 1, 8) as run_id,
    experiment_id as exp,
    status,
    start_time as started
FROM runs 
ORDER BY start_time DESC 
LIMIT 5;
"
echo ""

# Model registry
echo "Registered Models:"
echo "----------------------------------------------------------------------"
PGPASSWORD="$MLFLOW_DB_PASS" psql -h localhost -U mlflow -d mlflow_db -c "
SELECT 
    rm.name,
    COUNT(mv.version) as versions
FROM registered_models rm
LEFT JOIN model_versions mv ON rm.name = mv.name
GROUP BY rm.name
ORDER BY rm.creation_time DESC;
"
echo ""

# Database size
echo "Database Size:"
echo "----------------------------------------------------------------------"
PGPASSWORD="$MLFLOW_DB_PASS" psql -h localhost -U mlflow -d mlflow_db -c "
SELECT 
    pg_size_pretty(pg_database_size('mlflow_db')) as database_size;
"
echo ""

# Backup info
echo "Latest Backup:"
echo "----------------------------------------------------------------------"
if [ -d /opt/mlflow/backups ]; then
    LATEST=$(ls -t /opt/mlflow/backups/backup_*.tar.gz 2>/dev/null | head -1)
    if [ -n "$LATEST" ]; then
        echo "File: $(basename $LATEST)"
        echo "Size: $(du -h $LATEST | cut -f1)"
        echo "Date: $(stat -c %y $LATEST | cut -d'.' -f1)"
    else
        echo "No backups found"
    fi
else
    echo "Backup directory not found"
fi
echo ""

echo "======================================================================"
echo "Access Methods:"
echo "======================================================================"
echo "Web UI:  http://<SERVER_IP>:8081/adminer.php"
echo "         Login: mlflow / (see /opt/mlflow/.mlflow_db_pass)"
echo ""
echo "CLI:     pgcli -h localhost -U mlflow mlflow_db"
echo "         (password from /opt/mlflow/.mlflow_db_pass)"
echo "======================================================================"
