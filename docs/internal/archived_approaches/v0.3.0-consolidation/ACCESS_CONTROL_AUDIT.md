# SHML Platform - Complete Access Control & Authentication Audit
**Generated:** 2025-12-06  
**Platform:** SHML ML Platform  
**Total Services:** 17 services

---

## 📊 SERVICE ACCESS MATRIX

| Service | Path | Viewer | Developer | Elevated-Dev | Admin |
|---------|------|--------|-----------|--------------|-------|
| **Homer Dashboard** | `/` | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| **Grafana** | `/grafana` | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| **Inference Gateway** | `/inference` | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| **Qwen3-VL (LLM)** | `/api/llm` | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| **Z-Image (Image Gen)** | `/api/image` | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| **MLflow** | `/mlflow` | ❌ No | ✅ Yes | ✅ Yes | ✅ Yes |
| **Ray Dashboard** | `/ray` | ❌ No | ✅ Yes | ✅ Yes | ✅ Yes |
| **Ray Compute API** | `/api/ray` | ❌ No | ✅ Yes | ✅ Yes | ✅ Yes |
| **Chat UI** | `/chat-ui` | ❌ No | ✅ Yes | ✅ Yes | ✅ Yes |
| **Dozzle (Logs)** | `/logs` | ❌ No | ✅ Yes | ✅ Yes | ✅ Yes |
| **Prometheus** | `/prometheus` | ❌ No | ❌ No | ❌ No | ✅ Yes |
| **Traefik Dashboard** | `/traefik` | ❌ No | ❌ No | ❌ No | ✅ Yes |
| **Infisical (Secrets)** | `/secrets` | ❌ No | ❌ No | ❌ No | ✅ Yes |
| **FusionAuth Admin** | `/admin` | ⚠️ NO AUTH | ⚠️ NO AUTH | ⚠️ NO AUTH | ⚠️ NO AUTH |

---

## 🔐 MIDDLEWARE CONFIGURATION

### Viewer Role (Default for New Users)
**Middleware:** `oauth2-errors,oauth2-auth`  
**Access:**
- ✅ Homer Dashboard (homepage)
- ✅ Grafana (monitoring dashboards)
- ✅ Inference Gateway (chat history, queue status)
- ✅ Qwen3-VL API (LLM chat completions)
- ✅ Z-Image API (image generation)

### Developer Role
**Middleware:** `oauth2-errors,oauth2-auth,role-auth-developer`  
**Access:** All viewer services PLUS:
- ✅ MLflow (experiment tracking)
- ✅ Ray Dashboard (cluster monitoring)
- ✅ Ray Compute API (job submission)
- ✅ Chat UI (advanced chat interface)
- ✅ Dozzle (container logs)

### Elevated-Developer Role
**Middleware:** `oauth2-errors,oauth2-auth,role-auth-elevated`  
**Access:** All developer services PLUS:
- ✅ (Currently no unique services, inherits developer + admin capabilities)

### Admin Role
**Middleware:** `oauth2-errors,oauth2-auth,role-auth-admin`  
**Access:** All services PLUS:
- ✅ Prometheus (metrics database)
- ✅ Traefik Dashboard (reverse proxy config)
- ✅ Infisical (secrets management)

---

## 🚪 AUTHENTICATION FLOWS

### Flow 1: New User Self-Registration (Email/Password)
```
1. User visits https://shml-platform.tail38b60a.ts.net/
2. OAuth2-Proxy intercepts (no session) → Redirects to FusionAuth
3. FusionAuth shows unified login page with:
   - Email field
   - Password field
   - "Create an account" link ← USER CLICKS HERE
   - Social login buttons (Google, GitHub, Twitter)
4. User clicks "Create an account"
5. FusionAuth registration form:
   - Email (required)
   - Password (required)
   - First Name (required)
   - Last Name (required)
   - Birth Date, Mobile Phone, etc. (optional)
6. User submits form
7. FusionAuth creates user with:
   - Email verified: true (no verification required)
   - Registration verified: true (auto-verified)
   - Default role: viewer
8. FusionAuth redirects to OAuth2-Proxy callback
9. OAuth2-Proxy creates session (8hr expiry, Redis stored)
10. User lands on Homer Dashboard ✅
```

