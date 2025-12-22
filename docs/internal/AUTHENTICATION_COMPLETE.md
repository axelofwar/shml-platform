# Authentication & Access Control - Complete Documentation

**FusionAuth + OAuth2-Proxy + Role-Based Access Control**

**Status:** ✅ Production Ready  
**Last Updated:** January 11, 2025  
**Version:** 1.0.0

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture](#architecture)
3. [Role System](#role-system)
4. [Service Access Matrix](#service-access-matrix)
5. [Authentication Flows](#authentication-flows)
6. [JWT Bearer Token Authentication](#jwt-bearer-token-authentication)
7. [FusionAuth Configuration](#fusionauth-configuration)
8. [API Key Setup](#api-key-setup)
9. [Middleware Reference](#middleware-reference)
10. [Troubleshooting](#troubleshooting)

---

## Executive Summary

The platform uses a **three-tier authentication system**:

1. **FusionAuth** - OAuth/SSO provider with social login (Google, GitHub, Twitter)
2. **OAuth2-Proxy** - OAuth middleware for Traefik with JWT validation
3. **Role-Auth Middleware** - Custom role verification service

### Four User Roles

| Role | Description | Access Level |
|------|-------------|--------------|
| **viewer** | Default role, monitoring only | Grafana, Homer, inference APIs |
| **developer** | Full development access | MLflow, Ray, Agent Service, Chat UI |
| **elevated-developer** | Developer + code execution | Sandbox execution, model management |
| **admin** | Full platform access | Traefik, Prometheus, FusionAuth Admin |

---

## Architecture

### Authentication Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER REQUEST                                 │
│  ├─ Browser: Cookie-based OAuth2 flow                               │
│  └─ API/CI/CD: Authorization: Bearer <JWT>                          │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  TRAEFIK GATEWAY                                                     │
│  Routes to OAuth2-Proxy forwardAuth middleware                       │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  OAuth2-Proxy (Authentication Layer)                                 │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ Step 1: Check Authorization Header                            │   │
│  │   - Bearer <JWT> → Validate against FusionAuth JWKS          │   │
│  │   - No Bearer → Check session cookie / redirect to login      │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ Step 2: Set Response Headers                                  │   │
│  │   X-Auth-Request-User: <user claim>                           │   │
│  │   X-Auth-Request-Email: <email claim>                         │   │
│  │   X-Auth-Request-Groups: <roles claim>                        │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Role-Auth Middleware                                                │
│  Reads X-Auth-Request-Groups → 200 if authorized, 403 if not        │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Upstream Service (Agent API, MLflow, Ray, etc.)                    │
└─────────────────────────────────────────────────────────────────────┘
```

### Middleware Chain by Role

```yaml
# Viewer access (monitoring)
middlewares: oauth2-errors,oauth2-auth,role-auth-viewer

# Developer access (most services)
middlewares: oauth2-errors,oauth2-auth,role-auth-developer

# Elevated-Developer access (sandboxes)
middlewares: oauth2-errors,oauth2-auth,role-auth-elevated

# Admin access (platform management)
middlewares: oauth2-errors,oauth2-auth,role-auth-admin
```

---

## Role System

### Role Hierarchy (Inheritance)

```
viewer < developer < elevated-developer < admin
```

Each role inherits access from all lower roles:
- `viewer` → viewer access only
- `developer` → viewer + developer access
- `elevated-developer` → viewer + developer + elevated access
- `admin` → all access (superRole)

### FusionAuth Configuration

```
✓ viewer              (isDefault: true)  - Read-only, basic chat
✓ developer           (isDefault: false) - Full dev access, ML workflow
✓ elevated-developer  (isDefault: false) - Developer + code execution
✓ admin               (isDefault: false, isSuperRole: true) - Full access
```

---

## Service Access Matrix

| Service | Guest | Viewer | Developer | Elevated | Admin | Middleware |
|---------|-------|--------|-----------|----------|-------|------------|
| **Inference APIs** |
| Coding Models | ✅ | ✅ | ✅ | ✅ | ✅ | none |
| Chat API | ✅ | ✅ | ✅ | ✅ | ✅ | none |
| Image Gen (Z-Image) | ✅ | ✅ | ✅ | ✅ | ✅ | none |
| Vision (Qwen-VL) | ✅ | ✅ | ✅ | ✅ | ✅ | none |
| Embedding Service | ✅ | ✅ | ✅ | ✅ | ✅ | none |
| **Monitoring** |
| Homer Dashboard | ❌ | ✅ | ✅ | ✅ | ✅ | role-auth-viewer |
| Grafana | ❌ | ✅ | ✅ | ✅ | ✅ | role-auth-viewer |
| **ML Workflow** |
| MLflow UI | ❌ | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| MLflow API | ❌ | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| Ray Dashboard | ❌ | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| Ray Jobs API | ❌ | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| **Agent Service** |
| Agent REST API | ❌ | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| Agent WebSocket | ❌ | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| Agent Sandbox | ❌ | ❌ | ❌ | ✅ | ✅ | in-code check |
| **User Interface** |
| Chat UI | ❌ | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| Dozzle (Logs) | ❌ | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| **Admin** |
| Prometheus | ❌ | ❌ | ❌ | ❌ | ✅ | role-auth-admin |
| Traefik Dashboard | ❌ | ❌ | ❌ | ❌ | ✅ | role-auth-admin |
| Infisical | ❌ | ❌ | ❌ | ❌ | ✅ | role-auth-admin |

---

## Authentication Flows

### Flow 1: Browser OAuth (User Login)

```
1. User visits platform URL
2. OAuth2-Proxy intercepts (no session) → Redirects to FusionAuth
3. FusionAuth shows login page:
   - Email/Password
   - Social login (Google, GitHub, Twitter)
4. User authenticates
5. FusionAuth redirects to OAuth2-Proxy callback
6. OAuth2-Proxy creates session (8hr expiry, Redis)
7. User lands on Homer Dashboard
```

### Flow 2: Social OAuth (Google/GitHub/Twitter)

```
1. User clicks "Sign in with Google/GitHub/Twitter"
2. Redirected to OAuth provider
3. User authorizes application
4. Provider redirects back to FusionAuth
5. FusionAuth:
   - Creates/links user account
   - Assigns default role (viewer)
   - Issues access/refresh tokens
6. OAuth2-Proxy receives tokens, creates session
7. User authenticated ✅
```

### Flow 3: Self-Registration

```
1. User clicks "Create an account"
2. FusionAuth registration form:
   - Email (required)
   - Password (required)
   - First/Last Name (required)
3. User submits form
4. FusionAuth creates user:
   - Email verified: true
   - Default role: viewer
5. User authenticated with viewer access
```

---

## JWT Bearer Token Authentication

### How It Works

OAuth2-Proxy v7.6.0+ supports `--skip-jwt-bearer-tokens` for API access:

```yaml
oauth2-proxy:
  environment:
    OAUTH2_PROXY_SKIP_JWT_BEARER_TOKENS: "true"
    OAUTH2_PROXY_OIDC_ISSUER_URL: "https://${PUBLIC_DOMAIN}"
    OAUTH2_PROXY_CLIENT_ID: "${FUSIONAUTH_PROXY_CLIENT_ID}"
    OAUTH2_PROXY_OIDC_GROUPS_CLAIM: "roles"
```

### Getting a JWT Token

#### Method 1: Client Credentials (Service-to-Service)

```bash
curl -X POST http://localhost:9011/oauth2/token \
  -d "client_id=${FUSIONAUTH_CLIENT_ID}" \
  -d "client_secret=${FUSIONAUTH_CLIENT_SECRET}" \
  -d "grant_type=client_credentials" \
  -d "scope=openid" \
  | jq -r '.access_token'
```

#### Method 2: Password Grant (Testing Only)

```bash
# Enable temporarily
curl -X PATCH http://localhost:9011/api/application/${APP_ID} \
  -H "Authorization: ${FUSIONAUTH_API_KEY}" \
  -d '{"application":{"oauthConfiguration":{"enabledGrants":["authorization_code","refresh_token","password"]}}}'

# Get token
curl -X POST http://localhost:9011/oauth2/token \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" \
  -d "grant_type=password" \
  -d "username=user@example.com" \
  -d "password=your-password" \
  -d "scope=openid email profile" \
  | jq -r '.access_token'

# Disable after testing
curl -X PATCH http://localhost:9011/api/application/${APP_ID} \
  -H "Authorization: ${FUSIONAUTH_API_KEY}" \
  -d '{"application":{"oauthConfiguration":{"enabledGrants":["authorization_code","refresh_token"]}}}'
```

### Using JWT Token

```bash
# Set token
JWT="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."

# Call API with Bearer token
curl -X GET http://localhost/api/agent/health \
  -H "Authorization: Bearer $JWT"

# Execute agent
curl -X POST http://localhost/api/agent/execute \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "ci-pipeline",
    "session_id": "automation-1",
    "task": "Create a Python function",
    "category": "coding"
  }'
```

---

## FusionAuth Configuration

### Application Settings

| Setting | Value |
|---------|-------|
| Application Name | OAuth2-Proxy |
| Client Type | Confidential |
| Authorized Redirect URIs | `https://domain/oauth2/callback` |
| Authorized Grant Types | authorization_code, refresh_token |
| Access Token Lifetime | 3600 seconds (1 hour) |
| Refresh Token Lifetime | 2592000 seconds (30 days) |

### Identity Providers

| Provider | Status | Configuration |
|----------|--------|---------------|
| Google | ✅ Enabled | OAuth2 Client ID/Secret from Google Console |
| GitHub | ✅ Enabled | OAuth App ID/Secret from GitHub Settings |
| Twitter | ✅ Enabled | OAuth 2.0 Client ID/Secret from Twitter Dev |

### Lambda Functions

**JWT Populate Lambda** - Adds roles to JWT claims:
```javascript
function populate(jwt, user, registration) {
  jwt.roles = registration.roles || [];
  jwt.user = user.id;
  jwt.email = user.email;
  return jwt;
}
```

---

## API Key Setup

### Required API Keys (4 keys)

| Key Name | Role | Usage |
|----------|------|-------|
| Viewer Key | viewer | External monitoring, read-only access |
| Developer Key | developer | CI/CD pipelines, ML automation |
| Elevated Key | elevated-developer | GitHub Actions, sandbox execution |
| Admin Superkey | admin | Platform administration, emergency access |

### Creating API Keys in FusionAuth

1. Navigate to Settings → API Keys
2. Click "Add"
3. Enter key name and description
4. Select permissions/endpoints
5. Save and copy the generated key

---

## Middleware Reference

### Role-Auth Middleware Endpoints

| Endpoint | Required Roles |
|----------|----------------|
| `/auth/viewer` | viewer, developer, elevated-developer, admin |
| `/auth/developer` | developer, elevated-developer, admin |
| `/auth/elevated-developer` | elevated-developer, admin |
| `/auth/admin` | admin |

### Nginx Configuration

```nginx
# /scripts/role-auth/nginx.conf
location /auth/viewer {
    # Check X-Auth-Request-Groups header
    # Allow: viewer, developer, elevated-developer, admin
}

location /auth/developer {
    # Allow: developer, elevated-developer, admin
}

location /auth/elevated-developer {
    # Allow: elevated-developer, admin
}

location /auth/admin {
    # Allow: admin only
}
```

---

## Troubleshooting

### Common Issues

#### "403 Forbidden" on protected route
- **Cause:** User lacks required role
- **Solution:**
  1. Check user's roles in FusionAuth Admin
  2. Verify middleware chain in Traefik labels
  3. Confirm X-Auth-Request-Groups header is being set

#### JWT validation fails
- **Cause:** Invalid or expired token
- **Solution:**
  1. Check token expiration
  2. Verify JWKS endpoint accessible
  3. Confirm aud claim matches client_id

#### Social login callback fails
- **Cause:** Misconfigured redirect URI
- **Solution:**
  1. Verify redirect URI in FusionAuth application settings
  2. Check OAuth provider app configuration
  3. Ensure HTTPS for production

### Verification Commands

```bash
# Check OAuth2-Proxy health
curl http://localhost/oauth2/ping

# Verify role-auth middleware
curl -H "X-Auth-Request-Groups: developer" http://localhost/auth/developer

# Test JWT validation
curl -H "Authorization: Bearer $JWT" http://localhost/api/agent/health

# Check FusionAuth status
curl http://localhost:9011/api/status
```

---

## Related Documentation

- **Agent Service:** `docs/internal/AGENT_SERVICE_COMPLETE.md`
- **Architecture:** `docs/internal/ARCHITECTURE.md`
- **Troubleshooting:** `docs/internal/TROUBLESHOOTING.md`
- **FusionAuth Kickstart:** `fusionauth/kickstart/kickstart.json`

---

**Consolidated from:**
- ACCESS_CONTROL_AUDIT.md
- AUTH_FLOW_AND_USER_ACCESS.md
- FUSIONAUTH_CONFIGURATION_GUIDE.md
- JWT_BEARER_TOKEN_AUTH.md
- ROLE_MAPPING_STRATEGY.md

**Migration Date:** January 11, 2025
