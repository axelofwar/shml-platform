# Session Management Best Practices - ML Platform
**Last Updated:** 2025-12-06

## 🎯 Current Problem

Users are experiencing frequent re-authentication prompts because:
1. **Short session duration** - OAuth2-Proxy default cookie lifetime is too short
2. **No session persistence** - Cookie-only sessions don't survive browser restarts
3. **Per-service authentication** - Each service behind OAuth2-Proxy validates separately
4. **No SSO (Single Sign-On)** - FusionAuth identity provider disabled for OAuth2-Proxy

---

## 🏆 SOTA Session Management Approach

### Industry Best Practices (2025)

| Approach | Session Duration | Refresh Strategy | Security Level | User Experience |
|----------|------------------|------------------|----------------|-----------------|
| **Short-lived + Refresh Tokens** | 1 hour access + 30 days refresh | Auto-refresh before expiry | ⭐⭐⭐⭐⭐ High | ⭐⭐⭐⭐⭐ Excellent |
| **Medium-lived Sessions** | 8-24 hours | Re-auth on expiry | ⭐⭐⭐⭐ Good | ⭐⭐⭐⭐ Good |
| **Long-lived Sessions** | 30 days | Re-auth on expiry | ⭐⭐ Risky | ⭐⭐⭐⭐⭐ Excellent |
| **Remember Me** | 90 days | Re-auth on expiry | ⭐⭐⭐ Moderate | ⭐⭐⭐⭐⭐ Excellent |

### Recommended: **Short-lived Access + Refresh Tokens**

This is the **SOTA approach** used by:
- Google Workspace (1hr access, 7-30 day refresh)
- GitHub (1hr access, 6 months refresh)
- AWS Cognito (1hr access, 30 day refresh)
- Azure AD (1hr access, 90 day refresh)

**How it works:**
```
1. User signs in → Gets access token (1hr) + refresh token (30 days)
2. OAuth2-Proxy uses access token for authentication
3. Before access token expires → OAuth2-Proxy auto-refreshes via refresh token
4. User never sees re-authentication (seamless)
5. After 30 days of inactivity → User must sign in again
```

---

## 🔧 Recommended Configuration

### Role-Based Session Durations

Different roles have different security requirements:

```yaml
# Viewer Role (Read-only, lowest risk)
Access Token: 8 hours
Refresh Token: 30 days
Remember Me: Yes (90 days)
Rationale: Low security risk, prioritize UX

# Developer Role (Code access, moderate risk)
Access Token: 4 hours
Refresh Token: 14 days
Remember Me: Yes (30 days)
Rationale: Balance security and productivity

# Admin Role (Full control, highest risk)
Access Token: 1 hour
Refresh Token: 7 days
Remember Me: No
MFA Required: Yes
Rationale: High security, short sessions, require MFA
```

### OAuth2-Proxy Configuration

Add these environment variables to `docker-compose.infra.yml`:

```yaml
# SESSION DURATION CONFIGURATION
# Access token lifetime (how long until OAuth2-Proxy checks with FusionAuth again)
OAUTH2_PROXY_COOKIE_EXPIRE: "8h"  # 8 hours for viewer/developer
OAUTH2_PROXY_COOKIE_REFRESH: "4h" # Refresh at 4 hours (before expiry)

# Refresh token configuration (auto-refresh without user interaction)
OAUTH2_PROXY_REFRESH_TOKEN: "true"
OAUTH2_PROXY_REFRESH_TOKEN_EXPIRE: "720h"  # 30 days

# Cookie persistence (survive browser restart)
OAUTH2_PROXY_COOKIE_HTTPONLY: "true"
OAUTH2_PROXY_COOKIE_SAMESITE: "lax"

# Session store (use Redis for persistence across container restarts)
OAUTH2_PROXY_SESSION_STORE_TYPE: "redis"
OAUTH2_PROXY_REDIS_CONNECTION_URL: "redis://redis:6379"

# Grace period before forcing re-auth
OAUTH2_PROXY_GRACE_PERIOD: "5m"

# Skip auth for static assets (improve performance)
OAUTH2_PROXY_SKIP_AUTH_REGEX: "^/assets/.*$"
```