### Flow 2: New User Social OAuth (Google/GitHub/Twitter)
```
1. User visits https://shml-platform.tail38b60a.ts.net/
2. OAuth2-Proxy intercepts → Redirects to FusionAuth
3. FusionAuth shows unified login page
4. User clicks "Sign in with Google" (or GitHub/Twitter)
5. Redirected to OAuth provider (Google/GitHub/Twitter)
6. User authorizes application
7. OAuth provider redirects back to FusionAuth with authorization code
8. FusionAuth:
   - Checks if user exists by email
   - If NOT exists → Creates user automatically (createRegistration: true)
   - Assigns default role: viewer
   - Email verified: true
   - Registration verified: true
9. FusionAuth redirects to OAuth2-Proxy callback
10. OAuth2-Proxy creates session
11. User lands on Homer Dashboard ✅
```

### Flow 3: Existing User Login (Email/Password)
```
1. User visits https://shml-platform.tail38b60a.ts.net/
2. OAuth2-Proxy intercepts → Redirects to FusionAuth
3. FusionAuth shows SAME unified login page
   (NOT a separate page for existing users)
4. User enters email + password
5. FusionAuth authenticates:
   - Checks credentials
   - Retrieves user's roles (viewer/developer/admin)
   - Generates JWT with roles claim
6. FusionAuth redirects to OAuth2-Proxy callback
7. OAuth2-Proxy validates JWT, extracts roles
8. OAuth2-Proxy creates session with user email + roles
9. User lands on Homer Dashboard ✅
```

### Flow 4: Existing User Social OAuth
```
1. User visits https://shml-platform.tail38b60a.ts.net/
2. OAuth2-Proxy intercepts → Redirects to FusionAuth
3. FusionAuth shows unified login page
4. User clicks "Sign in with Google" (or GitHub/Twitter)
5. Redirected to OAuth provider
6. User authorizes (may auto-authorize if previously granted)
7. OAuth provider returns to FusionAuth
8. FusionAuth:
   - Recognizes existing user by email
   - Does NOT create duplicate account
   - Retrieves existing roles
   - Generates JWT with roles
9. OAuth2-Proxy validates JWT
10. User lands on Homer Dashboard ✅
```

---

## ✅ UNIFIED LOGIN PAGE BEHAVIOR

**CRITICAL:** FusionAuth uses a **single unified login page** for ALL users:

```
┌─────────────────────────────────────────┐
│  ML Platform - Sign In                  │
├─────────────────────────────────────────┤
│                                         │
│  Email:    [________________]           │
│  Password: [________________]           │
│                                         │
│  [ Sign In ]                            │
│                                         │
│  ─────────── OR ───────────            │
│                                         │
│  [ 🔵 Sign in with Google ]            │
│  [ ⚫ Sign in with GitHub ]            │
│  [ 🔷 Sign in with Twitter ]           │
│                                         │
│  Don't have an account?                 │
│  [ Create an account ]  ← NEW USERS    │
│                                         │
└─────────────────────────────────────────┘
```

**There is NO separate page or redirect for existing vs. new users.**

- **New users:** See this page → Click "Create an account"
- **Existing users:** See this page → Enter credentials OR use social login
- **FusionAuth handles the logic internally** (checks if email exists)

This is **standard OAuth/OIDC behavior** and matches industry practices (Google, GitHub, Auth0, etc.)

---

## ⚠️ SECURITY ISSUES IDENTIFIED

### 1. FusionAuth Admin - NO AUTHENTICATION ❌
**Current Configuration:**
```yaml
traefik.http.routers.fusionauth-admin.middlewares=fusionauth-headers
```

