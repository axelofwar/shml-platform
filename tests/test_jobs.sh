#!/bin/bash
# Ray Job Submission Test Script
# Tests local and remote job submission with various configurations

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
RAY_ADDRESS="${RAY_ADDRESS:-ray-head:8265}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLES_DIR="${SCRIPT_DIR}/examples"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Ray Job Submission Tests${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Check if we're inside or outside containers
if [ -f /.dockerenv ]; then
    echo -e "${GREEN}Running inside container${NC}"
    EXEC_PREFIX=""
else
    echo -e "${YELLOW}Running on host, will exec into ray-head container${NC}"
    EXEC_PREFIX="docker exec -it ray-head"
fi

# Function to check Ray cluster
check_cluster() {
    echo -e "${BLUE}1. Checking Ray cluster status...${NC}"

    if $EXEC_PREFIX ray status 2>/dev/null; then
        echo -e "${GREEN}✓ Ray cluster is running${NC}\n"
        return 0
    else
        echo -e "${RED}✗ Ray cluster is not accessible${NC}"
        echo -e "${YELLOW}  Make sure ray-head container is running${NC}\n"
        return 1
    fi
}

# Function to submit a job
submit_job() {
    local job_name=$1
    local script_path=$2
    local working_dir=$3

    echo -e "${BLUE}Submitting job: ${job_name}${NC}"

    # Copy script to container if running from host
    if [ -n "$EXEC_PREFIX" ]; then
        docker cp "$script_path" ray-head:/tmp/
        script_path="/tmp/$(basename $script_path)"
    fi

    # Submit the job
    if $EXEC_PREFIX ray job submit \
        --address="http://127.0.0.1:8265" \
        --runtime-env-json="{\"env_vars\":{\"MLFLOW_TRACKING_URI\":\"http://mlflow-server:5000\"}}" \
        -- python "$script_path"; then
        echo -e "${GREEN}✓ Job submitted successfully${NC}\n"
        return 0
    else
        echo -e "${RED}✗ Job submission failed${NC}\n"
        return 1
    fi
}

# Function to list jobs
list_jobs() {
    echo -e "${BLUE}Listing recent Ray jobs...${NC}"
    $EXEC_PREFIX ray job list --address="http://127.0.0.1:8265" 2>/dev/null || echo "No jobs found"
    echo
}

# Main execution
main() {
    # Check cluster
    if ! check_cluster; then
        exit 1
    fi

    # Test 1: Simple CPU job
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Test 1: Simple CPU Job (Pi Calculation)${NC}"
    echo -e "${BLUE}========================================${NC}\n"

    if [ -f "${EXAMPLES_DIR}/simple_job.py" ]; then
        submit_job "simple_pi_calculation" "${EXAMPLES_DIR}/simple_job.py" "$EXAMPLES_DIR"
    else
        echo -e "${RED}✗ simple_job.py not found${NC}\n"
    fi

    # Test 2: GPU job (if available)
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Test 2: GPU Job (Matrix Multiplication)${NC}"
    echo -e "${BLUE}========================================${NC}\n"

    if [ -f "${EXAMPLES_DIR}/gpu_job.py" ]; then
        submit_job "gpu_matrix_multiplication" "${EXAMPLES_DIR}/gpu_job.py" "$EXAMPLES_DIR"
    else
        echo -e "${YELLOW}⚠ gpu_job.py not found, skipping GPU test${NC}\n"
    fi

    # List all jobs
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Job Summary${NC}"
    echo -e "${BLUE}========================================${NC}\n"
    list_jobs

    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}Test suite completed!${NC}"
    echo -e "${GREEN}========================================${NC}\n"

    echo -e "${BLUE}Next steps:${NC}"
    echo -e "  1. View jobs in Ray Dashboard: http://localhost/ray/"
    echo -e "  2. Check MLflow experiments: http://localhost/mlflow/"
    echo -e "  3. Monitor metrics in Grafana: http://localhost/ray-grafana/"
    echo -e "  4. View logs: docker logs ray-head"
}

main "$@"
