#!/bin/bash
# Add elevated-developer role to FusionAuth OAuth2-Proxy application
# This role sits between developer and admin for sandbox execution and model management

set -e

FUSIONAUTH_URL="${FUSIONAUTH_URL:-http://localhost:9011}"
FUSIONAUTH_API_KEY="${FUSIONAUTH_API_KEY:-pYxEbVSHPxJTSTksYEGAA3LLSfh2fvrBZ91dA945Km7yk0JJu2uDDt_t}"
OAUTH2_PROXY_APP_ID="acda34f0-7cf2-40eb-9cba-7cb0048857d3"

echo "======================================="
echo "Adding elevated-developer role to FusionAuth"
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

# Step 1: Get current application configuration
echo "Step 1: Fetching current OAuth2-Proxy application configuration..."
CURRENT_APP=$($CURL_CMD -s -X GET \
    "${FUSIONAUTH_URL}/api/application/${OAUTH2_PROXY_APP_ID}" \
    -H "Authorization: ${FUSIONAUTH_API_KEY}")

echo "Current roles:"
echo "$CURRENT_APP" | jq -r '.application.roles[] | "  - \(.name) (default: \(.isDefault))"'
echo

# Check if elevated-developer already exists
if echo "$CURRENT_APP" | jq -e '.application.roles[] | select(.name == "elevated-developer")' > /dev/null 2>&1; then
    echo "✓ elevated-developer role already exists"
    echo
    echo "Current role configuration:"
    echo "$CURRENT_APP" | jq '.application.roles[] | {name: .name, id: .id, isDefault: .isDefault, isSuperRole: .isSuperRole}'
    exit 0
fi

# Step 2: Add elevated-developer role
echo "Step 2: Adding elevated-developer role..."
NEW_ROLE_RESPONSE=$($CURL_CMD -s -X POST \
    "${FUSIONAUTH_URL}/api/application/${OAUTH2_PROXY_APP_ID}/role" \
    -H "Authorization: ${FUSIONAUTH_API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{
        "role": {
            "name": "elevated-developer",
            "description": "Developer with elevated privileges: sandbox execution, model management, GitHub Actions access",
            "isDefault": false,
            "isSuperRole": false
        }
    }')

# Check for errors
if echo "$NEW_ROLE_RESPONSE" | jq -e '.fieldErrors // .generalErrors' > /dev/null 2>&1; then
    echo "✗ Failed to add role:"
    echo "$NEW_ROLE_RESPONSE" | jq '.fieldErrors // .generalErrors'
    exit 1
fi

echo "✓ elevated-developer role added successfully"
echo

# Step 3: Verify the role was added
echo "Step 3: Verifying role configuration..."
UPDATED_APP=$($CURL_CMD -s -X GET \
    "${FUSIONAUTH_URL}/api/application/${OAUTH2_PROXY_APP_ID}" \
    -H "Authorization: ${FUSIONAUTH_API_KEY}")

echo "Updated roles:"
echo "$UPDATED_APP" | jq -r '.application.roles[] | "  - \(.name) (id: \(.id))"'
echo

# Get the elevated-developer role ID for API key creation
ELEVATED_DEV_ROLE_ID=$(echo "$UPDATED_APP" | jq -r '.application.roles[] | select(.name == "elevated-developer") | .id')

echo "======================================="
echo "✓ Role Configuration Complete"
echo "======================================="
echo
echo "Role Hierarchy:"
echo "  1. viewer           (default, read-only)"
echo "  2. developer        (ML workflows, no sandboxes)"
echo "  3. elevated-developer (developer + sandboxes + model mgmt)"
echo "  4. admin            (full platform access)"
echo
echo "Next steps:"
echo "  1. Create API key with elevated-developer role"
echo "  2. Update role-auth middleware (already supports elevated-developer)"
echo "  3. Test sandbox execution with elevated-developer key"
echo
echo "Elevated-Developer Role ID: ${ELEVATED_DEV_ROLE_ID}"
echo "Save this for API key creation"
