# JWT Bearer Token Authentication - SOTA Implementation

**Status:** ✅ **IMPLEMENTED** - Using OAuth2-Proxy `--skip-jwt-bearer-tokens` feature  
**Version:** OAuth2-Proxy v7.6.0  
**Date:** 2025-12-07  

---

## Overview

This document explains the **state-of-the-art** JWT Bearer token authentication pattern implemented in our platform using OAuth2-Proxy's built-in JWT validation feature.

### Why This is SOTA

1. **Industry Standard:** OAuth2-Proxy is used by 13.4k+ GitHub stars, 417 contributors, major enterprise adoptions
2. **Native JWT Support:** Built-in since v7.0+, no custom middleware needed
3. **Secure:** Validates JWT signatures against FusionAuth JWKS, checks audience claim
4. **Dual Mode:** Supports both browser (cookie) and API (Bearer token) access patterns
5. **Role Propagation:** Automatically forwards role claims to downstream middleware

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Client Request                                                     │
│  ├─ Browser: Cookie-based OAuth2 flow                              │
│  └─ API/CI/CD: Authorization: Bearer <JWT>                         │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Traefik (Reverse Proxy)                                            │
│  Routes to OAuth2-Proxy forwardAuth middleware                      │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  OAuth2-Proxy (Authentication Layer)                                │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Step 1: Check Authorization Header                           │  │
│  │   - If "Bearer <JWT>" present:                               │  │
│  │     → Validate JWT signature against FusionAuth JWKS         │  │
│  │     → Verify 'aud' matches client_id                         │  │
│  │     → Extract claims (user, email, roles)                    │  │
│  │     → Skip cookie check (bypass OAuth flow)                  │  │
│  │   - If no Bearer token:                                       │  │
│  │     → Check for session cookie                                │  │
│  │     → Redirect to FusionAuth login if needed                 │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Step 2: Set Response Headers                                 │  │
│  │   X-Auth-Request-User: <from JWT 'user' claim>               │  │
│  │   X-Auth-Request-Email: <from JWT 'email' claim>             │  │
│  │   X-Auth-Request-Groups: <from JWT 'roles' claim>            │  │
│  │   Authorization: Bearer <original JWT>                        │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Role-Auth Middleware (Role Enforcement)                            │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Reads X-Auth-Request-Groups header                           │  │
│  │   - /auth/viewer: allows viewer, developer, elevated, admin  │  │
│  │   - /auth/developer: allows developer, elevated, admin       │  │
│  │   - /auth/elevated-developer: allows elevated, admin         │  │
│  │   - /auth/admin: allows admin only                           │  │
│  │ Returns 200 if authorized, 403 if not                        │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Upstream Service (Agent API, MLflow, Ray, etc.)                   │
│  Receives request with user info in headers                         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Configuration

### OAuth2-Proxy Settings (docker-compose.infra.yml)

```yaml
oauth2-proxy:
  environment:
    # Enable JWT Bearer token validation
    OAUTH2_PROXY_SKIP_JWT_BEARER_TOKENS: "true"

    # OIDC configuration (for JWT validation)
    OAUTH2_PROXY_PROVIDER: "oidc"
    OAUTH2_PROXY_OIDC_ISSUER_URL: "https://${PUBLIC_DOMAIN}"
    OAUTH2_PROXY_CLIENT_ID: "${FUSIONAUTH_PROXY_CLIENT_ID}"

    # Role claim mapping
    OAUTH2_PROXY_OIDC_GROUPS_CLAIM: "roles"

    # Header forwarding
    OAUTH2_PROXY_SET_XAUTHREQUEST: "true"
    OAUTH2_PROXY_PASS_ACCESS_TOKEN: "true"
    OAUTH2_PROXY_PASS_AUTHORIZATION_HEADER: "true"
```

**Key Environment Variables:**

