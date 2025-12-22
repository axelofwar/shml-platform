#!/bin/bash
# Setup Daily Automated Backups
# Adds cron job for automatic daily backups at 2 AM

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_SCRIPT="${PROJECT_ROOT}/scripts/backup_platform.sh"
LOG_DIR="${PROJECT_ROOT}/logs/backups"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "Setup Daily Automated Backups"
echo "=========================================="
echo ""

# Create log directory
mkdir -p "${LOG_DIR}"

# Cron job command
CRON_CMD="${BACKUP_SCRIPT} >> ${LOG_DIR}/backup_\$(date +\%Y\%m\%d).log 2>&1"
CRON_SCHEDULE="0 2 * * *"  # Daily at 2 AM
CRON_ENTRY="${CRON_SCHEDULE} ${CRON_CMD}"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "${BACKUP_SCRIPT}"; then
    echo -e "${YELLOW}⚠ Backup cron job already exists${NC}"
    echo ""
    echo "Current cron jobs:"
    crontab -l | grep "${BACKUP_SCRIPT}"
    echo ""
    read -p "Replace existing cron job? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled"
        exit 0
    fi
    # Remove existing entry
    crontab -l | grep -v "${BACKUP_SCRIPT}" | crontab -
fi

# Add cron job
(crontab -l 2>/dev/null; echo "${CRON_ENTRY}") | crontab -

echo -e "${GREEN}✓ Daily backup cron job installed${NC}"
echo ""
echo "Details:"
echo "  Schedule: Daily at 2:00 AM"
echo "  Command:  ${BACKUP_SCRIPT}"
echo "  Logs:     ${LOG_DIR}/backup_YYYYMMDD.log"
echo ""
echo "To view cron jobs:"
echo "  crontab -l"
echo ""
echo "To remove cron job:"
echo "  crontab -l | grep -v '${BACKUP_SCRIPT}' | crontab -"
echo ""