### FusionAuth JWT Configuration

In FusionAuth Admin → Tenants → Default → JWT tab:

```json
{
  "JWT duration": 3600,           // 1 hour (14400 for 4hr, 28800 for 8hr)
  "Refresh token duration": 43200, // 30 days in minutes
  "Refresh token usage": "Reusable",
  "Refresh token revocation": {
    "onPasswordChange": true,
    "onLoginPrevention": true
  }
}
```

---

## 🔒 FusionAuth Identity Provider - Enable or Disable?

### Current State (From Screenshot)
- ✅ Google: Enabled, Create Registration: ON
- ✅ OAuth2-Proxy: Enabled, Create Registration: ON
- ❌ **FusionAuth: DISABLED** ← This is the issue!

### Why Enable FusionAuth Provider?

The "FusionAuth" identity provider entry refers to **FusionAuth's native email/password login**. When disabled:

**❌ Problems:**
1. Users **cannot** create accounts with email/password
2. Users **cannot** sign in with email/password
3. **Only social logins work** (Google, GitHub, Twitter)
4. **Admin must manually create users** in FusionAuth admin panel
5. No self-service password reset

**✅ Benefits of Enabling:**
1. **Self-service registration** - Users can create accounts without admin
2. **Email/password login** - Doesn't require social accounts
3. **Password reset flows** - Users can recover access
4. **Admin can provision accounts** - Create users for contractors/employees
5. **Better for enterprise** - Not everyone wants to use Google/GitHub at work

### Security Analysis by Role

#### Viewer Role
**Risk:** Low (read-only access)
**Recommendation:** ✅ Enable FusionAuth, allow self-registration
```yaml
Rationale:
- Viewers only access dashboards (Homer, Grafana)
- No code execution or data modification
- Self-service reduces admin overhead
- Can revoke access easily in FusionAuth admin
```

#### Developer Role
**Risk:** Moderate (code execution, MLflow write)
**Recommendation:** ✅ Enable FusionAuth, admin-approval required
```yaml
Rationale:
- Requires admin approval before role upgrade from viewer
- Email/password provides audit trail (vs social OAuth)
- Can enforce password complexity policies
- Better for corporate environments
```

#### Admin Role
**Risk:** High (full platform control)
**Recommendation:** ✅ Enable FusionAuth + MFA required
```yaml
Rationale:
- Require email/password + MFA (TOTP or hardware key)
- Social OAuth alone is risky (account compromise = platform compromise)
- FusionAuth provides MFA, IP allowlisting, login anomaly detection
- Better audit logs for compliance
```

---

## 🎯 Recommended Configuration

### 1. Enable FusionAuth Identity Provider

**In FusionAuth Admin:**
```
Settings → Identity Providers → FusionAuth → Edit
├── Enabled: ✅ (turn ON)
├── Applications tab:
│   └── OAuth2-Proxy:
│       ├── Enabled: ✅
│       └── Create registration: ✅ (auto-assign viewer role)
└── Save
```

### 2. Configure Session Durations

**Update `docker-compose.infra.yml`:**
```yaml
services:
  oauth2-proxy:
    environment:
      # ENHANCED SESSION MANAGEMENT
      # Base session duration (8 hours for good UX)
      OAUTH2_PROXY_COOKIE_EXPIRE: "8h"

      # Refresh tokens for seamless re-authentication
      OAUTH2_PROXY_REFRESH_TOKEN: "true"
      OAUTH2_PROXY_COOKIE_REFRESH: "4h"  # Refresh at 50% lifetime

      # Persist sessions across browser restarts
      OAUTH2_PROXY_SESSION_STORE_TYPE: "redis"
      OAUTH2_PROXY_REDIS_CONNECTION_URL: "redis://redis:6379"

      # Cookie security
      OAUTH2_PROXY_COOKIE_HTTPONLY: "true"
      OAUTH2_PROXY_COOKIE_SECURE: "true"
      OAUTH2_PROXY_COOKIE_SAMESITE: "lax"
```

