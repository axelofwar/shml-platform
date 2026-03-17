#!/bin/bash
# SFML Platform - Test Runner Script
# Builds and runs the unified test container
#
# Usage:
#   ./tests/run_tests_container.sh                    # Run all tests
#   ./tests/run_tests_container.sh unit               # Run unit tests only
#   ./tests/run_tests_container.sh integration        # Run integration tests only
#   ./tests/run_tests_container.sh -k "copilot"       # Run tests matching pattern
#   ./tests/run_tests_container.sh --shell            # Interactive shell
#   ./tests/run_tests_container.sh --build            # Force rebuild container

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         SFML Platform - Test Runner                        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"

# Parse arguments
BUILD_FLAG=""
SHELL_MODE=false
TEST_ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --build)
            BUILD_FLAG="--build"
            shift
            ;;
        --shell)
            SHELL_MODE=true
            shift
            ;;
        unit)
            TEST_ARGS+=("/workspace/tests/unit" "-v" "-s")
            shift
            ;;
        integration)
            TEST_ARGS+=("/workspace/tests/integration" "-v" "-s")
            shift
            ;;
        *)
            TEST_ARGS+=("$1")
            shift
            ;;
    esac
done

# Default test args if none specified
if [ ${#TEST_ARGS[@]} -eq 0 ]; then
    TEST_ARGS=("/workspace/tests" "-v" "--tb=short")
fi

cd "$PROJECT_ROOT"

# Build the test container if needed
if [ -n "$BUILD_FLAG" ] || ! docker images | grep -q "shml-platform-test"; then
    echo -e "${YELLOW}Building test container...${NC}"
    docker compose -f tests/docker/docker-compose.test.yml build
fi

# Run tests
if [ "$SHELL_MODE" = true ]; then
    echo -e "${YELLOW}Starting interactive shell...${NC}"
    docker compose -f tests/docker/docker-compose.test.yml run --rm --entrypoint bash test
else
    echo -e "${YELLOW}Running tests: ${TEST_ARGS[*]}${NC}"
    echo ""

    # Run the tests
    if docker compose -f tests/docker/docker-compose.test.yml run --rm test "${TEST_ARGS[@]}"; then
        echo ""
        echo -e "${GREEN}✓ All tests passed!${NC}"
        exit 0
    else
        echo ""
        echo -e "${RED}✗ Some tests failed${NC}"
        exit 1
    fi
fi
