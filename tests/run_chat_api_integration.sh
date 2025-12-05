#!/bin/bash
# Run Chat API integration tests against live services
#
# Prerequisites:
# 1. Chat API service running (docker compose -f inference/chat-api/docker-compose.yml up -d)
# 2. Redis running for rate limiting
# 3. API keys configured in .env or exported
#
# Usage:
#   ./tests/run_chat_api_integration.sh              # Run all tests (skips key-required tests)
#   ./tests/run_chat_api_integration.sh --with-keys  # Run all tests with API keys from .env

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Chat API Integration Tests${NC}"
echo -e "${GREEN}========================================${NC}"

# Check if chat-api is running
CHAT_API_URL="${CHAT_API_DIRECT_URL:-http://localhost:8000}"
echo -e "\n${YELLOW}Checking if Chat API is accessible at $CHAT_API_URL...${NC}"

if curl -s --max-time 5 "$CHAT_API_URL/health" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Chat API is running${NC}"
else
    echo -e "${RED}✗ Chat API is not accessible at $CHAT_API_URL${NC}"
    echo -e "${YELLOW}Start it with: docker compose -f inference/chat-api/docker-compose.yml up -d${NC}"

    # Ask if user wants to continue anyway (tests will skip)
    read -p "Continue anyway? Tests requiring the service will be skipped. (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Load API keys from .env if requested
if [[ "$1" == "--with-keys" ]]; then
    if [[ -f .env ]]; then
        echo -e "\n${YELLOW}Loading API keys from .env...${NC}"
        # Export only CHAT_API_* variables
        export $(grep -E "^CHAT_API_" .env | xargs)

        if [[ -n "$CHAT_API_TEST_KEY" ]]; then
            echo -e "${GREEN}✓ Developer API key loaded${NC}"
        else
            echo -e "${YELLOW}⚠ CHAT_API_TEST_KEY not found in .env${NC}"
        fi

        if [[ -n "$CHAT_API_ADMIN_KEY" ]]; then
            echo -e "${GREEN}✓ Admin API key loaded${NC}"
        else
            echo -e "${YELLOW}⚠ CHAT_API_ADMIN_KEY not found in .env${NC}"
        fi
    else
        echo -e "${RED}✗ .env file not found${NC}"
        exit 1
    fi
fi

# Activate virtual environment if available
if [[ -d ".venv" ]]; then
    source .venv/bin/activate
fi

echo -e "\n${YELLOW}Running integration tests...${NC}\n"

# Run the integration tests
PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH" pytest \
    tests/integration/test_chat_api_live.py \
    -v \
    -m integration \
    --tb=short \
    "$@"

TEST_EXIT_CODE=$?

echo -e "\n${GREEN}========================================${NC}"
if [[ $TEST_EXIT_CODE -eq 0 ]]; then
    echo -e "${GREEN}  All tests passed!${NC}"
else
    echo -e "${RED}  Some tests failed (exit code: $TEST_EXIT_CODE)${NC}"
fi
echo -e "${GREEN}========================================${NC}"

exit $TEST_EXIT_CODE