| Variable | Value | Purpose |
|----------|-------|---------|
| `OAUTH2_PROXY_SKIP_JWT_BEARER_TOKENS` | `true` | Enable JWT Bearer token validation |
| `OAUTH2_PROXY_OIDC_ISSUER_URL` | FusionAuth URL | JWKS endpoint for signature validation |
| `OAUTH2_PROXY_CLIENT_ID` | OAuth2-Proxy app ID | Expected `aud` claim in JWT |
| `OAUTH2_PROXY_OIDC_GROUPS_CLAIM` | `roles` | Map FusionAuth roles to groups |
| `OAUTH2_PROXY_SET_XAUTHREQUEST` | `true` | Forward user/email/groups headers |

---

## How to Get JWT Tokens

### Method 1: Browser-Based OAuth Flow (Recommended for Users)

1. **User logs in via browser** → FusionAuth OAuth2 flow
2. **OAuth2-Proxy sets session cookie** → Stored in Redis
3. **Session lasts 8 hours** with auto-refresh (30-day refresh token)

### Method 2: Password Grant (CI/CD, Scripts)

**Note:** Password grant is currently **disabled** for security. Enable temporarily only for testing.

```bash
# Enable password grant in FusionAuth (temporary)
curl -X PATCH http://localhost:9011/api/application/acda34f0-7cf2-40eb-9cba-7cb0048857d3 \
  -H "Authorization: ${FUSIONAUTH_API_KEY}" \
  -d '{"application":{"oauthConfiguration":{"enabledGrants":["authorization_code","refresh_token","password"]}}}'

# Get JWT token
curl -X POST http://localhost:9011/oauth2/token \
  -d "client_id=acda34f0-7cf2-40eb-9cba-7cb0048857d3" \
  -d "client_secret=L8cS5c9Sy3IBMAums6ZGgnQtTbQxTTwJQO6FFd3pQzA" \
  -d "grant_type=password" \
  -d "username=your-email@example.com" \
  -d "password=your-password" \
  -d "scope=openid email profile" \
  | jq -r '.access_token'

# Disable password grant after testing (security best practice)
curl -X PATCH http://localhost:9011/api/application/acda34f0-7cf2-40eb-9cba-7cb0048857d3 \
  -H "Authorization: ${FUSIONAUTH_API_KEY}" \
  -d '{"application":{"oauthConfiguration":{"enabledGrants":["authorization_code","refresh_token"]}}}'
```

### Method 3: Client Credentials Flow (Service-to-Service)

**Best for:** CI/CD pipelines, automated systems, background jobs

```bash
# Get JWT token using client credentials
curl -X POST http://localhost:9011/oauth2/token \
  -d "client_id=acda34f0-7cf2-40eb-9cba-7cb0048857d3" \
  -d "client_secret=L8cS5c9Sy3IBMAums6ZGgnQtTbQxTTwJQO6FFd3pQzA" \
  -d "grant_type=client_credentials" \
  -d "scope=openid" \
  | jq -r '.access_token'
```

**Note:** Client credentials tokens have the roles of the application registration, not a specific user.

---

## Usage Examples

### Example 1: Agent API Health Check

```bash
# Get JWT token (assume you have one)
JWT="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."

# Test health endpoint
curl -X GET http://localhost/api/agent/health \
  -H "Authorization: Bearer $JWT"

# Expected: 200 OK with {"status": "healthy", ...}
```

### Example 2: Agent Execution (Elevated Developer)

```bash
# Execute code via agent
curl -X POST http://localhost/api/agent/execute \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "ci-pipeline",
    "session_id": "github-actions-1",
    "task": "Create a Python function that calculates fibonacci numbers",
    "category": "coding",
    "max_iterations": 3
  }'

# Expected: 200 OK with agent response
```

### Example 3: Sandbox Execution (Elevated Developer Only)

```bash
# This requires elevated-developer or admin role
curl -X POST http://localhost/api/agent/execute \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "ci-pipeline",
    "session_id": "github-actions-2",
    "task": "Run pytest on the test suite",
    "category": "testing",
    "use_sandbox": true,
    "max_iterations": 1
  }'

# Expected with elevated-developer: 200 OK
# Expected with developer role: 403 Forbidden
```

