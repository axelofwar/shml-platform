#!/bin/bash
# Platform Admin SDK Test Runner
#
# Usage:
#   ./run_tests.sh              # Run all tests
#   ./run_tests.sh unit         # Run unit tests only
#   ./run_tests.sh integration  # Run integration tests only
#   ./run_tests.sh e2e          # Run e2e tests only
#   ./run_tests.sh cleanup      # Run cleanup tests only
#   ./run_tests.sh quick        # Run unit + infrastructure tests (fast)
#   ./run_tests.sh full         # Run all tests in order

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Change to project root
cd "$PROJECT_ROOT"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}  Platform Admin SDK Test Runner${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# Check for virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    if [ -d ".venv" ]; then
        echo -e "${YELLOW}Activating virtual environment...${NC}"
        source .venv/bin/activate
    else
        echo -e "${YELLOW}No virtual environment found. Using system Python.${NC}"
    fi
fi

# Install test dependencies if needed
echo -e "${BLUE}Checking test dependencies...${NC}"
pip install -q pytest pytest-order requests python-dotenv 2>/dev/null || true

# Set Python path to include SDK
export PYTHONPATH="$PROJECT_ROOT/scripts:$PYTHONPATH"

# Load environment variables if .env exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo -e "${BLUE}Loading environment from .env${NC}"
    export $(grep -v '^#' "$PROJECT_ROOT/.env" | xargs) 2>/dev/null || true
fi

# Parse command line argument
TEST_TYPE="${1:-all}"

echo -e "${BLUE}Running: $TEST_TYPE tests${NC}"
echo ""

case "$TEST_TYPE" in
    unit)
        echo -e "${GREEN}Running unit tests...${NC}"
        python -m pytest tests/platform_admin/test_unit.py -v --tb=short
        ;;
    integration)
        echo -e "${GREEN}Running integration tests...${NC}"
        python -m pytest tests/platform_admin/test_integration_listing.py tests/platform_admin/test_integration_users.py -v --tb=short -m integration
        ;;
    e2e)
        echo -e "${GREEN}Running e2e tests...${NC}"
        python -m pytest tests/platform_admin/test_e2e_access.py -v --tb=short -m e2e
        ;;
    cleanup)
        echo -e "${YELLOW}Running cleanup tests...${NC}"
        python -m pytest tests/platform_admin/test_cleanup.py -v --tb=short -m cleanup
        ;;
    quick)
        echo -e "${GREEN}Running quick tests (unit + infrastructure)...${NC}"
        python -m pytest tests/platform_admin/test_unit.py tests/platform_admin/test_integration_listing.py::TestInfrastructureRequirements -v --tb=short
        ;;
    full)
        echo -e "${GREEN}Running full test suite in order...${NC}"
        echo ""

        echo -e "${BLUE}Step 1: Unit tests${NC}"
        python -m pytest tests/platform_admin/test_unit.py -v --tb=short || true
        echo ""

        echo -e "${BLUE}Step 2: Infrastructure validation${NC}"
        python -m pytest tests/platform_admin/test_integration_listing.py::TestInfrastructureRequirements -v --tb=short || exit 1
        echo ""

        echo -e "${BLUE}Step 3: Listing tests${NC}"
        python -m pytest tests/platform_admin/test_integration_listing.py -v --tb=short || true
        echo ""

        echo -e "${BLUE}Step 4: User creation tests${NC}"
        python -m pytest tests/platform_admin/test_integration_users.py::TestUserCreation -v --tb=short || true
        echo ""

        echo -e "${BLUE}Step 5: User verification tests${NC}"
        python -m pytest tests/platform_admin/test_integration_users.py::TestUserVerification tests/platform_admin/test_integration_users.py::TestGroupMemberships tests/platform_admin/test_integration_users.py::TestRoleAssignments -v --tb=short || true
        echo ""

        echo -e "${BLUE}Step 6: E2E access tests${NC}"
        python -m pytest tests/platform_admin/test_e2e_access.py -v --tb=short || true
        echo ""

        echo -e "${BLUE}Step 7: Cleanup${NC}"
        python -m pytest tests/platform_admin/test_cleanup.py -v --tb=short || true
        ;;
    all|*)
        echo -e "${GREEN}Running all tests...${NC}"
        python -m pytest tests/platform_admin/ -v --tb=short
        ;;
esac

echo ""
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}  Tests Complete!${NC}"
echo -e "${GREEN}======================================${NC}"
