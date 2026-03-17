#!/bin/bash
#
# MLflow Automated Backup Service
# Runs as Docker container with scheduled backups
#

set -e

BACKUP_DIR="/backups"
POSTGRES_BACKUP_DIR="$BACKUP_DIR/postgres"
ARTIFACTS_BACKUP_DIR="$BACKUP_DIR/artifacts"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-90}"
RETENTION_PRODUCTION="${BACKUP_RETENTION_PRODUCTION:-0}"  # 0 = keep forever

# Logging
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

# Create backup directories
mkdir -p "$POSTGRES_BACKUP_DIR" "$ARTIFACTS_BACKUP_DIR"

# Backup PostgreSQL
backup_postgres() {
    log "Starting PostgreSQL backup..."

    DATE=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$POSTGRES_BACKUP_DIR/mlflow_db_$DATE"

    # Get password from secret
    export PGPASSWORD=$(cat /run/secrets/db_password)

    # Custom format backup (for pg_restore)
    pg_dump -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -F c -f "$BACKUP_FILE.dump"

    # SQL format backup (human readable)
    pg_dump -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -F p -f "$BACKUP_FILE.sql"

    # Compress SQL backup
    gzip "$BACKUP_FILE.sql"

    # Calculate sizes
    DUMP_SIZE=$(du -h "$BACKUP_FILE.dump" | cut -f1)
    SQL_SIZE=$(du -h "$BACKUP_FILE.sql.gz" | cut -f1)

    log "✓ PostgreSQL backup complete: $DUMP_SIZE (custom), $SQL_SIZE (SQL)"

    # Cleanup old backups (skip production if retention = 0)
    if [ "$RETENTION_PRODUCTION" -eq 0 ]; then
        log "⚠️  Production retention set to FOREVER - skipping production backup cleanup"
        # Only clean dev/staging backups (exclude 'production' in filename)
        find "$POSTGRES_BACKUP_DIR" -name "*.dump" ! -name "*production*" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
        find "$POSTGRES_BACKUP_DIR" -name "*.sql.gz" ! -name "*production*" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
    else
        find "$POSTGRES_BACKUP_DIR" -name "*.dump" -mtime +$RETENTION_DAYS -delete
        find "$POSTGRES_BACKUP_DIR" -name "*.sql.gz" -mtime +$RETENTION_DAYS -delete
    fi

    log "✓ Cleaned up dev/staging backups older than $RETENTION_DAYS days"
}

# Backup artifacts directory (incremental)
backup_artifacts() {
    log "Starting artifacts backup (incremental)..."

    DATE=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$ARTIFACTS_BACKUP_DIR/artifacts_$DATE.tar.gz"

    # Create incremental backup using tar
    tar -czf "$BACKUP_FILE" -C /mlflow/artifacts .

    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    log "✓ Artifacts backup complete: $BACKUP_SIZE"

    # Cleanup old backups
    find "$ARTIFACTS_BACKUP_DIR" -name "*.tar.gz" -mtime +$RETENTION_DAYS -delete

    log "✓ Cleaned up artifact backups older than $RETENTION_DAYS days"
}

# Create backup manifest
create_manifest() {
    log "Creating backup manifest..."

    DATE=$(date +%Y%m%d_%H%M%S)
    MANIFEST_FILE="$BACKUP_DIR/manifest_$DATE.json"

    cat > "$MANIFEST_FILE" <<EOF
{
  "backup_date": "$(date -Iseconds)",
  "postgres_backups": [
$(find "$POSTGRES_BACKUP_DIR" -name "*.dump" -mtime -1 | while read f; do
    echo "    {\"file\": \"$(basename $f)\", \"size\": \"$(du -h $f | cut -f1)\", \"date\": \"$(stat -c %y $f)\"}"
done | paste -sd ',' -)
  ],
  "artifact_backups": [
$(find "$ARTIFACTS_BACKUP_DIR" -name "*.tar.gz" -mtime -1 | while read f; do
    echo "    {\"file\": \"$(basename $f)\", \"size\": \"$(du -h $f | cut -f1)\", \"date\": \"$(stat -c %y $f)\"}"
done | paste -sd ',' -)
  ],
  "retention_days": $RETENTION_DAYS,
  "total_backup_size": "$(du -sh $BACKUP_DIR | cut -f1)"
}
EOF

    log "✓ Manifest created: $MANIFEST_FILE"
}

# Main backup function
run_backup() {
    log "========================================="
    log "Starting MLflow backup service"
    log "========================================="

    backup_postgres
    backup_artifacts
    create_manifest

    log "========================================="
    log "Backup completed successfully"
    log "========================================="
}

# Run backup on startup
run_backup

# Schedule backups using cron
log "Setting up cron schedule: $BACKUP_SCHEDULE"
echo "$BACKUP_SCHEDULE cd / && ./backup.sh >> /var/log/backup.log 2>&1" | crontab -

# Start cron
log "Starting cron daemon..."
crond -f -l 2