**Issue:** FusionAuth admin interface (`/admin`) has NO OAuth protection.  
**Risk:** Anyone can access user management, application settings, API keys.

**Recommendation:** Add role-based auth:
```yaml
traefik.http.routers.fusionauth-admin.middlewares=oauth2-errors,oauth2-auth,role-auth-admin
```

### 2. FusionAuth Public Endpoints - Intentionally Unprotected ⚠️
**Endpoints:**
- `/auth` - Login/OAuth pages
- `/oauth2` - OAuth endpoints
- `/registration` - Registration forms
- `/password` - Password reset
- `/css`, `/js`, `/images`, `/fonts` - Static assets

**Status:** These MUST remain public for authentication to work.  
**Current:** Correctly configured with `fusionauth-headers` only.

---

## 📋 ROLE ASSIGNMENT PROCESS

### Default Role Assignment (Automatic)
```yaml
roles:
  - viewer (isDefault: true)  ← New users get this automatically
  - developer (isDefault: false)
  - elevated-developer (isDefault: false)
  - admin (isDefault: false)
```

### Manual Role Promotion (Admin Only)
**Via FusionAuth Admin UI:**
```
1. Login to FusionAuth Admin: /admin
2. Navigate to: Users → [Select User]
3. Click: Registrations tab
4. Find: OAuth2-Proxy application
5. Check additional roles: developer, admin
6. Click: Save
```

**User gets new roles on next login** (JWT refresh).

---

## 🔄 SESSION MANAGEMENT

| Setting | Value | Description |
|---------|-------|-------------|
| **Session Duration** | 8 hours | Access token lifetime |
| **Auto-Refresh** | 4 hours | Token refreshed at 50% lifetime |
| **Refresh Token** | 30 days | Long-lived refresh token |
| **Session Store** | Redis | Persistent across browser restarts |
| **Cookie Security** | HTTPOnly, SameSite=Lax, Secure | XSS/CSRF protection |

---

## 📊 CURRENT USER STATUS

| Email | Roles | Email Verified | Registration Verified | Access |
|-------|-------|----------------|----------------------|--------|
| axelofwar.web3@gmail.com | admin, developer, viewer | ✅ | ✅ | All services |
| bnccyberspace@msn.com | developer, viewer | ✅ | ✅ | Developer + viewer services |
| soundsbystoney@gmail.com | viewer | ✅ | ✅ | Viewer services only |
| william.caton@gmail.com | developer, viewer | ✅ | ✅ | Developer + viewer services |

**All users fully verified and operational.**

---

## ✨ SUMMARY

### ✅ What's Working Correctly
1. **Self-service registration** enabled with viewer as default role
2. **Social OAuth** providers (Google, GitHub, Twitter) auto-create users
3. **Unified login page** serves both new and existing users
4. **Role-based access control** enforced via Traefik middleware
5. **Session management** with 8hr sessions, Redis persistence, auto-refresh
6. **Viewer services** (Homer, Grafana, Inference) accessible to all users
7. **Developer services** (MLflow, Ray, Chat UI) properly protected
8. **Admin services** (Prometheus, Traefik, Infisical) admin-only

### ⚠️ Security Recommendations
1. **Add OAuth protection to FusionAuth Admin** (`/admin` endpoint)
2. **Review Infisical access** - Ensure admin role is sufficient
3. **Monitor JWT lambda** - Ensure roles are always included in tokens
4. **Regular user audits** - Run `./scripts/user_verification_report.sh`

### 🎯 User Experience
- **New users:** Can self-register → get viewer role → access Homer & Grafana immediately
- **Existing users:** See same login page → login → access services based on assigned roles
- **No confusion:** One page, clear options for both new and existing users
- **Role promotion:** Admins manually upgrade users from viewer → developer/admin

---

## 🔧 ISSUE RESOLUTION LOG

### 2025-12-06: Grafana SSO Failure - Login Failed After OAuth Authentication

