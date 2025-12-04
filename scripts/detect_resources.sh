#!/bin/bash
# Resource Auto-Detection Script for ML Platform
# Detects host resources and generates recommended container constraints
# Outputs environment variables that can be sourced or appended to .env
#
# Usage:
#   ./detect_resources.sh                    # Print recommendations
#   ./detect_resources.sh --apply            # Append to .env.local
#   ./detect_resources.sh --export           # Export as shell variables
#   source <(./detect_resources.sh --export) # Source directly

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_LOCAL="${PROJECT_ROOT}/.env.local"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# =============================================================================
# RESOURCE DETECTION
# =============================================================================

# Get total CPU cores
TOTAL_CPUS=$(nproc)

# Get total memory in MB
TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
TOTAL_MEM_MB=$((TOTAL_MEM_KB / 1024))
TOTAL_MEM_GB=$((TOTAL_MEM_MB / 1024))

# Get available memory (not used by system)
AVAIL_MEM_KB=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
AVAIL_MEM_MB=$((AVAIL_MEM_KB / 1024))

# Detect GPU count
GPU_COUNT=0
if command -v nvidia-smi &> /dev/null; then
    GPU_COUNT=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l || echo 0)
fi

# =============================================================================
# RESOURCE ALLOCATION STRATEGY
# =============================================================================
#
# We allocate resources in tiers:
# - Critical (ML workloads): 60% of available resources
# - Standard (databases, auth): 25% of available resources
# - Lightweight (monitoring, logs): 10% of available resources
# - Reserve: 5% for system overhead
#
# Within each tier, resources are distributed to services proportionally.
# =============================================================================

# Calculate allocatable resources (leave 10% for host OS)
ALLOCATABLE_CPUS=$(echo "$TOTAL_CPUS * 0.90" | bc)
ALLOCATABLE_MEM_MB=$(echo "$TOTAL_MEM_MB * 0.85" | bc | cut -d. -f1)

# Tier allocations (as decimals)
CRITICAL_CPU_SHARE=0.60
CRITICAL_MEM_SHARE=0.60
STANDARD_CPU_SHARE=0.25
STANDARD_MEM_SHARE=0.25
LIGHT_CPU_SHARE=0.10
LIGHT_MEM_SHARE=0.10

# Calculate tier budgets
CRITICAL_CPU=$(echo "$ALLOCATABLE_CPUS * $CRITICAL_CPU_SHARE" | bc)
CRITICAL_MEM=$(echo "$ALLOCATABLE_MEM_MB * $CRITICAL_MEM_SHARE" | bc | cut -d. -f1)
STANDARD_CPU=$(echo "$ALLOCATABLE_CPUS * $STANDARD_CPU_SHARE" | bc)
STANDARD_MEM=$(echo "$ALLOCATABLE_MEM_MB * $STANDARD_MEM_SHARE" | bc | cut -d. -f1)
LIGHT_CPU=$(echo "$ALLOCATABLE_CPUS * $LIGHT_CPU_SHARE" | bc)
LIGHT_MEM=$(echo "$ALLOCATABLE_MEM_MB * $LIGHT_MEM_SHARE" | bc | cut -d. -f1)

# =============================================================================
# SERVICE ALLOCATIONS
# =============================================================================

# Critical tier services (ML workloads)
# Ray Head: 30% of critical
RAY_HEAD_CPU=$(echo "$CRITICAL_CPU * 0.30" | bc)
RAY_HEAD_MEM=$(echo "$CRITICAL_MEM * 0.30" | bc | cut -d. -f1)

# MLflow: 20% of critical
MLFLOW_CPU=$(echo "$CRITICAL_CPU * 0.20" | bc)
MLFLOW_MEM=$(echo "$CRITICAL_MEM * 0.20" | bc | cut -d. -f1)

# Standard tier services
# PostgreSQL: 40% of standard
POSTGRES_CPU=$(echo "$STANDARD_CPU * 0.40" | bc)
POSTGRES_MEM=$(echo "$STANDARD_MEM * 0.40" | bc | cut -d. -f1)

# Redis: 20% of standard
REDIS_CPU=$(echo "$STANDARD_CPU * 0.20" | bc)
REDIS_MEM=$(echo "$STANDARD_MEM * 0.20" | bc | cut -d. -f1)

# FusionAuth: 25% of standard
FUSIONAUTH_CPU=$(echo "$STANDARD_CPU * 0.25" | bc)
FUSIONAUTH_MEM=$(echo "$STANDARD_MEM * 0.25" | bc | cut -d. -f1)

# Lightweight tier services (observability)
# Grafana: 25% of light
GRAFANA_CPU=$(echo "$LIGHT_CPU * 0.25" | bc)
GRAFANA_MEM=$(echo "$LIGHT_MEM * 0.25" | bc | cut -d. -f1)

