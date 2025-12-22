#!/bin/bash
# Script to verify a user's email in FusionAuth
# Usage: ./verify_user_email.sh <user-id-or-email>

set -e

USER_IDENTIFIER="$1"

if [ -z "$USER_IDENTIFIER" ]; then
    echo "Usage: $0 <user-id-or-email>"
    echo "Example: $0 soundsbystoney@gmail.com"
    echo "Example: $0 49c56535-dbcf-4f0a-b90a-f15d4a22f970"
    exit 1
fi

# Load environment variables
if [ -f .env ]; then
    source .env
else
    echo "Error: .env file not found"
    exit 1
fi

FUSIONAUTH_API_KEY="${FUSIONAUTH_API_KEY:-bf69486b-4733-4470-a592-f1bfce7af580}"

echo "🔍 Checking user: $USER_IDENTIFIER"
echo ""

# Determine if it's an email or user ID
if [[ "$USER_IDENTIFIER" == *"@"* ]]; then
    echo "Searching for user by email..."
    USER_ID=$(docker exec fusionauth curl -s "http://localhost:9011/api/user/search" \
        -X POST \
        -H "Authorization: $FUSIONAUTH_API_KEY" \
        -H "Content-Type: application/json" \
        -d "{\"search\":{\"queryString\":\"email:$USER_IDENTIFIER\"}}" | jq -r '.users[0].id // empty')

    if [ -z "$USER_ID" ]; then
        echo "❌ User not found with email: $USER_IDENTIFIER"
        exit 1
    fi
    echo "✅ Found user ID: $USER_ID"
else
    USER_ID="$USER_IDENTIFIER"
fi

echo ""
echo "📋 User details:"
docker exec fusionauth curl -s "http://localhost:9011/api/user/$USER_ID" \
    -H "Authorization: $FUSIONAUTH_API_KEY" | jq '{
        id: .user.id,
        email: .user.email,
        verified: .user.verified,
        active: .user.active,
        registrations: [.user.registrations[]? | {
            applicationId: .applicationId,
            roles: .roles,
            verified: .verified
        }]
    }'

echo ""
read -p "🤔 Do you want to verify this user's email? (y/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "✉️ Verifying email..."
    RESULT=$(docker exec fusionauth curl -s -X PATCH "http://localhost:9011/api/user/$USER_ID" \
        -H "Authorization: $FUSIONAUTH_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{"user":{"verified":true}}')

    if echo "$RESULT" | jq -e '.user.verified == true' > /dev/null 2>&1; then
        echo "✅ Email verified successfully!"
        echo ""
        echo "📋 Updated user details:"
        echo "$RESULT" | jq '{
            email: .user.email,
            verified: .user.verified
        }'
    else
        echo "❌ Failed to verify email. Response:"
        echo "$RESULT" | jq '.'
    fi
else
    echo "❌ Cancelled. User email not verified."
fi
