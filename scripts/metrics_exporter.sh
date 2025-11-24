#!/bin/bash
# Prometheus Metrics Exporter for ML Platform System Resources
# Exports system metrics in Prometheus text exposition format
# Can be scraped by Prometheus via node-exporter's textfile collector

set -e

# Configuration
METRICS_DIR="${METRICS_DIR:-/tmp/prometheus-metrics}"
METRICS_FILE="${METRICS_DIR}/ml_platform_resources.prom"
UPDATE_INTERVAL="${UPDATE_INTERVAL:-15}"

# Create metrics directory
mkdir -p "$METRICS_DIR"

# Function to get CPU usage
get_cpu_usage() {
    top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%* id.*/\1/" | awk '{print 100 - $1}'
}

# Function to get memory usage percentage
get_memory_usage() {
    free | grep Mem | awk '{print ($3/$2) * 100.0}'
}

# Function to get memory details
get_memory_details() {
    free -b | grep Mem | awk '{print $2, $3, $4, $5, $6, $7}'
}

# Function to get disk usage for root partition
get_disk_usage() {
    df -B1 / | awk 'NR==2 {print $2, $3, $4, $5}' | sed 's/%//'
}

# Function to get GPU metrics (if available)
get_gpu_metrics() {
    if command -v nvidia-smi &> /dev/null; then
        nvidia-smi --query-gpu=index,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw --format=csv,noheader,nounits
    else
        echo ""
    fi
}

# Function to get Docker container count
get_docker_stats() {
    if docker ps -q &> /dev/null; then
        local running=$(docker ps -q | wc -l)
        local total=$(docker ps -aq | wc -l)
        echo "$running $total"
    else
        echo "0 0"
    fi
}

