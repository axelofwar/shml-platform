#!/bin/bash
# Generate a comprehensive user verification report for FusionAuth
# Checks email verification, registration verification, and role assignments

set -e

# Required environment variables
: "${FUSIONAUTH_API_KEY:?Set FUSIONAUTH_API_KEY environment variable}"
: "${OAUTH2_PROXY_APP_ID:=acda34f0-7cf2-40eb-9cba-7cb0048857d3}"

echo "╔════════════════════════════════════════════════════════════════════════════╗"
echo "║                   FUSIONAUTH USER VERIFICATION REPORT                      ║"
echo "╚════════════════════════════════════════════════════════════════════════════╝"
echo ""

# 1. Tenant Configuration
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1️⃣  TENANT EMAIL VERIFICATION SETTINGS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker exec fusionauth curl -s "http://localhost:9011/api/tenant" \
    -H "Authorization: ${FUSIONAUTH_API_KEY}" | \
    jq -r '.tenants[] |
        "Tenant: \(.name)\n" +
        "  ├─ Verify Email: \(.emailConfiguration.verifyEmail)\n" +
        "  ├─ Verify Email When Changed: \(.emailConfiguration.verifyEmailWhenChanged)\n" +
        "  └─ Verification Strategy: \(.emailConfiguration.verificationStrategy)"'
echo ""

# 2. Application Configuration
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2️⃣  APPLICATION REGISTRATION VERIFICATION SETTINGS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker exec fusionauth curl -s "http://localhost:9011/api/application/$OAUTH2_PROXY_APP_ID" \
    -H "Authorization: ${FUSIONAUTH_API_KEY}" | \
    jq -r '.application |
        "Application: \(.name)\n" +
        "  ├─ Verify Registration: \(.verifyRegistration)\n" +
        "  └─ Registration Type: \(.registrationConfiguration.type)"'
echo ""

# 3. User Verification Status
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3️⃣  USER VERIFICATION STATUS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker exec shml-postgres psql -U fusionauth -d fusionauth -c "
    SELECT
        i.email as \"Email\",
        CASE WHEN i.verified THEN '✅' ELSE '❌' END as \"Email Verified\",
        CASE WHEN ur.verified THEN '✅' ELSE '❌' END as \"Registration Verified\",
        COALESCE(
            (SELECT string_agg(ar.name, ', ')
             FROM user_registrations_application_roles urar
             JOIN application_roles ar ON urar.application_roles_id = ar.id
             WHERE urar.user_registrations_id = ur.id
             GROUP BY urar.user_registrations_id),
            'no roles'
        ) as \"Roles\",
        CASE
            WHEN i.verified AND ur.verified THEN '✅ OK'
            WHEN i.verified AND NOT ur.verified THEN '⚠️  Registration Not Verified'
            WHEN NOT i.verified AND ur.verified THEN '⚠️  Email Not Verified'
            ELSE '❌ Both Not Verified'
        END as \"Status\"
    FROM identities i
    JOIN users u ON i.users_id = u.id
    JOIN user_registrations ur ON u.id = ur.users_id
    WHERE ur.applications_id = '$OAUTH2_PROXY_APP_ID'
    ORDER BY i.email;
"
echo ""

# 4. Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4️⃣  SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

TOTAL_USERS=$(docker exec shml-postgres psql -U fusionauth -d fusionauth -t -c "
    SELECT COUNT(*)
    FROM user_registrations ur
    WHERE ur.applications_id = '$OAUTH2_PROXY_APP_ID';
" | tr -d ' ')

VERIFIED_EMAILS=$(docker exec shml-postgres psql -U fusionauth -d fusionauth -t -c "
    SELECT COUNT(*)
    FROM identities i
    JOIN users u ON i.users_id = u.id
    JOIN user_registrations ur ON u.id = ur.users_id
    WHERE ur.applications_id = '$OAUTH2_PROXY_APP_ID' AND i.verified = true;
" | tr -d ' ')

VERIFIED_REGISTRATIONS=$(docker exec shml-postgres psql -U fusionauth -d fusionauth -t -c "
    SELECT COUNT(*)
    FROM user_registrations ur
    WHERE ur.applications_id = '$OAUTH2_PROXY_APP_ID' AND ur.verified = true;
" | tr -d ' ')

FULLY_VERIFIED=$(docker exec shml-postgres psql -U fusionauth -d fusionauth -t -c "
    SELECT COUNT(*)
    FROM identities i
    JOIN users u ON i.users_id = u.id
    JOIN user_registrations ur ON u.id = ur.users_id
    WHERE ur.applications_id = '$OAUTH2_PROXY_APP_ID'
      AND i.verified = true
      AND ur.verified = true;
" | tr -d ' ')

echo "Total Users: $TOTAL_USERS"
echo "  ├─ Email Verified: $VERIFIED_EMAILS/$TOTAL_USERS"
echo "  ├─ Registration Verified: $VERIFIED_REGISTRATIONS/$TOTAL_USERS"
echo "  └─ Fully Verified (Both): $FULLY_VERIFIED/$TOTAL_USERS"
echo ""

# Status Check
if [ "$FULLY_VERIFIED" -eq "$TOTAL_USERS" ]; then
    echo "✅ STATUS: All users are fully verified!"
    echo "   Users can authenticate without redirect loops."
else
    UNVERIFIED=$((TOTAL_USERS - FULLY_VERIFIED))
    echo "⚠️  STATUS: $UNVERIFIED user(s) not fully verified."
    echo "   Run ./scripts/verify_all_registrations.sh to fix."
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Report generated: $(date)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