### 3. Configure FusionAuth Refresh Tokens

**In FusionAuth Admin → Tenants → Default → JWT tab:**
```
JWT duration: 28800 seconds (8 hours)
Refresh token duration: 43200 minutes (30 days)
Refresh token usage: Reusable
Refresh token revocation policy:
  ✅ On password change
  ✅ On account lock
  ✅ On manual revocation
```

### 4. Role-Specific MFA

**For Admin Role (in FusionAuth):**
```
Applications → OAuth2-Proxy → Edit → Security tab:
├── Multi-Factor:
│   ├── Require for admin role: ✅ (TOTP or hardware key)
│   └── Require for elevated-developer: ✅
└── Login Policy:
    ├── Failed login attempts: 5
    └── Account lockout: 15 minutes
```

---

## 🚀 Implementation Steps

### Step 1: Enable FusionAuth Identity Provider

1. **Go to FusionAuth Admin:**
   ```
   https://shml-platform.tail38b60a.ts.net/admin
   ```

2. **Navigate to Identity Providers:**
   ```
   Settings → Identity Providers → FusionAuth row → Edit (pencil icon)
   ```

3. **Enable the provider:**
   ```
   Enabled toggle: ON (blue)
   ```

4. **Configure OAuth2-Proxy application:**
   ```
   Click "Applications" tab
   Find "OAuth2-Proxy" in list
   ✅ Enabled: checked
   ✅ Create registration: checked
   ```

5. **Save configuration**

### Step 2: Update OAuth2-Proxy Session Config

```bash
# Edit docker-compose.infra.yml
vim docker-compose.infra.yml

# Add session configuration (after line 316, OAUTH2_PROXY_COOKIE_NAME)
```

Add this configuration block:

```yaml
      # ===================================================================
      # ENHANCED SESSION MANAGEMENT (Added 2025-12-06)
      # ===================================================================
      # Access token lifetime - how long before re-checking with FusionAuth
      # Viewer/Developer: 8 hours (28800s) - good balance of security and UX
      # Admin: Use shorter duration (4 hours) via role-specific configuration
      OAUTH2_PROXY_COOKIE_EXPIRE: "8h"

      # Cookie refresh - auto-refresh tokens before expiry (seamless UX)
      # Refresh at 50% of cookie lifetime to prevent expiration
      OAUTH2_PROXY_COOKIE_REFRESH: "4h"

      # Enable refresh tokens for transparent re-authentication
      # OAuth2-Proxy will use refresh token to get new access token
      # User never sees re-login prompt (unless refresh token expires)
      OAUTH2_PROXY_REFRESH_TOKEN: "true"

      # Session persistence - use Redis instead of cookie-only storage
      # Benefits:
      # - Sessions survive browser restart
      # - Sessions survive OAuth2-Proxy container restart
      # - Centralized session management for multiple OAuth2-Proxy instances
      # - Can revoke sessions centrally via Redis
      OAUTH2_PROXY_SESSION_STORE_TYPE: "redis"
      OAUTH2_PROXY_REDIS_CONNECTION_URL: "redis://redis:6379"

      # Cookie security settings
      OAUTH2_PROXY_COOKIE_HTTPONLY: "true"  # Prevent JavaScript access
      OAUTH2_PROXY_COOKIE_SAMESITE: "lax"    # CSRF protection

      # Grace period before hard logout (allows brief network issues)
      # If FusionAuth is temporarily unreachable, user stays logged in
      OAUTH2_PROXY_GRACE_PERIOD: "5m"

      # Skip authentication for static assets (performance optimization)
      # Reduces load on OAuth2-Proxy and FusionAuth
      OAUTH2_PROXY_SKIP_AUTH_REGEX: "^/(assets|static|favicon\\.ico|robots\\.txt).*$"
```

### Step 3: Update FusionAuth JWT Settings

1. **Go to FusionAuth Admin:**
   ```
   Tenants → Default → Edit
   ```

2. **Click "JWT" tab**