# Prometheus: 25% of light
PROMETHEUS_CPU=$(echo "$LIGHT_CPU * 0.25" | bc)
PROMETHEUS_MEM=$(echo "$LIGHT_MEM * 0.25" | bc | cut -d. -f1)

# Dozzle: 10% of light
DOZZLE_CPU=$(echo "$LIGHT_CPU * 0.10" | bc)
DOZZLE_MEM=$(echo "$LIGHT_MEM * 0.10" | bc | cut -d. -f1)

# Homer: 10% of light
HOMER_CPU=$(echo "$LIGHT_CPU * 0.10" | bc)
HOMER_MEM=$(echo "$LIGHT_MEM * 0.10" | bc | cut -d. -f1)

# Backup: 10% of light (only active during backups)
BACKUP_CPU=$(echo "$LIGHT_CPU * 0.10" | bc)
BACKUP_MEM=$(echo "$LIGHT_MEM * 0.10" | bc | cut -d. -f1)

# Webhook: 5% of light
WEBHOOK_CPU=$(echo "$LIGHT_CPU * 0.05" | bc)
WEBHOOK_MEM=$(echo "$LIGHT_MEM * 0.05" | bc | cut -d. -f1)

# =============================================================================
# MINIMUM CONSTRAINTS
# =============================================================================
# Ensure services have minimum viable resources

min_cpu() {
    local val=$1
    local min=$2
    echo "scale=2; if ($val < $min) $min else $val" | bc
}

min_mem() {
    local val=$1
    local min=$2
    if [ "$val" -lt "$min" ]; then echo "$min"; else echo "$val"; fi
}

# Apply minimums
RAY_HEAD_CPU=$(min_cpu "$RAY_HEAD_CPU" 1.0)
RAY_HEAD_MEM=$(min_mem "$RAY_HEAD_MEM" 1024)
MLFLOW_CPU=$(min_cpu "$MLFLOW_CPU" 0.5)
MLFLOW_MEM=$(min_mem "$MLFLOW_MEM" 512)
POSTGRES_CPU=$(min_cpu "$POSTGRES_CPU" 0.5)
POSTGRES_MEM=$(min_mem "$POSTGRES_MEM" 384)
REDIS_CPU=$(min_cpu "$REDIS_CPU" 0.1)
REDIS_MEM=$(min_mem "$REDIS_MEM" 128)
FUSIONAUTH_CPU=$(min_cpu "$FUSIONAUTH_CPU" 0.25)
FUSIONAUTH_MEM=$(min_mem "$FUSIONAUTH_MEM" 256)
GRAFANA_CPU=$(min_cpu "$GRAFANA_CPU" 0.2)
GRAFANA_MEM=$(min_mem "$GRAFANA_MEM" 256)
PROMETHEUS_CPU=$(min_cpu "$PROMETHEUS_CPU" 0.2)
PROMETHEUS_MEM=$(min_mem "$PROMETHEUS_MEM" 256)
DOZZLE_CPU=$(min_cpu "$DOZZLE_CPU" 0.1)
DOZZLE_MEM=$(min_mem "$DOZZLE_MEM" 64)
HOMER_CPU=$(min_cpu "$HOMER_CPU" 0.1)
HOMER_MEM=$(min_mem "$HOMER_MEM" 64)
BACKUP_CPU=$(min_cpu "$BACKUP_CPU" 0.1)
BACKUP_MEM=$(min_mem "$BACKUP_MEM" 64)
WEBHOOK_CPU=$(min_cpu "$WEBHOOK_CPU" 0.05)
WEBHOOK_MEM=$(min_mem "$WEBHOOK_MEM" 64)

# =============================================================================
# OUTPUT
# =============================================================================