### Example 4: MLflow API Access (Developer)

```bash
# List experiments
curl -X GET http://localhost/mlflow/api/2.0/mlflow/experiments/list \
  -H "Authorization: Bearer $JWT"

# Expected: 200 OK with experiments list
```

---

## Role-Based Access Matrix

| Endpoint | Viewer | Developer | Elevated-Developer | Admin |
|----------|--------|-----------|-------------------|-------|
| `/` (Homer dashboard) | ✅ | ✅ | ✅ | ✅ |
| `/grafana/*` | ✅ | ✅ | ✅ | ✅ |
| `/mlflow/*` | ❌ | ✅ | ✅ | ✅ |
| `/ray/*` | ❌ | ✅ | ✅ | ✅ |
| `/api/agent/*` | ❌ | ✅ | ✅ | ✅ |
| Sandbox execution | ❌ | ❌ | ✅ | ✅ |
| GitHub Actions | ❌ | ❌ | ✅ | ✅ |
| Model management | ❌ | ❌ | ✅ | ✅ |
| `/traefik/*` (admin panel) | ❌ | ❌ | ❌ | ✅ |
| Host access | ❌ | ❌ | ❌ | ✅ |

---

## JWT Token Structure

### Access Token Claims (from FusionAuth)

```json
{
  "aud": "acda34f0-7cf2-40eb-9cba-7cb0048857d3",
  "exp": 1765151516,
  "iat": 1765147916,
  "iss": "https://shml-platform.tail38b60a.ts.net",
  "sub": "c784043e-7d0a-43fc-8f28-8abb339bd9d3",
  "jti": "b29b0c11-222b-4035-a0ca-7456f23673b3",
  "authenticationType": "PASSWORD",
  "email": "elevated-developer-service@ml-platform.local",
  "email_verified": true,
  "applicationId": "acda34f0-7cf2-40eb-9cba-7cb0048857d3",
  "roles": ["elevated-developer"],
  "auth_time": 1765147916,
  "tid": "8beb3def-b3f9-29e4-2761-6c888715 3e9c"
}
```

**Critical Claims:**

- `aud`: Must match `OAUTH2_PROXY_CLIENT_ID` for validation to pass
- `exp`: Token expiration (default: 1 hour)
- `roles`: Array of user roles (maps to `X-Auth-Request-Groups`)
- `sub`: User ID (unique identifier)
- `email`: User email

---

## Security Considerations

### 1. JWT Signature Validation

OAuth2-Proxy validates JWT signatures against FusionAuth's JWKS endpoint:
```
https://shml-platform.tail38b60a.ts.net/.well-known/jwks.json
```

**This ensures:**
- Token was issued by FusionAuth
- Token has not been tampered with
- Token is still valid (not expired)

### 2. Audience Claim Verification

The `aud` claim must match the OAuth2-Proxy client ID. This prevents:
- Tokens issued for other applications from being accepted
- Token reuse attacks across different services

### 3. Role Claim Trust

OAuth2-Proxy trusts the `roles` claim from FusionAuth. **Security requirements:**
- FusionAuth must be properly secured (admin UI access restricted)
- Role assignments should be audited
- API keys for FusionAuth must be rotated regularly

### 4. Token Expiration

- **Access tokens:** 1 hour (default)
- **Refresh tokens:** 30 days (can be used to get new access tokens)
- **Session cookies:** 8 hours with auto-refresh

**Best practice:** Use short-lived access tokens for API access.

### 5. HTTPS Required

JWT tokens should only be transmitted over HTTPS. Our setup:
- Tailscale Funnel terminates TLS
- Internal communication can use HTTP (within Docker network)
- External access requires HTTPS

---

## Troubleshooting

### Issue: 401 Unauthorized with JWT Bearer Token

**Cause:** OAuth2-Proxy not validating JWT tokens

**Solution:**
1. Check `OAUTH2_PROXY_SKIP_JWT_BEARER_TOKENS=true` is set
2. Restart OAuth2-Proxy: `docker compose -f docker-compose.infra.yml restart oauth2-proxy`
3. Check logs: `docker logs oauth2-proxy`

