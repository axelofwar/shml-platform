# Authentication & Authorization Flow

**Version:** 1.0.0  
**Last Updated:** 2025-12-05  
**Purpose:** Detailed authentication and authorization flow documentation

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication Stack](#authentication-stack)
3. [Login Flow](#login-flow)
4. [Authorization Flow](#authorization-flow)
5. [Token Management](#token-management)
6. [Role-Based Access Control](#role-based-access-control)
7. [Troubleshooting](#troubleshooting)

---

## Overview

The ML Platform uses a multi-layered authentication and authorization system:

- **OAuth2/OIDC Provider:** FusionAuth
- **OAuth2 Proxy:** oauth2-proxy (session management)
- **Role-Based Auth:** role-auth service (RBAC enforcement)
- **API Gateway:** Traefik (middleware orchestration)

### Key Characteristics

- ✅ **Standards-Based:** OAuth 2.0 + OpenID Connect
- ✅ **Social Logins:** Google, GitHub, Twitter (via FusionAuth)
- ✅ **Role-Based:** Developer and Admin roles
- ✅ **Stateless:** JWT tokens + session cookies
- ✅ **Single Sign-On:** One login for all services

---

## Authentication Stack

### Component Responsibilities

```
┌─────────────────────────────────────────────────────────────┐
│                         CLIENT                              │
│                   (Browser/API Client)                      │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP Request
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                       TRAEFIK                               │
│                   (API Gateway)                             │
│  - Routes requests by path                                  │
│  - Applies middleware chain                                 │
│  - Handles HTTPS termination                                │
└────────────────────────┬────────────────────────────────────┘
                         │ Middleware Chain
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   OAUTH2-ERRORS                             │
│            (Error Handling Middleware)                      │
│  - Catches 401/403 from oauth2-auth                         │
│  - Redirects to /oauth2-proxy/sign_in?rd={url}             │
└────────────────────────┬────────────────────────────────────┘
                         │ If not 401/403
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    OAUTH2-AUTH                              │
│            (Authentication Middleware)                      │
│  - ForwardAuth to oauth2-proxy:4180/oauth2-proxy/auth      │
│  - Validates session cookie                                 │
│  - Returns user headers or 401                              │
└────────────────────────┬────────────────────────────────────┘
                         │ If authenticated
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   ROLE-AUTH-DEVELOPER                       │
│            (Authorization Middleware)                       │
│  - ForwardAuth to role-auth:8080/auth/developer            │
│  - Checks X-Auth-Request-Groups header                      │
│  - Returns 200 if role matches, 403 if not                  │
└────────────────────────┬────────────────────────────────────┘
                         │ If authorized
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    BACKEND SERVICE                          │
│         (MLflow, Ray, Grafana, etc.)                        │
│  - Receives request with user headers                       │
│  - X-Auth-Request-User: email                               │
│  - X-Auth-Request-Email: email                              │
│  - X-Auth-Request-Groups: developer,admin                   │
└─────────────────────────────────────────────────────────────┘
```

### Service Details

**FusionAuth (fusionauth:9011)**
- OAuth2/OIDC provider
- User management
- Group/role management
- Social login integration
- Token issuance

**OAuth2 Proxy (oauth2-proxy:4180)**
- Session cookie management
- Token validation
- Token refresh
- ForwardAuth endpoint: `/oauth2-proxy/auth`
- Sign-in page: `/oauth2-proxy/sign_in`
- Callback: `/oauth2-proxy/callback`

**Role Auth (role-auth:8080)**
- Nginx-based RBAC service
- Endpoints:
  - `/auth/developer` - Requires "developer" or "admin" group
  - `/auth/admin` - Requires "admin" group
- Checks `X-Auth-Request-Groups` header

**Traefik (ml-platform-traefik:80)**
- API gateway
- Middleware orchestration
- Route management
- HTTPS termination

---

## Login Flow

### Initial Access (No Session)

```
1. User visits http://localhost/mlflow/
      │
      ▼
2. Traefik receives request
      │
      ├─ Rule: PathPrefix(`/mlflow/`)
      ├─ Middlewares: oauth2-errors,oauth2-auth,role-auth-developer
      │
      ▼
3. oauth2-auth middleware (ForwardAuth)
      │
      ├─ Sends request to oauth2-proxy:4180/oauth2-proxy/auth
      │
      ▼
4. OAuth2 Proxy checks session cookie
      │
      ├─ No cookie found
      ├─ Returns 401 Unauthorized
      │
      ▼
5. oauth2-errors middleware catches 401
      │
      ├─ Redirects to /oauth2-proxy/sign_in?rd=/mlflow/
      │
      ▼
6. OAuth2 Proxy /sign_in page
      │
      ├─ Builds OAuth2 authorize URL
      ├─ Redirects to FusionAuth
      │
      ▼
7. FusionAuth /oauth2/authorize
      │
      ├─ Shows login page
      ├─ User enters credentials or uses social login
      │
      ▼
8. User authenticates with FusionAuth
      │
      ├─ FusionAuth validates credentials
      ├─ Creates authorization code
      ├─ Redirects to /oauth2-proxy/callback?code=...
      │
      ▼
9. OAuth2 Proxy /callback handler
      │
      ├─ Receives authorization code
      ├─ Exchanges code for access token (POST to FusionAuth /oauth2/token)
      ├─ Validates token
      ├─ Creates session cookie
      ├─ Redirects to original URL (/mlflow/)
      │
      ▼
10. User visits /mlflow/ again (with session cookie)
      │
      ├─ oauth2-auth validates session
      ├─ role-auth-developer validates "developer" role
      ├─ Request forwarded to mlflow-nginx
      │
      ▼
11. MLflow UI loads successfully
```

### Subsequent Access (With Session)

```
1. User visits http://localhost/grafana/
      │
      ▼
2. Traefik → oauth2-errors → oauth2-auth middleware
      │
      ▼
3. OAuth2 Proxy checks session cookie
      │
      ├─ Cookie present and valid
      ├─ Returns 200 with user headers
      │
      ▼
4. Request forwarded to grafana:3000
      │
      ▼
5. Grafana loads (with user info in headers)
```

### Token Refresh Flow

```
1. User's access token expires (typically 1 hour)
      │
      ▼
2. OAuth2 Proxy detects expired token
      │
      ├─ Uses refresh token
      ├─ POST to FusionAuth /oauth2/token
      ├─ grant_type=refresh_token
      │
      ▼
3. FusionAuth validates refresh token
      │
      ├─ Returns new access token
      ├─ Returns new refresh token
      │
      ▼
4. OAuth2 Proxy updates session
      │
      ├─ Stores new tokens
      ├─ Updates cookie expiry
      │
      ▼
5. Request proceeds normally
```

---

## Authorization Flow

### Role-Based Access Control (RBAC)

After authentication succeeds, authorization checks the user's roles:

```
1. Authenticated request reaches role-auth middleware
      │
      ▼
2. Traefik forwards request to role-auth:8080/auth/{role}
      │
      ├─ /auth/developer → Requires "developer" or "admin"
      ├─ /auth/admin → Requires "admin" only
      │
      ▼
3. Role Auth service (Nginx) checks X-Auth-Request-Groups
      │
      ├─ Header: "X-Auth-Request-Groups: developer,admin"
      │
      ▼
4. Nginx regex match on groups
      │
      ├─ For /auth/developer:
      │   if ($http_x_auth_request_groups ~* "(developer|admin)") {
      │       return 200;
      │   }
      │   return 403;
      │
      ├─ For /auth/admin:
      │   if ($http_x_auth_request_groups ~* "admin") {
      │       return 200;
      │   }
      │   return 403;
      │
      ▼
5. If authorized (200): Request proceeds to backend
   If denied (403): Traefik returns 403 Forbidden
```

### Service Protection Matrix

| Service | Path | OAuth2 | Role Required | Notes |
|---------|------|--------|---------------|-------|
| MLflow UI | /mlflow/ | ✅ | developer | Experiment tracking |
| MLflow API | /api/v2.0/mlflow/* | ✅ | developer | API access |
| Ray Dashboard | /ray/ | ✅ | developer | Cluster monitoring |
| Ray API | /api/compute/* | ✅ | developer | Job submission |
| Grafana | /grafana/ | ✅ | - | Dashboards |
| Prometheus | /prometheus/ | ✅ | admin | Raw metrics |
| Traefik | /traefik | ✅ | admin | Gateway admin |
| Dozzle | /dozzle/ | ✅ | developer | Log viewer |
| Homer | / | ✅ | - | Landing page |
| FusionAuth | /auth/, /admin/ | ❌ | - | Public (auth pages) |
| OAuth2 Proxy | /oauth2-proxy/* | ❌ | - | Public (callbacks) |
| Webhook | /webhook/* | ❌ | - | HMAC-signed |

### Middleware Configuration

**In docker-compose.infra.yml:**

```yaml
# OAuth2 Authentication
traefik.http.middlewares.oauth2-auth.forwardauth.address: |
  http://oauth2-proxy:4180/oauth2-proxy/auth
traefik.http.middlewares.oauth2-auth.forwardauth.trustForwardHeader: "true"
traefik.http.middlewares.oauth2-auth.forwardauth.authResponseHeaders: |
  X-Auth-Request-User,X-Auth-Request-Email,X-Auth-Request-Groups,Authorization

# OAuth2 Error Handling
traefik.http.middlewares.oauth2-errors.errors.status: "401-403"
traefik.http.middlewares.oauth2-errors.errors.service: "oauth2-proxy"
traefik.http.middlewares.oauth2-errors.errors.query: |
  /oauth2-proxy/sign_in?rd={url}

# Role-Based Authorization
traefik.http.middlewares.role-auth-developer.forwardauth.address: |
  http://role-auth:8080/auth/developer
traefik.http.middlewares.role-auth-developer.forwardauth.trustForwardHeader: "true"

traefik.http.middlewares.role-auth-admin.forwardauth.address: |
  http://role-auth:8080/auth/admin
traefik.http.middlewares.role-auth-admin.forwardauth.trustForwardHeader: "true"
```

**Service Protection Example (MLflow):**

```yaml
mlflow-server:
  labels:
    - "traefik.enable=true"
    - "traefik.http.routers.mlflow-ui.rule=PathPrefix(`/mlflow/`)"
    - "traefik.http.routers.mlflow-ui.entrypoints=web,websecure"
    - "traefik.http.routers.mlflow-ui.middlewares=oauth2-errors,oauth2-auth,role-auth-developer"
```

---

## Token Management

### Token Types

**Access Token (JWT):**
- **Lifetime:** 1 hour (configurable in FusionAuth)
- **Purpose:** API access, user identification
- **Storage:** Session cookie (managed by oauth2-proxy)
- **Format:** JWT with claims (sub, email, groups, exp, iat)

**Refresh Token:**
- **Lifetime:** 30 days (configurable in FusionAuth)
- **Purpose:** Renew access token without re-login
- **Storage:** Session cookie (managed by oauth2-proxy)
- **Security:** Single-use, rotates on each refresh

**Session Cookie:**
- **Name:** `_oauth2_proxy` (configurable)
- **Lifetime:** Tied to refresh token (30 days)
- **Security:** HTTPOnly, Secure (HTTPS), SameSite=Lax
- **Storage:** Browser cookies

### Token Claims (Access Token JWT)

```json
{
  "sub": "user-uuid-12345",
  "email": "user@example.com",
  "groups": ["developer", "admin"],
  "name": "John Doe",
  "iss": "https://shml-platform.tail38b60a.ts.net",
  "aud": "oauth2-proxy-client-id",
  "exp": 1733409600,
  "iat": 1733406000,
  "auth_time": 1733406000
}
```

### Token Validation

**OAuth2 Proxy validates tokens by:**
1. JWT signature (RSA or HMAC)
2. Expiration time (exp claim)
3. Issuer (iss claim)
4. Audience (aud claim)

**Token Introspection (if JWT validation fails):**
```http
POST https://fusionauth:9011/oauth2/introspect
Authorization: Basic {client_id}:{client_secret}
Content-Type: application/x-www-form-urlencoded

token={access_token}
```

---

## Role-Based Access Control

### Role Hierarchy

```
admin (superuser)
  ├── All developer permissions
  ├── Traefik dashboard access
  ├── Prometheus raw metrics access
  ├── System configuration
  └── User management (via FusionAuth admin)

developer (default)
  ├── MLflow experiment tracking
  ├── Ray job submission
  ├── Grafana dashboards
  ├── Dozzle log viewer
  └── Homer landing page

viewer (future)
  └── Read-only dashboard access
```

### FusionAuth Group Setup

**Creating Groups:**
```bash
# Via Platform SDK
from platform_sdk import FusionAuthClient

client = FusionAuthClient(
    base_url="http://fusionauth:9011",
    api_key="${FUSIONAUTH_API_KEY}"
)

# Create developer group
developer_group = client.groups.create({
    "name": "developer",
    "roles": ["developer"]
})

# Create admin group
admin_group = client.groups.create({
    "name": "admin",
    "roles": ["admin"]
})
```

**Assigning Users to Groups:**
```bash
# Add user to developer group
client.groups.add_member(
    group_id=developer_group.id,
    user_id="user-uuid-12345"
)

# Add user to admin group
client.groups.add_member(
    group_id=admin_group.id,
    user_id="user-uuid-12345"
)
```

**Via FusionAuth Admin UI:**
1. Navigate to http://localhost/admin/
2. Go to Users → Select user
3. Go to Groups tab
4. Add to "developer" or "admin" group
5. Save

### Role Auth Service Configuration

**File:** `scripts/role-auth/nginx.conf`

```nginx
server {
    listen 8080;
    server_name role-auth;

    # Developer role check (requires "developer" or "admin")
    location /auth/developer {
        if ($http_x_auth_request_groups ~* "(developer|admin)") {
            return 200;
        }
        return 403;
    }

    # Admin role check (requires "admin")
    location /auth/admin {
        if ($http_x_auth_request_groups ~* "admin") {
            return 200;
        }
        return 403;
    }

    # Health check
    location /health {
        return 200 "OK\n";
    }
}
```

---

## Troubleshooting

### Common Issues

#### 1. Login Loop

**Symptom:** User gets redirected to login page infinitely

**Causes:**
- OAuth2 Proxy can't reach FusionAuth
- FusionAuth redirect URL misconfigured
- Session cookie not being set

**Debug:**
```bash
# Check OAuth2 Proxy logs
docker logs oauth2-proxy

# Check FusionAuth logs
docker logs fusionauth

# Verify FusionAuth OAuth client redirect URLs
# Should include: http://localhost/oauth2-proxy/callback
#                 https://shml-platform.tail38b60a.ts.net/oauth2-proxy/callback

# Test OAuth2 Proxy auth endpoint
curl -I http://localhost/mlflow/
# Should redirect to /oauth2-proxy/sign_in

# Check session cookie
# Browser DevTools → Application → Cookies
# Should see _oauth2_proxy cookie after login
```

**Fix:**
```bash
# Update FusionAuth OAuth client redirect URLs
./start_all_safe.sh fix-oauth
```

#### 2. 500 Internal Server Error

**Symptom:** All protected services return 500

**Causes:**
- oauth2-auth middleware not registered in Traefik
- OAuth2 Proxy container not running or unhealthy

**Debug:**
```bash
# Check middleware registration
curl -s http://localhost:8090/api/http/middlewares | jq '.[] | select(.name=="oauth2-auth@docker")'

# Should return middleware config
# If empty, oauth2-proxy middleware not registered

# Check OAuth2 Proxy status
docker ps --filter "name=oauth2-proxy"

# Check Traefik logs for errors
docker logs ml-platform-traefik 2>&1 | grep -i oauth
```

**Fix:**
```bash
# Restart OAuth2 Proxy
docker-compose -f docker-compose.infra.yml restart oauth2-proxy

# Wait for middleware registration
sleep 30

# Verify middleware exists
curl -s http://localhost:8090/api/http/middlewares | grep oauth2-auth

# Restart Traefik to pick up middleware
docker-compose -f docker-compose.infra.yml restart traefik
```

#### 3. 403 Forbidden After Login

**Symptom:** User can log in but gets 403 on all services

**Causes:**
- User not in required role/group
- role-auth service not working
- X-Auth-Request-Groups header not passed

**Debug:**
```bash
# Check user's groups in FusionAuth
# FusionAuth Admin UI → Users → Select user → Groups tab

# Check role-auth service
curl -i -H "X-Auth-Request-Groups: developer" http://role-auth:8080/auth/developer
# Should return 200

curl -i -H "X-Auth-Request-Groups: viewer" http://role-auth:8080/auth/developer
# Should return 403

# Check OAuth2 Proxy headers
docker logs oauth2-proxy | grep -i "x-auth-request-groups"
```

**Fix:**
```bash
# Add user to developer group via Platform SDK
python scripts/platform_sdk/bootstrap/add_user_to_group.py \
    --user-email user@example.com \
    --group developer

# Or via FusionAuth Admin UI (see Role Assignment above)
```

#### 4. Path Prefix Conflict (/oauth2 vs /oauth2-proxy)

**Symptom:** OAuth callback fails with 404

**Cause:** FusionAuth uses `/oauth2/*` for OIDC endpoints, conflicts with OAuth2 Proxy default `/oauth2/*`

**Solution:** OAuth2 Proxy uses `/oauth2-proxy/*` prefix

**Verify:**
```bash
# Check OAuth2 Proxy config
docker exec oauth2-proxy printenv | grep PROXY_PREFIX
# Should show: OAUTH2_PROXY_PROXY_PREFIX=/oauth2-proxy

# Check FusionAuth OAuth client
# Redirect URLs should be: /oauth2-proxy/callback (not /oauth2/callback)

# Check Traefik routes
curl -s http://localhost:8090/api/http/routers | jq '.[] | select(.name | contains("oauth"))'
# Should show separate routes for /oauth2/* (FusionAuth) and /oauth2-proxy/* (OAuth2 Proxy)
```

#### 5. Token Expired

**Symptom:** User logged in but suddenly gets 401

**Causes:**
- Access token expired (after 1 hour)
- Refresh token expired (after 30 days)
- Session cookie deleted

**Normal Behavior:** OAuth2 Proxy automatically refreshes token

**If refresh fails:**
```bash
# Check OAuth2 Proxy logs
docker logs oauth2-proxy | grep -i "refresh"

# User needs to log in again
# Clear cookies and revisit any protected page
```

---

## Security Best Practices

### 1. Secret Management

**OAuth2 Client Secret:**
```bash
# Generate secure secret
openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c 64 > secrets/oauth2_client_secret.txt

# Never commit to git (already in .gitignore)
```

**Cookie Secret:**
```bash
# OAuth2 Proxy requires 16, 24, or 32 byte cookie secret
openssl rand -base64 32 > secrets/oauth2_cookie_secret.txt
```

### 2. HTTPS Enforcement

**Traefik Configuration:**
```yaml
entrypoints:
  websecure:
    address: :443
    http:
      tls: true

# Redirect HTTP → HTTPS (production)
middlewares:
  https-redirect:
    redirectscheme:
      scheme: https
      permanent: true
```

**OAuth2 Proxy Configuration:**
```yaml
environment:
  OAUTH2_PROXY_COOKIE_SECURE: "true"  # Only send cookie over HTTPS
  OAUTH2_PROXY_COOKIE_SAMESITE: "lax"  # CSRF protection
```

### 3. Token Rotation

**Refresh Token Rotation (enabled by default in FusionAuth):**
- Each token refresh returns new refresh token
- Old refresh token is invalidated
- Prevents replay attacks

### 4. Session Timeout

**Idle Timeout:**
```yaml
# OAuth2 Proxy config
OAUTH2_PROXY_COOKIE_REFRESH: "1h"  # Refresh session cookie every hour
OAUTH2_PROXY_COOKIE_EXPIRE: "720h"  # 30 days (tied to refresh token)
```

**Absolute Timeout:**
```yaml
# FusionAuth Application config
jwt:
  timeToLiveInSeconds: 3600  # 1 hour access token
refresh_token:
  timeToLiveInMinutes: 43200  # 30 days refresh token
```

### 5. Rate Limiting

**FusionAuth Rate Limiting:**
- Failed login attempts: 5 per hour
- Password reset: 3 per hour
- Email verification: 3 per hour

**Traefik Rate Limiting (optional):**
```yaml
middlewares:
  rate-limit:
    ratelimit:
      average: 100  # requests per second
      burst: 200
```

---

## Appendix: Configuration Examples

### Complete OAuth2 Proxy Environment

```yaml
oauth2-proxy:
  environment:
    # Provider
    - OAUTH2_PROXY_PROVIDER=oidc
    - OAUTH2_PROXY_OIDC_ISSUER_URL=https://shml-platform.tail38b60a.ts.net
    - OAUTH2_PROXY_CLIENT_ID=${OAUTH2_CLIENT_ID}
    - OAUTH2_PROXY_CLIENT_SECRET=${OAUTH2_CLIENT_SECRET}
    
    # Paths
    - OAUTH2_PROXY_PROXY_PREFIX=/oauth2-proxy
    - OAUTH2_PROXY_REDIRECT_URL=https://shml-platform.tail38b60a.ts.net/oauth2-proxy/callback
    
    # Cookies
    - OAUTH2_PROXY_COOKIE_NAME=_oauth2_proxy
    - OAUTH2_PROXY_COOKIE_SECRET=${OAUTH2_COOKIE_SECRET}
    - OAUTH2_PROXY_COOKIE_SECURE=true
    - OAUTH2_PROXY_COOKIE_HTTPONLY=true
    - OAUTH2_PROXY_COOKIE_SAMESITE=lax
    - OAUTH2_PROXY_COOKIE_REFRESH=1h
    - OAUTH2_PROXY_COOKIE_EXPIRE=720h
    
    # Scopes
    - OAUTH2_PROXY_SCOPE=openid profile email groups
    
    # Headers
    - OAUTH2_PROXY_SET_XAUTHREQUEST=true
    - OAUTH2_PROXY_PASS_ACCESS_TOKEN=true
    - OAUTH2_PROXY_PASS_USER_HEADERS=true
    
    # Upstream
    - OAUTH2_PROXY_UPSTREAMS=static://200
    - OAUTH2_PROXY_HTTP_ADDRESS=0.0.0.0:4180
```

### Complete FusionAuth Application Config

```json
{
  "application": {
    "name": "OAuth2-Proxy",
    "oauthConfiguration": {
      "authorizedRedirectURLs": [
        "http://localhost/oauth2-proxy/callback",
        "https://shml-platform.tail38b60a.ts.net/oauth2-proxy/callback"
      ],
      "clientId": "${OAUTH2_CLIENT_ID}",
      "clientSecret": "${OAUTH2_CLIENT_SECRET}",
      "enabledGrants": [
        "authorization_code",
        "refresh_token"
      ],
      "generateRefreshTokens": true,
      "logoutURL": "http://localhost/",
      "requireClientAuthentication": true
    },
    "jwtConfiguration": {
      "enabled": true,
      "timeToLiveInSeconds": 3600
    },
    "refreshTokenTimeToLiveInMinutes": 43200
  }
}
```

---

**Document Version:** 1.0.0  
**Last Updated:** 2025-12-05  
**Maintained By:** Platform Team