# Function to write metrics
write_metrics() {
    local temp_file="${METRICS_FILE}.tmp"
    
    # Start with header
    cat > "$temp_file" <<EOF
# HELP ml_platform_cpu_usage_percent Current CPU usage percentage
# TYPE ml_platform_cpu_usage_percent gauge
ml_platform_cpu_usage_percent $(get_cpu_usage)

EOF

    # Memory metrics
    local mem_usage=$(get_memory_usage)
    read -r mem_total mem_used mem_free mem_shared mem_buff mem_available <<< $(get_memory_details)
    
    cat >> "$temp_file" <<EOF
# HELP ml_platform_memory_usage_percent Current memory usage percentage
# TYPE ml_platform_memory_usage_percent gauge
ml_platform_memory_usage_percent $mem_usage

# HELP ml_platform_memory_total_bytes Total system memory in bytes
# TYPE ml_platform_memory_total_bytes gauge
ml_platform_memory_total_bytes $mem_total

# HELP ml_platform_memory_used_bytes Used system memory in bytes
# TYPE ml_platform_memory_used_bytes gauge
ml_platform_memory_used_bytes $mem_used

# HELP ml_platform_memory_free_bytes Free system memory in bytes
# TYPE ml_platform_memory_free_bytes gauge
ml_platform_memory_free_bytes $mem_free

# HELP ml_platform_memory_available_bytes Available system memory in bytes
# TYPE ml_platform_memory_available_bytes gauge
ml_platform_memory_available_bytes $mem_available

EOF

    # Disk metrics
    read -r disk_total disk_used disk_free disk_percent <<< $(get_disk_usage)
    
    cat >> "$temp_file" <<EOF
# HELP ml_platform_disk_usage_percent Root disk usage percentage
# TYPE ml_platform_disk_usage_percent gauge
ml_platform_disk_usage_percent $disk_percent

# HELP ml_platform_disk_total_bytes Total root disk size in bytes
# TYPE ml_platform_disk_total_bytes gauge
ml_platform_disk_total_bytes $disk_total

# HELP ml_platform_disk_used_bytes Used root disk space in bytes
# TYPE ml_platform_disk_used_bytes gauge
ml_platform_disk_used_bytes $disk_used

# HELP ml_platform_disk_free_bytes Free root disk space in bytes
# TYPE ml_platform_disk_free_bytes gauge
ml_platform_disk_free_bytes $disk_free

EOF

    # Docker container stats
    read -r docker_running docker_total <<< $(get_docker_stats)
    
    cat >> "$temp_file" <<EOF
# HELP ml_platform_docker_containers_running Number of running Docker containers
# TYPE ml_platform_docker_containers_running gauge
ml_platform_docker_containers_running $docker_running

# HELP ml_platform_docker_containers_total Total number of Docker containers
# TYPE ml_platform_docker_containers_total gauge
ml_platform_docker_containers_total $docker_total

EOF

    # GPU metrics (if available)
    local gpu_data=$(get_gpu_metrics)
    if [ -n "$gpu_data" ]; then
        echo "$gpu_data" | while IFS=, read -r gpu_index gpu_util gpu_mem_used gpu_mem_total gpu_temp gpu_power; do
            cat >> "$temp_file" <<EOF
# HELP ml_platform_gpu_utilization_percent GPU utilization percentage
# TYPE ml_platform_gpu_utilization_percent gauge
ml_platform_gpu_utilization_percent{gpu="$gpu_index"} $gpu_util

# HELP ml_platform_gpu_memory_used_mb GPU memory used in MB
# TYPE ml_platform_gpu_memory_used_mb gauge
ml_platform_gpu_memory_used_mb{gpu="$gpu_index"} $gpu_mem_used

# HELP ml_platform_gpu_memory_total_mb GPU memory total in MB
# TYPE ml_platform_gpu_memory_total_mb gauge
ml_platform_gpu_memory_total_mb{gpu="$gpu_index"} $gpu_mem_total

# HELP ml_platform_gpu_temperature_celsius GPU temperature in Celsius
# TYPE ml_platform_gpu_temperature_celsius gauge
ml_platform_gpu_temperature_celsius{gpu="$gpu_index"} $gpu_temp

# HELP ml_platform_gpu_power_draw_watts GPU power draw in watts
# TYPE ml_platform_gpu_power_draw_watts gauge
ml_platform_gpu_power_draw_watts{gpu="$gpu_index"} $gpu_power

EOF
        done
    fi
    
    # Timestamp
    cat >> "$temp_file" <<EOF
# HELP ml_platform_metrics_last_update_timestamp_seconds Timestamp of last metrics update
# TYPE ml_platform_metrics_last_update_timestamp_seconds gauge
ml_platform_metrics_last_update_timestamp_seconds $(date +%s)
EOF
    
    # Atomic move
    mv "$temp_file" "$METRICS_FILE"
}

# Main execution
case "${1:-daemon}" in
    "once")
        write_metrics
        echo "Metrics written to $METRICS_FILE"
        ;;
    "daemon")
        echo "Starting metrics exporter daemon (interval: ${UPDATE_INTERVAL}s)"
        echo "Metrics file: $METRICS_FILE"
        echo "Press Ctrl+C to stop"
        
        while true; do
            write_metrics
            sleep "$UPDATE_INTERVAL"
        done
        ;;
    "cat")
        if [ -f "$METRICS_FILE" ]; then
            cat "$METRICS_FILE"
        else
            echo "No metrics file found at $METRICS_FILE"
            exit 1
        fi
        ;;
    *)
        cat <<EOF
Usage: $0 [COMMAND]

Commands:
    once     Write metrics once and exit
    daemon   Run continuously, updating metrics every ${UPDATE_INTERVAL}s (default)
    cat      Display current metrics file

Environment Variables:
    METRICS_DIR       Directory for metrics file (default: /tmp/prometheus-metrics)
    UPDATE_INTERVAL   Update interval in seconds (default: 15)

Example:
    # Run as daemon
    $0 daemon

    # Export once
    $0 once

    # View current metrics
    $0 cat
EOF
        exit 1
        ;;
esac
