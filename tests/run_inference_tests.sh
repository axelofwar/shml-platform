#!/bin/bash
# Run inference stack tests
#
# Usage:
#   ./run_inference_tests.sh           # Run all inference tests (unit + integration)
#   ./run_inference_tests.sh unit      # Run only unit tests (no GPU needed)
#   ./run_inference_tests.sh int       # Run only integration tests (services needed)
#   ./run_inference_tests.sh --skip-slow  # Skip slow tests

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo "================================================"
echo "Inference Stack Test Runner"
echo "================================================"
echo ""

# Parse arguments
TEST_TYPE="all"
SKIP_SLOW=""
VERBOSE="-v"

for arg in "$@"; do
    case $arg in
        unit)
            TEST_TYPE="unit"
            ;;
        int|integration)
            TEST_TYPE="integration"
            ;;
        --skip-slow)
            SKIP_SLOW="--skip-slow"
            ;;
        -vv)
            VERBOSE="-vv"
            ;;
        -q)
            VERBOSE=""
            ;;
    esac
done

# Check if pytest is available
if ! command -v pytest &> /dev/null; then
    echo -e "${RED}Error: pytest not found. Install with: pip install pytest${NC}"
    exit 1
fi

# Install test dependencies if needed
echo -e "${BLUE}Checking test dependencies...${NC}"
if ! python -c "import requests" 2>/dev/null; then
    echo -e "${YELLOW}Installing test dependencies...${NC}"
    pip install -r tests/requirements.txt
fi

echo ""

case $TEST_TYPE in
    unit)
        echo -e "${BLUE}Running unit tests (no GPU/services required)...${NC}"
        echo "================================================"
        pytest tests/unit/inference/ $VERBOSE $SKIP_SLOW --tb=short
        ;;
    integration)
        echo -e "${BLUE}Running integration tests (services required)...${NC}"
        echo "================================================"
        echo -e "${YELLOW}Note: Integration tests require running inference services${NC}"
        echo ""
        pytest tests/integration/test_inference_stack.py $VERBOSE $SKIP_SLOW --tb=short
        ;;
    all)
        echo -e "${BLUE}Running all inference tests...${NC}"
        echo "================================================"
        echo ""

        echo -e "${BLUE}Phase 1: Unit tests (no GPU required)${NC}"
        echo "------------------------------------------------"
        pytest tests/unit/inference/ $VERBOSE $SKIP_SLOW --tb=short || true

        echo ""
        echo -e "${BLUE}Phase 2: Integration tests (services required)${NC}"
        echo "------------------------------------------------"
        pytest tests/integration/test_inference_stack.py $VERBOSE $SKIP_SLOW --tb=short -m "not gpu" || true
        ;;
esac

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}Test run complete${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo "Tips:"
echo "  - Unit tests can run anywhere (no GPU needed)"
echo "  - Integration tests need running services"
echo "  - Use --skip-slow to skip slow tests"
echo "  - Use -vv for verbose output"