**Problem:**
- User Kay Rodgers successfully authenticated via OAuth2-Proxy to access Homer
- When clicking to Grafana, received "Login failed" error
- HTML/CSS content shown instead of proper Grafana page
- Session already valid but Grafana tried to start its own OAuth flow

**Root Cause:**
Grafana had **dual authentication configuration**:
1. OAuth2-Proxy handling auth at Traefik layer (working)
2. Grafana's built-in Generic OAuth trying to auth directly with FusionAuth (conflicting)

This created a race condition where:
- OAuth2-Proxy authenticated user successfully
- Grafana ignored OAuth2-Proxy headers
- Grafana redirected to FusionAuth for login
- User already had valid session but Grafana couldn't complete its own OAuth flow
- Result: "Login failed" with HTML error response

**Solution:**
Switched Grafana from **Generic OAuth mode** to **Auth Proxy mode**:

```yaml
# BEFORE (conflicting dual auth):
GF_AUTH_GENERIC_OAUTH_ENABLED: "true"
GF_AUTH_GENERIC_OAUTH_AUTH_URL: "https://.../oauth2/authorize"
# ... 15+ OAuth settings

# AFTER (auth proxy mode):
GF_AUTH_PROXY_ENABLED: "true"
GF_AUTH_PROXY_HEADER_NAME: "X-Auth-Request-Email"
GF_AUTH_PROXY_HEADER_PROPERTY: "email"
GF_AUTH_PROXY_AUTO_SIGN_UP: "true"
GF_AUTH_PROXY_WHITELIST: "172.16.0.0/12,192.168.0.0/16,127.0.0.1"
GF_AUTH_PROXY_HEADERS: "Name:X-Auth-Request-User Email:X-Auth-Request-Email"
```

**How Auth Proxy Mode Works:**
1. User clicks Homer → Grafana
2. OAuth2-Proxy intercepts request at Traefik layer
3. OAuth2-Proxy validates session (already exists from Homer login)
4. OAuth2-Proxy forwards request with headers:
   - `X-Auth-Request-Email`: user's email
   - `X-Auth-Request-User`: user's display name
   - `X-Auth-Request-Groups`: comma-separated roles
5. Grafana trusts these headers (from whitelist IPs)
6. Grafana auto-creates/logs in user based on email header
7. User sees Grafana dashboard immediately (no second login)

**Benefits:**
- ✅ Single Sign-On (SSO) working correctly
- ✅ No duplicate authentication flows
- ✅ Seamless navigation: Homer → Grafana → MLflow (all same session)
- ✅ User only logs in once to access all platform services
- ✅ Roles automatically synced from FusionAuth via OAuth2-Proxy headers

**Testing:**
```bash
# Verify auth proxy configuration
docker exec unified-grafana env | grep GF_AUTH_PROXY

# Should show:
# GF_AUTH_PROXY_ENABLED=true
# GF_AUTH_PROXY_HEADER_NAME=X-Auth-Request-Email
# GF_AUTH_PROXY_AUTO_SIGN_UP=true

# Test health endpoint
docker exec unified-grafana wget -q -O- http://localhost:3000/grafana/api/health
# Should return: {"database":"ok","version":"10.2.2",...}
```

**Files Modified:**
- `/home/axelofwar/Projects/shml-platform/docker-compose.infra.yml`
  - Removed `GF_AUTH_GENERIC_OAUTH_*` variables (17 lines)
  - Added `GF_AUTH_PROXY_*` variables (8 lines)
  - Container recreated with `--force-recreate` flag

**Status:** ✅ **RESOLVED** - Grafana now uses centralized OAuth2-Proxy authentication

---

**Report Generated:** 2025-12-06  
**Last Updated:** 2025-12-06 (Grafana SSO fix)  
**Platform Version:** 0.1.0  
**Services Audited:** 17  
**Authentication:** FusionAuth + OAuth2-Proxy  
**Authorization:** Traefik ForwardAuth + role-auth middleware
