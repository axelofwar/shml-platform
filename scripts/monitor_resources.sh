#!/bin/bash
# Resource Monitoring Script for ML Platform
# Monitors CPU, Memory, and Disk usage with configurable thresholds

set -e

# Color codes for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Thresholds (percentages)
CPU_WARN=75
CPU_CRITICAL=90
MEM_WARN=80
MEM_CRITICAL=95
DISK_WARN=85
DISK_CRITICAL=95

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_FILE="${PROJECT_ROOT}/logs/resource_monitor.log"

# Create logs directory if it doesn't exist
mkdir -p "${PROJECT_ROOT}/logs"

# Function to get current timestamp
timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

# Function to log messages
log_message() {
    local level=$1
    shift
    echo "[$(timestamp)] [$level] $*" | tee -a "$LOG_FILE"
}

# Function to get CPU usage
get_cpu_usage() {
    top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%* id.*/\1/" | awk '{print 100 - $1}'
}

# Function to get memory usage percentage
get_memory_usage() {
    free | grep Mem | awk '{print ($3/$2) * 100.0}'
}

# Function to get disk usage for root partition
get_disk_usage() {
    df -h / | awk 'NR==2 {print $5}' | sed 's/%//'
}

# Function to check Docker containers status
check_docker_containers() {
    echo -e "${BLUE}=== Docker Containers Status ===${NC}"
    if docker ps -q > /dev/null 2>&1 && [ $(docker ps -q | wc -l) -gt 0 ]; then
        docker ps --format "table {{.Names}}\t{{.Status}}" 2>/dev/null
        echo ""
        echo -e "${BLUE}=== Container Resource Stats ===${NC}"
        docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>/dev/null | head -10
    else
        echo "Docker not running or no containers"
    fi
}

# Function to display system metrics
display_metrics() {
    local cpu_usage=$(get_cpu_usage)
    local mem_usage=$(get_memory_usage)
    local disk_usage=$(get_disk_usage)
    
    echo ""
    echo -e "${BLUE}=== System Resource Usage ===${NC}"
    echo "Timestamp: $(timestamp)"
    echo ""
    
    # CPU Status
    printf "CPU Usage: %.1f%% " "$cpu_usage"
    if (( $(echo "$cpu_usage >= $CPU_CRITICAL" | bc -l) )); then
        echo -e "${RED}[CRITICAL]${NC}"
        log_message "CRITICAL" "CPU usage at ${cpu_usage}%"
    elif (( $(echo "$cpu_usage >= $CPU_WARN" | bc -l) )); then
        echo -e "${YELLOW}[WARNING]${NC}"
        log_message "WARNING" "CPU usage at ${cpu_usage}%"
    else
        echo -e "${GREEN}[OK]${NC}"
    fi
    
    # Memory Status
    printf "Memory Usage: %.1f%% " "$mem_usage"
    if (( $(echo "$mem_usage >= $MEM_CRITICAL" | bc -l) )); then
        echo -e "${RED}[CRITICAL]${NC}"
        log_message "CRITICAL" "Memory usage at ${mem_usage}%"
    elif (( $(echo "$mem_usage >= $MEM_WARN" | bc -l) )); then
        echo -e "${YELLOW}[WARNING]${NC}"
        log_message "WARNING" "Memory usage at ${mem_usage}%"
    else
        echo -e "${GREEN}[OK]${NC}"
    fi
    
    # Disk Status
    printf "Disk Usage: %s%% " "$disk_usage"
    if [ "$disk_usage" -ge "$DISK_CRITICAL" ]; then
        echo -e "${RED}[CRITICAL]${NC}"
        log_message "CRITICAL" "Disk usage at ${disk_usage}%"
    elif [ "$disk_usage" -ge "$DISK_WARN" ]; then
        echo -e "${YELLOW}[WARNING]${NC}"
        log_message "WARNING" "Disk usage at ${disk_usage}%"
    else
        echo -e "${GREEN}[OK]${NC}"
    fi
    
    echo ""
    
    # Detailed memory info
    echo -e "${BLUE}=== Detailed Memory Info ===${NC}"
    free -h
    echo ""
    
    # Docker container stats if running
    if docker ps -q > /dev/null 2>&1; then
        check_docker_containers
    fi
}

# Function for continuous monitoring
watch_mode() {
    local interval=${1:-5}
    echo "Starting continuous monitoring (interval: ${interval}s)"
    echo "Press Ctrl+C to stop"
    echo ""
    
    while true; do
        clear
        display_metrics
        echo ""
        echo "Refreshing in ${interval}s..."
        sleep "$interval"
    done
}

# Function to check if system is under critical load
check_critical_state() {
    local cpu_usage=$(get_cpu_usage)
    local mem_usage=$(get_memory_usage)
    local disk_usage=$(get_disk_usage)
    
    local critical=0
    
    if (( $(echo "$cpu_usage >= $CPU_CRITICAL" | bc -l) )); then
        log_message "ALERT" "System under critical CPU load: ${cpu_usage}%"
        critical=1
    fi
    
    if (( $(echo "$mem_usage >= $MEM_CRITICAL" | bc -l) )); then
        log_message "ALERT" "System under critical memory load: ${mem_usage}%"
        critical=1
    fi
    
    if [ "$disk_usage" -ge "$DISK_CRITICAL" ]; then
        log_message "ALERT" "System disk critically full: ${disk_usage}%"
        critical=1
    fi
    
    return $critical
}

# Function to display usage
usage() {
    cat <<EOF
Usage: $0 [COMMAND] [OPTIONS]

Commands:
    check       Display current resource usage (default)
    watch       Continuous monitoring mode
    critical    Check if system is in critical state (exit 1 if critical)
    docker      Show Docker container resource usage
    help        Display this help message

Options:
    -i, --interval SECONDS    Set refresh interval for watch mode (default: 5)
    -v, --verbose            Enable verbose output

Examples:
    $0                       # Show current status
    $0 watch                 # Start continuous monitoring
    $0 watch -i 10           # Monitor with 10s interval
    $0 critical              # Check for critical state (for scripts)
    $0 docker                # Show only Docker stats

EOF
}

# Main script logic
COMMAND="${1:-check}"
INTERVAL=5
VERBOSE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        check|watch|critical|docker|help)
            COMMAND=$1
            shift
            ;;
        -i|--interval)
            INTERVAL=$2
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Execute command
case $COMMAND in
    check)
        display_metrics
        ;;
    watch)
        watch_mode "$INTERVAL"
        ;;
    critical)
        if check_critical_state; then
            echo "System is in critical state!"
            exit 1
        else
            echo "System resources within acceptable limits"
            exit 0
        fi
        ;;
    docker)
        check_docker_containers
        ;;
    help)
        usage
        ;;
    *)
        echo "Unknown command: $COMMAND"
        usage
        exit 1
        ;;
esac
