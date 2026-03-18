#!/bin/bash
#
# ML Platform Test Runner
# Run comprehensive tests across all access methods
#

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "=========================================="
echo "  ML PLATFORM COMPREHENSIVE TEST SUITE"
echo "=========================================="
echo ""

# Check if virtual environment exists
if [ ! -d "tests/venv" ]; then
    echo "Creating test virtual environment..."
    python3 -m venv tests/venv
    source tests/venv/bin/activate
    pip install --upgrade pip
    pip install -r tests/requirements.txt
else
    source tests/venv/bin/activate
fi

# Parse arguments
HOST="${1:-all}"
VERBOSE="${2:-}"

echo "Test Configuration:"
echo "  Host: $HOST"
echo "  Verbose: ${VERBOSE:-no}"
echo "  Workers: 1 (sequential to prevent resource exhaustion)"
echo ""

# Run tests based on host selection with resource limits
case "$HOST" in
    "local")
        echo -e "${YELLOW}Testing LOCAL access (localhost)...${NC}"
        pytest tests/ --host=local -v $VERBOSE -n 1 --maxfail=5
        ;;
    "lan")
        echo -e "${YELLOW}Testing LAN access (${SERVER_IP})...${NC}"
        pytest tests/ --host=lan -v $VERBOSE -n 1 --maxfail=5
        ;;
    "vpn")
        echo -e "${YELLOW}Testing VPN access (${TAILSCALE_IP})...${NC}"
        pytest tests/ --host=vpn -v $VERBOSE -n 1 --maxfail=5
        ;;
    "all")
        echo -e "${YELLOW}Testing ALL access methods...${NC}"
        pytest tests/ --host=all -v $VERBOSE -n 1 --maxfail=5
        ;;
    "quick")
        echo -e "${YELLOW}Running quick tests (skip slow)...${NC}"
        pytest tests/ --skip-slow -v $VERBOSE -n 1 --maxfail=3
        ;;
    *)
        echo -e "${RED}Invalid host option: $HOST${NC}"
        echo "Usage: $0 {local|lan|vpn|all|quick} [--cov]"
        exit 1
        ;;
esac

EXIT_CODE=$?

echo ""
echo "=========================================="
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ ALL TESTS PASSED${NC}"
else
    echo -e "${RED}✗ SOME TESTS FAILED${NC}"
fi
echo "=========================================="

exit $EXIT_CODE