3. **Update these settings:**
   ```
   JWT duration: 28800 (8 hours in seconds)

   Scroll to "Refresh token settings":
   Duration: 43200 (30 days in minutes)
   Usage policy: Reusable (allows multiple refreshes)

   Revocation policy:
   ✅ On action preventing login
   ✅ On password change
   ✅ On multi-factor disable (if using MFA)
   ```

4. **Save**

### Step 4: Restart OAuth2-Proxy

```bash
cd /home/axelofwar/Projects/shml-platform
docker compose --env-file .env -f docker-compose.infra.yml up -d --force-recreate oauth2-proxy
```

### Step 5: Test Session Persistence

**Test 1: Browser Restart**
```
1. Sign in to https://shml-platform.tail38b60a.ts.net/
2. Close browser completely
3. Reopen browser
4. Go to https://shml-platform.tail38b60a.ts.net/
5. ✅ Should NOT prompt for login (session persists)
```

**Test 2: Cross-Service Navigation**
```
1. Sign in to Homer (https://shml-platform.tail38b60a.ts.net/)
2. Click link to Grafana
3. ✅ Should NOT prompt for login (SSO works)
4. Click link to MLflow
5. ✅ Should NOT prompt for login (SSO works)
```

**Test 3: Session Duration**
```
1. Sign in
2. Wait 4 hours
3. Access any service
4. ✅ Should auto-refresh token (no login prompt)
5. Wait 30+ days without activity
6. ✅ Should prompt for re-authentication (refresh token expired)
```

---

## 📊 Comparison: Current vs. Recommended

| Aspect | Current | Recommended | Improvement |
|--------|---------|-------------|-------------|
| **Session Duration** | ~1 hour | 8 hours (auto-refresh) | ⬆️ 8x longer |
| **Browser Restart** | Must re-login | Session persists | ⬆️ Much better UX |
| **Refresh Tokens** | Not configured | Auto-refresh at 4hr | ⬆️ Seamless UX |
| **Session Store** | Cookie-only | Redis (persistent) | ⬆️ Survives restarts |
| **Email/Password Login** | ❌ Disabled | ✅ Enabled | ⬆️ Self-service |
| **Cross-Service SSO** | Works | Works better | ⬆️ Faster |
| **Security** | Moderate | High (MFA for admin) | ⬆️ Better audit |

---

## 🛡️ Security Considerations

### Mitigations for Longer Sessions

**1. Token Revocation**
```yaml
# In Redis, store active sessions
# On user logout, delete session from Redis
# On admin revoke, delete all user sessions
```

**2. IP-Based Validation**
```yaml
# Optional: Store IP address with session
# If IP changes dramatically (different country), force re-auth
OAUTH2_PROXY_PASS_ACCESS_TOKEN: "true"  # For IP logging
```

**3. Device Fingerprinting**
```yaml
# Optional: Track user-agent changes
# If device changes, force re-auth for admin role
```

**4. Audit Logging**
```yaml
# Log all authentication events to FusionAuth
# Monitor for anomalies (login from new location, etc.)
```

**5. Role-Specific Policies**
```
Viewer: 8hr session, 30 day refresh, no MFA required
Developer: 4hr session, 14 day refresh, MFA recommended
Admin: 1hr session, 7 day refresh, MFA required
```

---

## 🎯 Summary: Enable FusionAuth + Enhanced Sessions

**Immediate Actions:**

1. ✅ **Enable FusionAuth identity provider** in admin UI
   - Allows email/password login
   - Enables self-service registration
   - Better for enterprise/contractor access

2. ✅ **Add session configuration** to OAuth2-Proxy
   - 8 hour sessions with auto-refresh
   - Redis session store (survives restarts)
   - 30 day refresh tokens (seamless UX)

3. ✅ **Configure FusionAuth JWT settings**
   - 8 hour access tokens
   - 30 day refresh tokens
   - Revocation policies

4. ✅ **Test all authentication methods**
   - Google OAuth (already working)
   - GitHub OAuth (verify createRegistration)
   - Twitter OAuth (verify createRegistration)
   - Email/Password (after enabling FusionAuth provider)

**Result:** Users sign in once, stay authenticated for 30 days of activity, seamless cross-service navigation, no constant re-login prompts!
