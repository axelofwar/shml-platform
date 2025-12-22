#!/bin/bash
# Script to verify all user registrations in FusionAuth
# This fixes the "AuthenticatedRegistrationNotVerified" redirect loop issue

set -e

echo "🔧 Verifying all user registrations in FusionAuth..."
echo ""

# OAuth2-Proxy application ID
OAUTH2_PROXY_APP_ID="acda34f0-7cf2-40eb-9cba-7cb0048857d3"

# Get all unverified registrations
echo "📋 Finding unverified registrations..."
UNVERIFIED=$(docker exec shml-postgres psql -U fusionauth -d fusionauth -t -c "
    SELECT i.email, ur.users_id, ur.applications_id, ur.verified
    FROM user_registrations ur
    JOIN users u ON ur.users_id = u.id
    JOIN identities i ON u.id = i.users_id
    WHERE ur.applications_id = '$OAUTH2_PROXY_APP_ID' AND ur.verified = false;
")

if [ -z "$(echo "$UNVERIFIED" | tr -d '[:space:]')" ]; then
    echo "✅ All registrations are already verified!"
    exit 0
fi

echo "Found unverified registrations:"
echo "$UNVERIFIED"
echo ""

read -p "🤔 Do you want to verify all these registrations? (y/n): " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Cancelled. No changes made."
    exit 0
fi

echo "✉️ Verifying all registrations..."
docker exec shml-postgres psql -U fusionauth -d fusionauth -c "
    UPDATE user_registrations
    SET verified = true
    WHERE applications_id = '$OAUTH2_PROXY_APP_ID' AND verified = false;
"

echo ""
echo "✅ All registrations verified!"
echo ""
echo "📋 Current registration status:"
docker exec shml-postgres psql -U fusionauth -d fusionauth -c "
    SELECT
        i.email,
        i.verified as email_verified,
        ur.verified as registration_verified,
        COALESCE(
            (SELECT string_agg(ar.name, ', ')
             FROM user_registrations_application_roles urar
             JOIN application_roles ar ON urar.application_roles_id = ar.id
             WHERE urar.user_registrations_id = ur.id
             GROUP BY urar.user_registrations_id),
            'no roles'
        ) as roles
    FROM user_registrations ur
    JOIN users u ON ur.users_id = u.id
    JOIN identities i ON u.id = i.users_id
    WHERE ur.applications_id = '$OAUTH2_PROXY_APP_ID'
    ORDER BY i.email;
"

echo ""
echo "🎉 Done! Users should now be able to log in without redirect loops."
echo "   Note: Users may need to clear browser cookies/cache or sign out and back in."