### Issue: 403 Forbidden after successful authentication

**Cause:** User has correct JWT but wrong role

**Solution:**
1. Check JWT payload: `echo $JWT | cut -d. -f2 | base64 -d | jq .roles`
2. Verify user has required role in FusionAuth Admin UI
3. Check role-auth middleware logs: `docker logs role-auth`

### Issue: JWT signature validation fails

**Cause:** FusionAuth JWKS endpoint unreachable or JWT from wrong issuer

**Solution:**
1. Test JWKS endpoint: `curl https://shml-platform.tail38b60a.ts.net/.well-known/jwks.json`
2. Check `OAUTH2_PROXY_OIDC_ISSUER_URL` matches FusionAuth URL
3. Verify JWT `iss` claim matches issuer URL

### Issue: Roles not propagating to role-auth middleware

**Cause:** `X-Auth-Request-Groups` header not set

**Solution:**
1. Verify `OAUTH2_PROXY_SET_XAUTHREQUEST=true`
2. Check `OAUTH2_PROXY_OIDC_GROUPS_CLAIM="roles"`
3. Test header forwarding: `curl -v http://localhost/api/agent/health -H "Authorization: Bearer $JWT" 2>&1 | grep X-Auth`

---

## Testing Checklist

### ✅ Infrastructure Verified

- [x] OAuth2-Proxy v7.6.0 running
- [x] `OAUTH2_PROXY_SKIP_JWT_BEARER_TOKENS=true` configured
- [x] FusionAuth JWKS endpoint accessible
- [x] Role-auth middleware supports 4 roles (viewer, developer, elevated-developer, admin)
- [x] Docker socket mounted for sandbox execution

### ⏳ Pending Validation

- [ ] JWT Bearer token health check (200 OK)
- [ ] JWT Bearer token agent execution (200/202)
- [ ] Viewer role blocked (403)
- [ ] Developer role agent access (200)
- [ ] Elevated-developer sandbox access (200)
- [ ] Admin full access (200)

### 📋 Manual Testing Steps (Browser)

Since password grant is disabled, use browser-based testing:

1. **Login as different users:**
   - soundsbystoney@gmail.com (viewer)
   - bncyberspace@msn.com (developer)
   - elevated-developer-service@ml-platform.local (elevated-developer)
   - axelofwar.web3@gmail.com (admin - needs role assignment)

2. **Test access levels:**
   - Viewer: Can access Grafana, blocked from Agent API
   - Developer: Can access Agent API, blocked from sandbox
   - Elevated: Can use sandbox, GitHub actions
   - Admin: Can access Traefik dashboard

3. **Verify role enforcement:**
   - Check browser dev tools for 403 errors
   - Check OAuth2-Proxy logs for role checks
   - Check role-auth logs for middleware decisions

---

## References

### OAuth2-Proxy Documentation

- [Skip JWT Bearer Tokens](https://oauth2-proxy.github.io/oauth2-proxy/docs/configuration/overview#proxy-options)
- [OIDC Groups Claim](https://oauth2-proxy.github.io/oauth2-proxy/docs/configuration/oauth_provider#openid-connect-provider)
- [Header Configuration](https://oauth2-proxy.github.io/oauth2-proxy/docs/configuration/overview#header-options)
- [Behavior Documentation](https://oauth2-proxy.github.io/oauth2-proxy/docs/behaviour)

### Related Files

- `docker-compose.infra.yml` - OAuth2-Proxy configuration
- `docs/internal/ROLE_MAPPING_STRATEGY.md` - Role definitions and access matrix
- `docs/internal/AUTH_FLOW_AND_USER_ACCESS.md` - Authentication flow documentation
- `scripts/test-oauth2-roles.sh` - OAuth2 testing guide

---

**Last Updated:** 2025-12-07  
**Status:** Implementation complete, awaiting validation testing  
**Next Steps:** Browser-based manual testing with real user accounts
