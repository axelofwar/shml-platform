#!/bin/bash
# cleanup_interrupted_uploads.sh - Clean up interrupted/corrupted uploads in dataset-registry
# Created: 2025-11-20
#
# This script identifies and removes partial/corrupted uploads while preserving complete files.

set -euo pipefail

ARTIFACTS_DIR="/opt/mlflow/artifacts/11"  # experiment_id=11 (dataset-registry)
LOG_FILE="/tmp/cleanup_uploads_$(date +%Y%m%d_%H%M%S).log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

warn() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} WARNING: $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} ERROR: $1" | tee -a "$LOG_FILE"
}

# Check if running as root or with sudo
if [[ $EUID -ne 0 ]]; then
   error "This script must be run with sudo"
   exit 1
fi

log "=== Dataset-Registry Upload Cleanup ==="
log "Log file: $LOG_FILE"
echo ""

# Analysis phase
log "PHASE 1: Analyzing uploads..."
echo ""

# Files to delete (partial/corrupted)
PARTIAL_FILES=(
    "58006df99c8145fc940589d65b16ed5c/artifacts/datasets/ccpd.tar.zst.part000"
    "bcf1cae1034641799dd1f53c144c75d5/artifacts/datasets/ccpd.tar.zst.part000"
)

# Files that appear complete but are actually incomplete uploads
INCOMPLETE_UPLOADS=(
    "4c31c82266f54183b07002d93d48aa6c/artifacts/dataset/pii_combined_upload.tar.zst"
    "d62c5fb96a5041afbd05153bb26923d1/artifacts/dataset/pii_v2_occluded_upload.tar.zst"
)

# All runs with incomplete/corrupted uploads - DELETE from database and filesystem
DELETE_RUNS=(
    "58006df99c8145fc940589d65b16ed5c:ccpd-v1.0"
    "bcf1cae1034641799dd1f53c144c75d5:ccpd-v1.0"
    "4c31c82266f54183b07002d93d48aa6c:upload_pii_combined"
    "d62c5fb96a5041afbd05153bb26923d1:upload_pii_v2_occluded"
)

log "Found PARTIAL multipart uploads to DELETE:"
total_size=0
for file in "${PARTIAL_FILES[@]}"; do
    full_path="$ARTIFACTS_DIR/$file"
    if [[ -f "$full_path" ]]; then
        size=$(stat -c %s "$full_path")
        size_mb=$((size / 1024 / 1024))
        total_size=$((total_size + size))
        log "  - $file (${size_mb} MB) - .part000 suffix indicates incomplete"
        log "    Last modified: $(stat -c %y "$full_path")"
    else
        warn "  - $file (NOT FOUND)"
    fi
done
echo ""

log "Found INCOMPLETE streaming uploads to DELETE (appear valid but truncated):"
for file in "${INCOMPLETE_UPLOADS[@]}"; do
    full_path="$ARTIFACTS_DIR/$file"
    if [[ -f "$full_path" ]]; then
        size=$(stat -c %s "$full_path")
        size_mb=$((size / 1024 / 1024))
        total_size=$((total_size + size))
        log "  - $file (${size_mb} MB) - upload interrupted mid-stream"
        log "    File type: $(file -b "$full_path")"
        log "    Last modified: $(stat -c %y "$full_path")"
    else
        warn "  - $file (NOT FOUND)"
    fi
done
echo ""

total_size_gb=$(echo "scale=2; $total_size / 1024 / 1024 / 1024" | bc)
log "Total space to be freed: ${total_size_gb} GB"
echo ""

log "Runs to DELETE (incomplete uploads):"
for run_info in "${DELETE_RUNS[@]}"; do
    IFS=':' read -r run_uuid run_name <<< "$run_info"
    log "  - $run_name ($run_uuid)"
done
echo ""

