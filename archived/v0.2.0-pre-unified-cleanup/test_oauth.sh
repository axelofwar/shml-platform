#!/bin/bash
# Test OAuth authentication for Ray Compute and MLflow

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.env"

echo "============================================"
echo "  OAuth Authentication Test"
echo "============================================"
echo

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test Authentik availability
echo "1. Testing Authentik server..."
if curl -sf http://localhost:9000/ > /dev/null 2>&1; then
    echo -e "   ${GREEN}✓${NC} Authentik is accessible"
else
    echo -e "   ${RED}✗${NC} Authentik is not accessible"
    exit 1
fi

# Test Ray Compute OAuth
echo
echo "2. Testing Ray Compute OAuth token acquisition..."
RAY_TOKEN_RESPONSE=$(curl -s -X POST http://localhost:9000/application/o/token/ \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=${RAY_OAUTH_CLIENT_ID}" \
  -d "client_secret=${RAY_OAUTH_CLIENT_SECRET}")

if echo "$RAY_TOKEN_RESPONSE" | jq -e '.access_token' > /dev/null 2>&1; then
    RAY_ACCESS_TOKEN=$(echo "$RAY_TOKEN_RESPONSE" | jq -r '.access_token')
    echo -e "   ${GREEN}✓${NC} Ray Compute OAuth token acquired"
    echo "   Token (first 20 chars): ${RAY_ACCESS_TOKEN:0:20}..."
else
    echo -e "   ${RED}✗${NC} Failed to acquire Ray Compute OAuth token"
    echo "   Response: $RAY_TOKEN_RESPONSE"
    exit 1
fi

# Test MLflow OAuth
echo
echo "3. Testing MLflow OAuth token acquisition..."
MLFLOW_TOKEN_RESPONSE=$(curl -s -X POST http://localhost:9000/application/o/token/ \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=${MLFLOW_OAUTH_CLIENT_ID}" \
  -d "client_secret=${MLFLOW_OAUTH_CLIENT_SECRET}")

if echo "$MLFLOW_TOKEN_RESPONSE" | jq -e '.access_token' > /dev/null 2>&1; then
    MLFLOW_ACCESS_TOKEN=$(echo "$MLFLOW_TOKEN_RESPONSE" | jq -r '.access_token')
    echo -e "   ${GREEN}✓${NC} MLflow OAuth token acquired"
    echo "   Token (first 20 chars): ${MLFLOW_ACCESS_TOKEN:0:20}..."
else
    echo -e "   ${RED}✗${NC} Failed to acquire MLflow OAuth token"
    echo "   Response: $MLFLOW_TOKEN_RESPONSE"
    exit 1
fi

# Test Ray Compute API with token
echo
echo "4. Testing Ray Compute API with OAuth token..."
RAY_API_RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" \
  -H "Authorization: Bearer $RAY_ACCESS_TOKEN" \
  http://localhost/api/ray/health)

HTTP_CODE=$(echo "$RAY_API_RESPONSE" | grep -o "HTTP_CODE:[0-9]*" | cut -d: -f2)
RESPONSE_BODY=$(echo "$RAY_API_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
    echo -e "   ${GREEN}✓${NC} Ray Compute API responded successfully"
    echo "   Response: $RESPONSE_BODY"
else
    echo -e "   ${YELLOW}⚠${NC} Ray Compute API returned HTTP $HTTP_CODE"
    echo "   Response: $RESPONSE_BODY"
    echo "   Note: This may be expected if OAuth enforcement is not yet fully configured"
fi

# Test MLflow API with token
echo
echo "5. Testing MLflow API with OAuth token..."
MLFLOW_API_RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" \
  -H "Authorization: Bearer $MLFLOW_ACCESS_TOKEN" \
  http://localhost/api/v1/health)

HTTP_CODE=$(echo "$MLFLOW_API_RESPONSE" | grep -o "HTTP_CODE:[0-9]*" | cut -d: -f2)
RESPONSE_BODY=$(echo "$MLFLOW_API_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
    echo -e "   ${GREEN}✓${NC} MLflow API responded successfully"
    echo "   Response: $RESPONSE_BODY"
else
    echo -e "   ${YELLOW}⚠${NC} MLflow API returned HTTP $HTTP_CODE"
    echo "   Response: $RESPONSE_BODY"
    echo "   Note: This may be expected if OAuth enforcement is not yet fully configured"
fi

echo
echo "============================================"
echo "  OAuth Test Summary"
echo "============================================"
echo
echo "✓ Authentik server accessible"
echo "✓ Ray Compute OAuth token acquired"
echo "✓ MLflow OAuth token acquired"
echo
echo "Next steps:"
echo "  1. Save tokens for API testing:"
echo "     export RAY_TOKEN='$RAY_ACCESS_TOKEN'"
echo "     export MLFLOW_TOKEN='$MLFLOW_ACCESS_TOKEN'"
echo
echo "  2. Test authenticated requests:"
echo "     curl -H \"Authorization: Bearer \$RAY_TOKEN\" http://localhost/api/ray/jobs"
echo "     curl -H \"Authorization: Bearer \$MLFLOW_TOKEN\" http://localhost/api/v1/experiments"
echo
echo "  3. Verify automatic MLflow logging in Ray jobs"
echo "     Submit a test job and check MLflow for logged runs"
echo