generate_env() {
    cat << EOF
# =============================================================================
# AUTO-DETECTED RESOURCE CONSTRAINTS
# Generated: $(date -Iseconds)
# Host: $(hostname)
# Total CPUs: ${TOTAL_CPUS}, Total RAM: ${TOTAL_MEM_GB}GB, GPUs: ${GPU_COUNT}
# =============================================================================

# Critical Tier (ML Workloads)
RAY_HEAD_CPU_LIMIT=${RAY_HEAD_CPU}
RAY_HEAD_MEM_LIMIT=${RAY_HEAD_MEM}M
MLFLOW_CPU_LIMIT=${MLFLOW_CPU}
MLFLOW_MEM_LIMIT=${MLFLOW_MEM}M

# Standard Tier (Infrastructure)
POSTGRES_CPU_LIMIT=${POSTGRES_CPU}
POSTGRES_MEM_LIMIT=${POSTGRES_MEM}M
REDIS_CPU_LIMIT=${REDIS_CPU}
REDIS_MEM_LIMIT=${REDIS_MEM}M
FUSIONAUTH_CPU_LIMIT=${FUSIONAUTH_CPU}
FUSIONAUTH_MEM_LIMIT=${FUSIONAUTH_MEM}M

# Lightweight Tier (Observability)
GRAFANA_CPU_LIMIT=${GRAFANA_CPU}
GRAFANA_MEM_LIMIT=${GRAFANA_MEM}M
PROMETHEUS_CPU_LIMIT=${PROMETHEUS_CPU}
PROMETHEUS_MEM_LIMIT=${PROMETHEUS_MEM}M
DOZZLE_CPU_LIMIT=${DOZZLE_CPU}
DOZZLE_MEM_LIMIT=${DOZZLE_MEM}M
HOMER_CPU_LIMIT=${HOMER_CPU}
HOMER_MEM_LIMIT=${HOMER_MEM}M
BACKUP_CPU_LIMIT=${BACKUP_CPU}
BACKUP_MEM_LIMIT=${BACKUP_MEM}M
WEBHOOK_CPU_LIMIT=${WEBHOOK_CPU}
WEBHOOK_MEM_LIMIT=${WEBHOOK_MEM}M
EOF
}

print_summary() {
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║     SFML Platform Resource Auto-Detection                  ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${CYAN}Host Resources:${NC}"
    echo -e "  CPUs:   ${GREEN}${TOTAL_CPUS}${NC} cores"
    echo -e "  RAM:    ${GREEN}${TOTAL_MEM_GB}${NC} GB (${AVAIL_MEM_MB} MB available)"
    echo -e "  GPUs:   ${GREEN}${GPU_COUNT}${NC}"
    echo ""
    echo -e "${CYAN}Allocatable (after 10-15% reserve):${NC}"
    echo -e "  CPUs:   ${YELLOW}${ALLOCATABLE_CPUS}${NC} cores"
    echo -e "  RAM:    ${YELLOW}${ALLOCATABLE_MEM_MB}${NC} MB"
    echo ""
    echo -e "${CYAN}Tier Budgets:${NC}"
    echo -e "  Critical (ML):     ${CRITICAL_CPU} CPUs, ${CRITICAL_MEM} MB"
    echo -e "  Standard (Infra):  ${STANDARD_CPU} CPUs, ${STANDARD_MEM} MB"
    echo -e "  Lightweight (Obs): ${LIGHT_CPU} CPUs, ${LIGHT_MEM} MB"
    echo ""
    echo -e "${CYAN}Service Allocations:${NC}"
    echo -e "  ${GREEN}Critical:${NC}"
    echo -e "    Ray Head:    ${RAY_HEAD_CPU} CPUs, ${RAY_HEAD_MEM}M RAM"
    echo -e "    MLflow:      ${MLFLOW_CPU} CPUs, ${MLFLOW_MEM}M RAM"
    echo -e "  ${YELLOW}Standard:${NC}"
    echo -e "    PostgreSQL:  ${POSTGRES_CPU} CPUs, ${POSTGRES_MEM}M RAM"
    echo -e "    Redis:       ${REDIS_CPU} CPUs, ${REDIS_MEM}M RAM"
    echo -e "    FusionAuth:  ${FUSIONAUTH_CPU} CPUs, ${FUSIONAUTH_MEM}M RAM"
    echo -e "  ${BLUE}Lightweight:${NC}"
    echo -e "    Grafana:     ${GRAFANA_CPU} CPUs, ${GRAFANA_MEM}M RAM"
    echo -e "    Prometheus:  ${PROMETHEUS_CPU} CPUs, ${PROMETHEUS_MEM}M RAM"
    echo -e "    Dozzle:      ${DOZZLE_CPU} CPUs, ${DOZZLE_MEM}M RAM"
    echo -e "    Homer:       ${HOMER_CPU} CPUs, ${HOMER_MEM}M RAM"
    echo ""
}

# Parse arguments
case "${1:-}" in
    --apply)
        print_summary
        echo -e "${YELLOW}Appending to ${ENV_LOCAL}...${NC}"
        generate_env >> "$ENV_LOCAL"
        echo -e "${GREEN}✓ Resource constraints written to ${ENV_LOCAL}${NC}"
        echo -e "${CYAN}To use: docker compose --env-file .env --env-file .env.local up${NC}"
        ;;
    --export)
        # Output export statements for sourcing
        generate_env | grep -v '^#' | grep '=' | sed 's/^/export /'
        ;;
    --env)
        # Output just the env file content
        generate_env
        ;;
    *)
        print_summary
        echo -e "${CYAN}Usage:${NC}"
        echo "  $0              # Show this summary"
        echo "  $0 --apply      # Append to .env.local"
        echo "  $0 --export     # Export as shell variables"
        echo "  $0 --env        # Output .env format"
        ;;
esac