all_files=$((${#PARTIAL_FILES[@]} + ${#INCOMPLETE_UPLOADS[@]}))

# Confirmation prompt
read -p "Proceed with cleanup? This will DELETE ${all_files} files (${total_size_gb} GB) and ${#DELETE_RUNS[@]} runs. [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log "Cleanup cancelled by user"
    exit 0
fi

# Cleanup phase
log "PHASE 2: Removing incomplete/corrupted files..."
echo ""

# Delete .part000 files
for file in "${PARTIAL_FILES[@]}"; do
    full_path="$ARTIFACTS_DIR/$file"
    if [[ -f "$full_path" ]]; then
        log "Deleting partial multipart upload: $full_path"
        rm -f "$full_path"
        if [[ ! -f "$full_path" ]]; then
            log "  ✓ Successfully deleted"
        else
            error "  ✗ Failed to delete"
        fi
    else
        warn "File not found, skipping: $full_path"
    fi
done

# Delete incomplete streaming uploads
for file in "${INCOMPLETE_UPLOADS[@]}"; do
    full_path="$ARTIFACTS_DIR/$file"
    if [[ -f "$full_path" ]]; then
        log "Deleting incomplete streaming upload: $full_path"
        rm -f "$full_path"
        if [[ ! -f "$full_path" ]]; then
            log "  ✓ Successfully deleted"
        else
            error "  ✗ Failed to delete"
        fi
    else
        warn "File not found, skipping: $full_path"
    fi
done
echo ""

# Database cleanup phase
log "PHASE 3: Cleaning up database..."
echo ""

DB_PASS=$(cat /opt/mlflow/.mlflow_db_pass)

# Delete all runs with incomplete uploads
log "Deleting incomplete upload runs from database:"
for run_info in "${DELETE_RUNS[@]}"; do
    IFS=':' read -r run_uuid run_name <<< "$run_info"
    log "Deleting run: $run_name ($run_uuid)"

    # Delete from all related tables (params, metrics, tags, and runs)
    PGPASSWORD="$DB_PASS" psql -h localhost -U mlflow -d mlflow_db >> "$LOG_FILE" 2>&1 << EOF
DELETE FROM params WHERE run_uuid = '$run_uuid';
DELETE FROM metrics WHERE run_uuid = '$run_uuid';
DELETE FROM tags WHERE run_uuid = '$run_uuid';
DELETE FROM latest_metrics WHERE run_uuid = '$run_uuid';
DELETE FROM runs WHERE run_uuid = '$run_uuid';
EOF

    if [[ $? -eq 0 ]]; then
        log "  ✓ Successfully deleted from database"

        # Also delete the run directory
        run_dir="$ARTIFACTS_DIR/$run_uuid"
        if [[ -d "$run_dir" ]]; then
            log "  Deleting run directory: $run_dir"
            rm -rf "$run_dir"
            if [[ ! -d "$run_dir" ]]; then
                log "  ✓ Successfully deleted run directory"
            else
                error "  ✗ Failed to delete run directory"
            fi
        fi
    else
        error "  ✗ Failed to delete from database"
    fi
done
echo ""

# Cleanup empty directories
log "PHASE 4: Cleaning up empty directories..."
echo ""

# Clean up any remaining empty directories
find "$ARTIFACTS_DIR" -type d -empty -delete 2>/dev/null || true
log "Removed any empty directories"
echo ""

# Final summary
log "=== CLEANUP COMPLETE ==="
log "Deleted files: $all_files"
log "Deleted runs: ${#DELETE_RUNS[@]}"
log "Space freed: ${total_size_gb} GB"
log "Full log: $LOG_FILE"
echo ""

log "To verify database updates, run:"
log "  PGPASSWORD=\$(sudo cat /opt/mlflow/.mlflow_db_pass) psql -h localhost -U mlflow -d mlflow_db -c \"SELECT run_uuid, name, status FROM runs WHERE experiment_id = 11 ORDER BY start_time DESC LIMIT 10;\""

exit 0
