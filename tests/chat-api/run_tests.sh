#!/bin/bash
# Run Chat API tests
# Usage: ./run_tests.sh [pytest args]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "====================================="
echo "SHML Platform - Chat API Tests"
echo "====================================="

# Add project root to PYTHONPATH so imports work
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

# Check if we're in a virtual environment or have pytest
if ! command -v pytest &> /dev/null; then
    echo "pytest not found. Installing test dependencies..."
    pip install -r "$SCRIPT_DIR/requirements-test.txt"
fi

echo ""
echo "Running tests..."
echo ""

# Run pytest with verbose output
pytest "$SCRIPT_DIR" \
    -v \
    --tb=short \
    --strict-markers \
    "$@"

echo ""
echo "====================================="
echo "Tests completed!"
echo "====================================="
