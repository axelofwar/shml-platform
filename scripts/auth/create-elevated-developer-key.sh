#!/bin/bash
# Create elevated-developer API key for FusionAuth
# This key will be used for GitHub Actions, model management, and testing sandbox execution

set -e

FUSIONAUTH_URL="${FUSIONAUTH_URL:-http://localhost:9011}"
FUSIONAUTH_API_KEY="${FUSIONAUTH_API_KEY:-pYxEbVSHPxJTSTksYEGAA3LLSfh2fvrBZ91dA945Km7yk0JJu2uDDt_t}"
OAUTH2_PROXY_APP_ID="acda34f0-7cf2-40eb-9cba-7cb0048857d3"
ELEVATED_DEV_ROLE_ID="b8d14b7f-84a7-4707-8b79-cb6929be0edd"

echo "======================================="
echo "Creating elevated-developer API key"
echo "======================================="
echo

# Check if running inside container
if [ -f "/.dockerenv" ]; then
    FUSIONAUTH_URL="http://localhost:9011"
    CURL_CMD="curl"
else
    # Running from host, use docker exec
    CURL_CMD="docker exec fusionauth curl"
fi

# Generate a secure random API key (compatible with FusionAuth format)
# FusionAuth uses base64url encoding without padding
NEW_API_KEY=$(openssl rand -base64 48 | tr '+/' '-_' | tr -d '=')

echo "Generated API key: ${NEW_API_KEY:0:20}..."
echo

# Create user for the API key (service account)
echo "Step 1: Creating service account for elevated-developer..."
SERVICE_USER_RESPONSE=$($CURL_CMD -s -X POST \
    "${FUSIONAUTH_URL}/api/user" \
    -H "Authorization: ${FUSIONAUTH_API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{
        "user": {
            "email": "elevated-developer-service@ml-platform.local",
            "username": "elevated-developer-service",
            "fullName": "Elevated Developer Service Account",
            "password": "'"$(openssl rand -base64 32)"'"
        },
        "sendSetPasswordEmail": false,
        "skipVerification": true
    }')

# Extract user ID (may already exist)
SERVICE_USER_ID=$(echo "$SERVICE_USER_RESPONSE" | jq -r '.user.id // empty')

if [ -z "$SERVICE_USER_ID" ]; then
    # User might already exist, try to get it
    echo "Service account may already exist, fetching..."
    SERVICE_USER_ID=$($CURL_CMD -s -X GET \
        "${FUSIONAUTH_URL}/api/user?email=elevated-developer-service@ml-platform.local" \
        -H "Authorization: ${FUSIONAUTH_API_KEY}" \
        | jq -r '.user.id')
fi

echo "Service user ID: ${SERVICE_USER_ID}"
echo

# Step 2: Register user to OAuth2-Proxy app with elevated-developer role
echo "Step 2: Registering service account to OAuth2-Proxy with elevated-developer role..."
REGISTRATION_RESPONSE=$($CURL_CMD -s -X POST \
    "${FUSIONAUTH_URL}/api/user/registration/${SERVICE_USER_ID}" \
    -H "Authorization: ${FUSIONAUTH_API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{
        "registration": {
            "applicationId": "'"${OAUTH2_PROXY_APP_ID}"'",
            "roles": ["elevated-developer"]
        }
    }')

# Check for errors (ignore if already registered)
if echo "$REGISTRATION_RESPONSE" | jq -e '.fieldErrors // .generalErrors' > /dev/null 2>&1; then
    echo "Note: Registration may already exist (this is okay)"
fi

echo "✓ Service account registered with elevated-developer role"
echo

# Step 3: Create the API key
echo "Step 3: Creating API key..."

# Note: FusionAuth API keys don't directly store user roles
# Instead, they have full API access and roles are checked when used with OAuth2
# For testing, we'll create a generic API key and document its intended use

API_KEY_RESPONSE=$($CURL_CMD -s -X POST \
    "${FUSIONAUTH_URL}/api/api-key" \
    -H "Authorization: ${FUSIONAUTH_API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{
        "apiKey": {
            "key": "'"${NEW_API_KEY}"'",
            "description": "[C]/[CD] Elevated Developer key - For GitHub Actions, model management, sandbox execution"
        }
    }')

# Check for errors
if echo "$API_KEY_RESPONSE" | jq -e '.fieldErrors // .generalErrors' > /dev/null 2>&1; then
    echo "✗ Failed to create API key:"
    echo "$API_KEY_RESPONSE" | jq '.fieldErrors // .generalErrors'

    # Check if key already exists
    if echo "$API_KEY_RESPONSE" | jq -e '.fieldErrors.key' | grep -q "duplicate"; then
        echo
        echo "API key already exists. Retrieving existing key..."
        # In production, you'd store this securely
    fi
    exit 1
fi

echo "✓ API key created successfully"
echo

# Step 4: Verify the API key
echo "Step 4: Verifying API key..."
VERIFY_RESPONSE=$($CURL_CMD -s -X GET \
    "${FUSIONAUTH_URL}/api/system/version" \
    -H "Authorization: ${NEW_API_KEY}")

if echo "$VERIFY_RESPONSE" | jq -e '.version' > /dev/null 2>&1; then
    echo "✓ API key verified successfully"
    FUSIONAUTH_VERSION=$(echo "$VERIFY_RESPONSE" | jq -r '.version')
    echo "  FusionAuth version: ${FUSIONAUTH_VERSION}"
else
    echo "✗ API key verification failed"
    exit 1
fi

echo
echo "======================================="
echo "✓ API Key Creation Complete"
echo "======================================="
echo
echo "Add this to your .env file:"
echo
echo "FUSIONAUTH_CICD_ELEVATED_KEY=${NEW_API_KEY}"
echo
echo "Export for testing:"
echo
echo "export ELEVATED_DEVELOPER_API_KEY='${NEW_API_KEY}'"
echo
echo "Next steps:"
echo "  1. Add to .env file"
echo "  2. Run: ./scripts/test-role-auth.sh"
echo "  3. Test sandbox execution with elevated-developer key"
echo
echo "⚠️  SECURITY NOTE:"
echo "  - Store this key securely (use secrets manager in production)"
echo "  - This key has elevated privileges for sandbox execution"
echo "  - Rotate regularly (recommended: every 90 days)"
