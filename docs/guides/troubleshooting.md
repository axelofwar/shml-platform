# Troubleshooting Guide

**Last Updated:** 2025-12-05

---

## ⚠️ IMPORTANT: Service Management

**Always use `./start_all_safe.sh` for starting services!**

Do NOT use `docker compose up` directly - it will fail due to network/volume dependencies between services.

```bash
# Correct way to start services
./start_all_safe.sh                   # Full restart (recommended)
./start_all_safe.sh start mlflow      # Start MLflow only
./start_all_safe.sh start ray         # Start Ray only
./start_all_safe.sh start inference   # Start coding models + chat

# Correct way to stop services
./start_all_safe.sh stop              # Stop all
./start_all_safe.sh stop mlflow       # Stop MLflow only

# Check status
./start_all_safe.sh status
./check_platform_status.sh
```

---

## Quick Diagnostics

```bash
# Check all services
docker ps

# Check network
docker network inspect shml-platform

# Check logs
docker logs <container> --tail 50

# Health checks
curl http://localhost/mlflow/ | grep MLflow
curl http://localhost:8090/ping  # Traefik
```

---

## Authentication & OAuth Issues

### OAuth Redirect Loop - Users Keep Redirected to Sign-In Page

**Symptoms:**
- Users sign in with Google successfully but keep getting sent back to "Sign in with OpenID Connect" page
- Infinite redirect loop, never reaching Homer/Grafana/MLflow
- OAuth2-Proxy logs show `202` responses for `/oauth2-proxy/auth`
- Users have roles assigned in FusionAuth but still can't access services
- No error messages visible to user

**Root Cause:**
FusionAuth is NOT including the `roles` claim in the JWT `id_token`. Even if users have roles assigned in FusionAuth, the JWT doesn't contain them without a **JWT Populate Lambda**.

This results in:
1. User authenticates successfully ✓
2. FusionAuth issues JWT **without roles claim**
3. OAuth2-Proxy reads `roles` claim (via `OAUTH2_PROXY_OIDC_GROUPS_CLAIM`) → finds nothing
4. OAuth2-Proxy passes empty `X-Auth-Request-Groups` header to services
5. If `OAUTH2_PROXY_ALLOWED_GROUPS` is enabled → OAuth2-Proxy rejects request
6. Traefik redirects back to sign-in → infinite loop

**Quick Diagnosis:**
```bash
# 1. Verify user HAS roles in FusionAuth
open https://shml-platform.tail38b60a.ts.net/admin
# Users → [user] → Registrations → OAuth2-Proxy → should show "viewer" checked

# 2. Check if JWT contains roles claim
# Have user sign in, then in browser:
# DevTools → Application → Cookies → _sfml_oauth2 (copy value)
# Go to https://jwt.io and paste JWT
# Look for "roles": [...] in payload
# If MISSING → JWT Populate lambda not configured

# 3. Check OAuth2-Proxy logs
docker logs oauth2-proxy --tail 50 | grep "user@example.com"
# Should show 202 with roles in request

# 4. Check FusionAuth Event Log
# Admin → System → Event Log
# Filter by: Debug or Information
# Look for: "Added roles to JWT for user..."
# If NOT FOUND → Lambda not attached or not executing
```

**Solution: Configure JWT Populate Lambda**

FusionAuth needs a lambda to include roles in the JWT token:

1. **Create the JWT Populate Lambda:**
   ```
   FusionAuth Admin → Settings → Lambdas → ➕ Add Lambda

   Name: JWT Populate - Include Roles Claim
   Type: JWT populate
   Enabled: ✓ (checked)
   Debug: ✓ (checked, for setup)

   Copy code from: fusionauth/lambdas/jwt-populate-roles.js

   Click: Save
   ```

2. **Attach Lambda to Tenant:**
   ```
   FusionAuth Admin → Tenants → ML Platform → Edit (pencil icon)

   Scroll down to "JWT" section

   Id Token populate lambda: ▼ Select "JWT Populate - Include Roles Claim"

   Click: Save (💾 icon at top right)
   ```

3. **Verify Lambda Execution:**
   ```bash
   # Check Event Log
   FusionAuth Admin → System → Event Log

   # Should see (after user signs in):
   # "Added roles to JWT for user user@example.com: viewer"
   ```

4. **Force Users to Get New Tokens:**
   ```bash
   # Option 1: Users clear cookies and sign in again
   # Browser → Clear cookies for: shml-platform.tail38b60a.ts.net

   # Option 2: Restart OAuth2-Proxy (invalidates all sessions)
   docker restart oauth2-proxy

   # Users will be asked to sign in again with new JWT
   ```

5. **Verify JWT Contains Roles:**
   ```bash
   # After fresh sign-in:
   # Browser DevTools → Application → Cookies → _sfml_oauth2
   # Copy JWT → Paste at https://jwt.io

   # Should see in payload:
   {
     "email": "user@example.com",
     "roles": ["viewer"],     # ← OAuth2-Proxy reads this
     "role": "viewer",        # ← Backup string format
     ...
   }
   ```

**Verification:**
```bash
# 1. User should be able to access Homer dashboard
open https://shml-platform.tail38b60a.ts.net/

# 2. Check OAuth2-Proxy logs show roles
docker logs oauth2-proxy --tail 20

# 3. Test role-auth middleware (for developer role)
curl -H "X-Auth-Request-Groups: viewer,developer" \
  http://localhost:8080/auth/developer
# Should return: 200 OK "Authorized"

# 4. Check Traefik access logs
docker logs traefik --tail 50
# Should show successful requests without redirects
```

**Related Files:**
- Lambda code: `fusionauth/lambdas/jwt-populate-roles.js` (JWT Populate)
- Lambda docs: `fusionauth/lambdas/README.md` (setup guide)
- OAuth2-Proxy config: `docker-compose.infra.yml` (lines 260-400)
- Role-auth nginx: `scripts/role-auth/nginx.conf`

**Prevention:**
- **ALWAYS configure JWT Populate lambda when setting up FusionAuth**
- Test authentication with a fresh user account before production
- Document lambda configuration in deployment checklist
- Use FusionAuth Event Log to verify lambda execution
- Decode JWT tokens to confirm claims are present

**Common Mistakes:**
- ❌ Creating lambda but not attaching it to tenant
- ❌ Attaching lambda to application instead of tenant
- ❌ Using Google Reconcile lambda instead of JWT Populate lambda
- ❌ Forgetting to enable "Debug" mode in lambda settings
- ❌ Not having users clear cookies after adding lambda
- ❌ Assuming roles in FusionAuth == roles in JWT (they're separate)

---

### OAuth Redirect Loop - AuthenticatedRegistrationNotVerified

**Symptoms:**
- User authenticates successfully with OAuth provider (Google/GitHub/Twitter)
- OAuth2-Proxy logs show: `userState=AuthenticatedRegistrationNotVerified`
- Continuous 401 responses every 4 seconds from `/oauth2-proxy/auth`
- User stuck in infinite redirect loop despite having roles assigned
- JWT contains roles but session is immediately rejected

**Root Cause:**
User's **registration is not verified** in FusionAuth database. Even though:
- User account is verified (`identities.verified = true`) ✓
- JWT Populate lambda is working and adding roles ✓
- Email verification is disabled at tenant level ✓

The registration itself has `user_registrations.verified = false` which causes FusionAuth to add `userState=AuthenticatedRegistrationNotVerified` to the OAuth callback, and OAuth2-Proxy rejects the session.

**Quick Diagnosis:**
```bash
# 1. Check OAuth2-Proxy logs for the specific user
docker logs oauth2-proxy --tail 100 | grep "user@example.com"
# Look for: userState=AuthenticatedRegistrationNotVerified

# 2. Check user's registration verification status
./scripts/user_verification_report.sh
# Look for: Registration Verified = ❌

# 3. Query database directly
docker exec shml-postgres psql -U fusionauth -d fusionauth -c "
SELECT i.email, i.verified as email_verified, ur.verified as registration_verified
FROM identities i
JOIN users u ON i.users_id = u.id
JOIN user_registrations ur ON u.id = ur.users_id
WHERE i.email = 'user@example.com'
  AND ur.applications_id = 'acda34f0-7cf2-40eb-9cba-7cb0048857d3';
"
# If registration_verified = f → User has unverified registration
```

**Solution: Verify User Registrations**

```bash
# Option 1: Verify all users at once (recommended)
./scripts/verify_all_registrations.sh

# Option 2: Verify specific user
./scripts/verify_user_email.sh user@example.com

# Option 3: Manual SQL update (for single user)
docker exec shml-postgres psql -U fusionauth -d fusionauth -c "
UPDATE user_registrations
SET verified = true
WHERE users_id = (SELECT users_id FROM identities WHERE email = 'user@example.com')
  AND applications_id = 'acda34f0-7cf2-40eb-9cba-7cb0048857d3';
"
```

**Post-Fix: Users Must Clear Browser Cookies**

After fixing registration verification, users MUST clear their browser cookies for the platform domain:

```
1. Browser → Settings → Cookies
2. Search for: shml-platform.tail38b60a.ts.net
3. Delete all cookies for this domain
4. Navigate to platform homepage and sign in again

OR use incognito/private browsing mode for testing
```

Old session cookies still contain the `AuthenticatedRegistrationNotVerified` state, so they must be cleared.

**Verification:**
```bash
# 1. Run verification report
./scripts/user_verification_report.sh
# Should show: Registration Verified = ✅ for all users

# 2. Check OAuth2-Proxy logs after user signs in
docker logs oauth2-proxy --tail 50 | grep "user@example.com"
# Should show: [AuthSuccess] ... groups:[viewer]
# Should NOT show: userState=AuthenticatedRegistrationNotVerified

# 3. User should reach Homer dashboard without redirect loop
```

**Prevention:**
```bash
# 1. Disable email verification at tenant level (already done)
FusionAuth Admin → Tenants → Default → Email → Verify Email: OFF

# 2. Disable registration verification at application level (already done)
FusionAuth Admin → Applications → OAuth2-Proxy → Registration → Verify Registration: OFF

# 3. Run verification script after creating new users
./scripts/verify_all_registrations.sh

# 4. Add to user onboarding checklist:
# - Create user in FusionAuth
# - Assign roles to user
# - Run verify_all_registrations.sh
# - Test authentication
```

**Related Files:**
- Verification report: `scripts/user_verification_report.sh`
- Bulk verification: `scripts/verify_all_registrations.sh`
- Single user fix: `scripts/verify_user_email.sh`
- OAuth2-Proxy logs: `docker logs oauth2-proxy`

**Current Status:**
- ✅ Tenant email verification: **DISABLED** (`verifyEmail: false`)
- ✅ Application registration verification: **DISABLED** (`verifyRegistration: false`)
- ✅ All existing users: **VERIFIED** (4/4 users as of 2025-12-06)

**Why This Happens:**
Even with verification disabled at tenant and application levels, FusionAuth may create registrations with `verified = false` when users authenticate via OAuth providers (Google/GitHub/Twitter). This is likely a race condition or default behavior that needs manual cleanup.

---

## MLflow Issues

### Container Won't Start

**Symptoms:**
- Service fails to start
- Containers exit immediately
- Port conflict errors

**Fix:**
```bash
# Check ports
sudo netstat -tulpn | grep -E ':(80|5000|5432)'

# Stop conflicts
sudo systemctl stop nginx apache2 postgresql

# Clean restart using the safe script
./start_all_safe.sh stop mlflow
./start_all_safe.sh start mlflow
```

### Database Connection Failed

**Symptoms:**
- "connection refused"
- "authentication failed"
- UI shows database error

**Fix:**
```bash
# Check PostgreSQL
docker exec shml-postgres pg_isready

# Verify password
cat ml-platform/mlflow-server/secrets/db_password.txt

# Check logs
docker logs mlflow-postgres --tail 50

# Test connection
PGPASSWORD=$(cat ml-platform/mlflow-server/secrets/db_password.txt) \
  psql -h localhost -U mlflow -d mlflow_db -c '\dt'

# Restart if needed
docker restart mlflow-postgres mlflow-server
```

### Can't Access UI

**Symptoms:**
- Browser: "connection refused"
- Timeout errors
- 502/504 errors

**Fix:**
```bash
# Check Traefik
docker logs traefik --tail 50
curl http://localhost:8090/ping

# Check MLflow containers
docker ps --filter "name=mlflow"

# Check routing
curl -v http://localhost/mlflow/

# Check firewall
sudo ufw status | grep 80

# Restart chain
docker restart traefik mlflow-nginx mlflow-server
```

### Large Upload Fails

**Symptoms:**
- 413 Request Entity Too Large
- 504 Gateway Timeout
- Upload hangs

**Fix:**
```bash
# Check Nginx config
docker exec mlflow-nginx grep client_max_body_size /etc/nginx/conf.d/mlflow.conf

# Increase limits (ml-platform/mlflow-server/docker-compose.yml):
# nginx:
#   environment:
#     CLIENT_MAX_BODY_SIZE: 5G
#     PROXY_TIMEOUT: 3600

# Rebuild
cd mlflow-server
docker compose up -d --build nginx
```

### Experiments Not Showing

**Symptoms:**
- Empty UI
- 0 experiments listed
- Old data missing

**Fix:**
```bash
# Check database
docker exec mlflow-postgres psql -U mlflow -d mlflow_db \
  -c "SELECT COUNT(*) FROM experiments;"

# Check MLflow connection
docker logs mlflow-server --tail 50 | grep -i error

# Clear browser cache
# Ctrl+Shift+R in browser

# Restart
docker restart mlflow-server
```

---

## Ray Compute Issues

### Ray Services Not Starting

**Symptoms:**
- Containers exit
- "no such network" error
- Ray dashboard unreachable

**Fix:**
```bash
# Check network exists
docker network inspect ml-platform

# Create if missing
docker network create ml-platform \
  --driver bridge \
  --subnet 172.30.0.0/16

# Start Ray
cd ray_compute
docker compose -f docker-compose.ray.yml up -d

# Check logs
docker logs ray-head --tail 50
```

### GPU Not Available

**Symptoms:**
- "no GPU found"
- CUDA errors
- nvidia-smi fails in container

**Fix:**
```bash
# Check host GPU
nvidia-smi

# Check nvidia-container-toolkit
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi

# Install if missing
sudo apt install -y nvidia-container-toolkit
sudo systemctl restart docker

# Check Ray config (docker-compose.ray.yml):
# ray-head:
#   deploy:
#     resources:
#       reservations:
#         devices:
#           - driver: nvidia
#             count: all
#             capabilities: [gpu]
```

### OAuth Login Failed

**Symptoms:**
- Redirect loop
- "invalid client" error
- Token exchange fails

**Fix:**
```bash
# Check FusionAuth logs
docker logs fusionauth --tail 50

# Verify OAuth application in FusionAuth admin
# URL: http://localhost:9011/admin/ or https://shml-platform.tail38b60a.ts.net/auth/admin/
# Navigate to Applications > Ray Compute > OAuth tab

# Check environment (.env):
# FUSIONAUTH_RAY_CLIENT_ID=<client-id>
# FUSIONAUTH_RAY_CLIENT_SECRET=<secret>
# NEXTAUTH_URL=http://${TAILSCALE_IP}:3002

# Restart
docker restart fusionauth ray-compute-ui
```

---

### Ray UI 401/403 After OAuth Login (CRITICAL)

**Symptoms:**
- User successfully logs in via OAuth (FusionAuth/OAuth2-Proxy)
- Ray UI loads briefly, then shows 401/403 errors
- API calls to `/ray/api/*` fail with unauthorized
- Browser shows cookies are set correctly
- Traefik logs show OAuth2-Proxy forwardAuth succeeds
- API logs show: `"Missing authorization - no cookie or token"`

**Root Cause:**
OAuth2-Proxy uses **session cookies** (like `_sfml_oauth2`) that work for browser navigation. But when Ray UI makes **fetch() API calls**, there's a mismatch:

1. **OAuth2-Proxy authentication** validates the cookie → sets `X-Auth-Request-*` headers
2. **Traefik forwardAuth** passes these headers to the backend
3. **Ray API** looks for JWT token OR session cookie → finds neither (fetch doesn't auto-send cookies without credentials)
4. **API rejects** the request with 401

Unlike services that have no backend auth (MLflow), or services designed for proxy auth (Grafana with `GF_AUTH_PROXY_ENABLED`), Ray API requires explicit configuration to trust the forwarded headers.

**Diagnosis:**
```bash
# 1. Check if OAuth2-Proxy is setting headers correctly
curl -v -b "_sfml_oauth2=<session-cookie>" \
  https://shml-platform.tail38b60a.ts.net/oauth2-proxy/auth
# Should return 202 with X-Auth-Request-* headers

# 2. Check what headers reach Ray API
docker logs ray-compute-api --tail 50 | grep -i auth
# Look for: "X-Auth-Request-User", "X-Auth-Request-Email"

# 3. Test API directly with headers
curl -H "X-Auth-Request-Email: user@example.com" \
  http://localhost:8000/health
# If API is configured correctly, should return 200
```

**Solution: Enable Proxy Auth Trust Mode**

The fix is to configure Ray API to trust `X-Auth-Request-*` headers set by OAuth2-Proxy, similar to how Grafana's `GF_AUTH_PROXY_ENABLED=true` works.

**Step 1: Update Ray API configuration**

Add to `ray_compute/.env`:
```bash
# Trust OAuth2-Proxy forwarded headers for authentication
PROXY_AUTH_ENABLED=true
PROXY_AUTH_HEADER=X-Auth-Request-Email
PROXY_AUTH_USER_HEADER=X-Auth-Request-User
PROXY_AUTH_GROUPS_HEADER=X-Auth-Request-Groups
```

**Step 2: Update docker-compose to pass environment**

In `ray_compute/docker-compose.yml`:
```yaml
ray-compute-api:
  environment:
    - PROXY_AUTH_ENABLED=${PROXY_AUTH_ENABLED:-false}
    - PROXY_AUTH_HEADER=${PROXY_AUTH_HEADER:-X-Auth-Request-Email}
    - PROXY_AUTH_USER_HEADER=${PROXY_AUTH_USER_HEADER:-X-Auth-Request-User}
    - PROXY_AUTH_GROUPS_HEADER=${PROXY_AUTH_GROUPS_HEADER:-X-Auth-Request-Groups}
```

**Step 3: Implement proxy auth in API server**

In `ray_compute/api/server_v2.py`, add dependency that extracts user from headers:
```python
async def get_current_user_from_proxy(request: Request) -> Optional[dict]:
    """Extract user from OAuth2-Proxy forwarded headers."""
    if not os.getenv("PROXY_AUTH_ENABLED", "false").lower() == "true":
        return None

    email = request.headers.get(os.getenv("PROXY_AUTH_HEADER", "X-Auth-Request-Email"))
    user = request.headers.get(os.getenv("PROXY_AUTH_USER_HEADER", "X-Auth-Request-User"))
    groups = request.headers.get(os.getenv("PROXY_AUTH_GROUPS_HEADER", "X-Auth-Request-Groups"), "")

    if email:
        return {
            "email": email,
            "user": user or email.split("@")[0],
            "groups": groups.split(",") if groups else []
        }
    return None
```

**Step 4: Restart Ray API**
```bash
./start_all_safe.sh restart ray
```

**Verification:**
```bash
# 1. Check API health with proxy headers
curl -H "X-Auth-Request-Email: test@example.com" \
  http://localhost:8000/health
# Should return 200

# 2. Check through Traefik with session cookie
curl -b "_sfml_oauth2=<session-cookie>" \
  https://shml-platform.tail38b60a.ts.net/ray/api/health
# Should return 200

# 3. Open Ray UI in browser
# Navigate to Jobs page
# Check network tab - all API calls should return 200
```

**Why Different Services Need Different Auth Patterns:**

| Service | Auth Pattern | Why |
|---------|--------------|-----|
| **MLflow UI** | No backend auth | Just a dashboard, all actions go through MLflow API |
| **Grafana** | `GF_AUTH_PROXY_ENABLED` | Native support for proxy auth headers |
| **Ray UI** | Custom proxy auth | API requires auth, must trust proxy headers |
| **Homer** | No backend auth | Static dashboard, no sensitive data |

**Key Insight:**
- OAuth2-Proxy handles **user authentication** at the gateway
- Backend APIs need to be told to **trust the gateway's auth decision**
- Without explicit configuration, APIs will reject requests from authenticated users

**Related Files:**
- Ray API server: `ray_compute/api/server_v2.py`
- Ray environment: `ray_compute/.env`
- OAuth2-Proxy config: `docker-compose.infra.yml`
- Traefik middlewares: `docker-compose.yml` (oauth2-auth forwardAuth)

**Prevention:**
- **ALWAYS** configure backend APIs to trust OAuth2-Proxy headers when using forwardAuth
- Add `PROXY_AUTH_ENABLED=true` to any new API service behind OAuth2-Proxy
- Test API auth with both browser navigation AND fetch() calls
- Check API logs for auth failures after OAuth changes

### MLflow Artifact Permission Denied in Ray Jobs

**Symptoms:**
- Training completes successfully but fails at end with `PermissionError: [Errno 13] Permission denied: '/mlflow'`
- MLflow callback tries to log artifacts but can't write to `/mlflow/artifacts`
- Error occurs during `mlflow.log_artifact()` in Ray training jobs

**Root Cause:**
Ray container runs as `ray` user (uid=1000) but doesn't have the mlflow-artifacts volume mounted, or the volume has wrong permissions.

**Fix:**
```bash
# 1. Ensure mlflow-artifacts volume is mounted in ray_compute/docker-compose.yml
# Add to ray-head volumes section:
#   - mlflow-artifacts:/mlflow/artifacts
# Add to volumes section at bottom:
#   mlflow-artifacts:
#     external: true

# 2. Fix volume permissions
sudo chown -R 1000:100 /var/lib/docker/volumes/mlflow-artifacts/_data

# 3. Recreate Ray container to pick up volume mount
cd ray_compute
docker compose up -d ray-head

# 4. Verify mount and permissions
docker exec ray-head ls -la /mlflow/artifacts
docker exec ray-head touch /mlflow/artifacts/test.txt && docker exec ray-head rm /mlflow/artifacts/test.txt
```

**Verification:**
- `/mlflow/artifacts` directory exists in Ray container
- Directory is owned by `ray` user (uid=1000, gid=100)
- Ray can create and delete files in the directory
- MLflow artifact logging succeeds in training jobs

### API 500 Errors

**Symptoms:**
- Internal server error
- API returns 500
- Logs show Python exceptions

**Fix:**
```bash
# Check API logs
docker logs ray-compute-api --tail 100

# Check database connection
docker exec ray-compute-api python -c "
from sqlalchemy import create_engine
engine = create_engine('postgresql://ray_compute:password@ray-compute-db:5432/ray_compute')
with engine.connect() as conn:
    print('Connected')
"

# Check Ray connection
docker exec ray-compute-api curl http://ray-head:8265/api/version

# Restart
docker restart ray-compute-api
```

---

## Network Issues

### Traefik API Routes Return 404 (CRITICAL)

**Symptoms:**
- Custom API routes like `/api/v1/health` return 404
- Traefik dashboard API responds instead of application
- Direct container access works: `curl http://<container-ip>:8000/health` succeeds
- Traefik proxy fails: `curl http://localhost/api/v1/health` returns 404

**Root Cause:**
Traefik's internal API dashboard uses `PathPrefix(/api)` with ultra-high priority (2147483646), intercepting all `/api/*` requests unless application routers have higher priority.

**Diagnosis:**
```bash
# Check router priorities
curl -s http://localhost:8090/api/http/routers | jq '.[] | select(.name | contains("api")) | {name, rule, priority}'

# Should show:
# {
#   "name": "api@internal",
#   "rule": "PathPrefix(`/api`)",
#   "priority": 2147483646        # Traefik internal API
# }
# {
#   "name": "mlflow-api-v1@docker",
#   "rule": "PathPrefix(`/api/v1`)",
#   "priority": 2147483647        # YOUR API (must be higher!)
# }

# Test direct container access
CONTAINER_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' mlflow-api)
curl http://$CONTAINER_IP:8000/health  # Should work

# Test through Traefik
curl http://localhost/api/v1/health    # 404 = priority issue
```

**Fix:**
Edit `docker-compose.yml` and set router priority to max int32 (2147483647):
```yaml
labels:
  - traefik.http.routers.mlflow-api-v1.rule=PathPrefix(`/api/v1`)
  - traefik.http.routers.mlflow-api-v1.priority=2147483647  # Max int32 - MUST exceed 2147483646
  - traefik.http.routers.mlflow-api-v1.service=mlflow-api-service
```

Apply changes:
```bash
docker-compose up -d --force-recreate mlflow-api
# Wait 10 seconds for router registration
curl http://localhost/api/v1/health  # Should now work
```

**Why Priority Matters:**
- Traefik evaluates routes by priority (highest first)
- Internal API (`api@internal`): priority 2147483646
- If your API has lower priority (e.g., 500), Traefik internal API wins
- Use max int32 (2147483647) to guarantee precedence

**Access Points After Fix:**
- Application API: http://localhost/api/v1/* (priority 2147483647)
- Traefik Dashboard API: http://localhost:8090/api/* (internal access only)
- Traefik Dashboard UI: http://localhost:8090/ (internal access only)

**Reference:** See copilot instructions for comprehensive Traefik routing best practices.

---

### Services Can't Communicate

**Symptoms:**
- "connection refused" between containers
- DNS resolution fails
- Ray can't reach MLflow

**Fix:**
```bash
# Check network
docker network inspect ml-platform | grep -A 5 "Containers"

# Test DNS
docker exec ray-compute-api nslookup mlflow-nginx
docker exec mlflow-server nslookup ray-head

# Test connectivity
docker exec ray-compute-api ping -c 2 mlflow-nginx
docker exec ray-compute-api curl http://mlflow-nginx:80/health

# Reconnect containers
docker network disconnect ml-platform ray-compute-api
docker network connect ml-platform ray-compute-api

# Or restart all
docker compose down
docker compose up -d
```

### External Access Blocked

**Symptoms:**
- Can't access from LAN
- Tailscale doesn't work
- Firewall blocking

**Fix:**
```bash
# Check firewall
sudo ufw status

# Open ports
sudo ufw allow 80/tcp comment "Traefik Gateway"
sudo ufw allow 8090/tcp comment "Traefik Dashboard"

# Check Tailscale
tailscale status
tailscale ip -4

# Test local first
curl http://localhost/mlflow/

# Test LAN
curl http://localhost/mlflow/

# Test VPN
curl http://${TAILSCALE_IP}/mlflow/

# Check Traefik logs
docker logs traefik --tail 50 | grep -i error
```

### Traefik 404 Errors

**Symptoms:**
- 404 Not Found
- "Backend not found"
- Routes not working

**Fix:**
```bash
# Check routers
curl http://localhost:8090/api/http/routers | jq

# Check services
curl http://localhost:8090/api/http/services | jq

# Verify labels (docker inspect)
docker inspect mlflow-nginx | grep -A 20 Labels

# Expected labels:
# traefik.http.routers.mlflow.rule=PathPrefix(`/mlflow`)
# traefik.http.routers.mlflow.priority=100

# Restart Traefik
docker restart traefik
```

---

## Performance Issues

### Slow Response Times

**Symptoms:**
- Long page load
- API timeouts
- High CPU/memory

**Fix:**
```bash
# Check resources
docker stats

# Check logs for errors
docker logs mlflow-server --tail 100 | grep -i error
docker logs ray-head --tail 100 | grep -i error

# Check database size
docker exec mlflow-postgres psql -U mlflow -d mlflow_db \
  -c "SELECT pg_size_pretty(pg_database_size('mlflow_db'));"

# Check disk space
df -h

# Cleanup old data
docker exec mlflow-postgres psql -U mlflow -d mlflow_db \
  -c "DELETE FROM runs WHERE start_time < NOW() - INTERVAL '90 days';"

# Restart services
docker restart mlflow-server mlflow-postgres
```

### High Memory Usage

**Symptoms:**
- Out of memory errors
- OOMKilled containers
- System freezes

**Fix:**
```bash
# Check memory
free -h
docker stats --no-stream

# Add memory limits (docker-compose.yml):
# mlflow-server:
#   deploy:
#     resources:
#       limits:
#         memory: 2G
#       reservations:
#         memory: 1G

# Restart with limits
docker compose up -d
```

### Disk Space Full

**Symptoms:**
- "no space left on device"
- Backup failures
- Artifact upload fails

**Fix:**
```bash
# Check usage
df -h
du -sh ml-platform/mlflow-server/data/*
du -sh ml-platform/ray_compute/data/*

# Clean Docker
docker system prune -a --volumes -f

# Remove old backups
find ml-platform/mlflow-server/backups -mtime +90 -delete

# Move artifacts to larger disk
mv ml-platform/mlflow-server/data /mnt/storage/mlflow-data
ln -s /mnt/storage/mlflow-data ml-platform/mlflow-server/data
```

---

## Tailscale VPN Issues

### Connection Refused

**Symptoms:**
- Can't reach Tailscale IP
- Timeout errors
- VPN disconnected

**Fix:**
```bash
# Check Tailscale status
tailscale status

# Check IP
tailscale ip -4

# Restart Tailscale
sudo systemctl restart tailscaled

# Reconnect
sudo tailscale up

# Enable on boot
sudo systemctl enable tailscaled

# Test connectivity
ping -c 4 $(tailscale ip -4)
curl http://$(tailscale ip -4)/mlflow/
```

### IP Changed

**Symptoms:**
- Old IP doesn't work
- Clients can't connect
- Documentation shows old IP

**Fix:**
```bash
# Get current IP
tailscale ip -4

# Update .env files
cd mlflow-server
sed -i 's/100\.78\.129\.124/<NEW_IP>/g' docker-compose.yml

cd ../ray_compute
sed -i 's/100\.78\.129\.124/<NEW_IP>/g' .env docker-compose.*.yml

# Restart services
docker compose down
docker compose up -d
```

---

## Data Issues

### Lost Data After Restart

**Symptoms:**
- Experiments gone
- Models missing
- Database empty

**Fix:**
```bash
# Check volumes
docker volume ls | grep mlflow

# Check data directory
ls -lh ml-platform/mlflow-server/data/

# Restore from backup
docker compose down
cp -r ml-platform/mlflow-server/data.backup.* ml-platform/mlflow-server/data
docker compose up -d

# Or restore database only
cd ml-platform/mlflow-server/backups/postgres
gunzip -c mlflow_backup_20251122.sql.gz | \
  docker exec -i mlflow-postgres psql -U mlflow -d mlflow_db
```

### Backup Failed

**Symptoms:**
- Cron job errors
- Empty backup files
- Disk full

**Fix:**
```bash
# Check backup logs
docker logs mlflow-backup --tail 50

# Check backup directory
ls -lh ml-platform/mlflow-server/backups/postgres/

# Manual backup
docker exec mlflow-postgres pg_dump -U mlflow mlflow_db | \
  gzip > ml-platform/mlflow-server/backups/postgres/manual_$(date +%Y%m%d).sql.gz

# Check cron (if using)
docker exec mlflow-backup crontab -l

# Fix permissions
sudo chown -R $USER:$USER ml-platform/mlflow-server/backups/
```

---

## After Reboot

### Services Don't Auto-Start

**Symptoms:**
- Nothing running after boot
- Have to manually start
- systemd not configured

**Fix:**
```bash
# Option 1: Docker restart policy (already set)
# Check compose files have:
# restart: unless-stopped

# Option 2: Systemd service
sudo nano /etc/systemd/system/ml-platform.service
# Paste contents (see SYSTEMD_SERVICE.md)

sudo systemctl daemon-reload
sudo systemctl enable ml-platform.service
sudo systemctl start ml-platform.service

# Check status
sudo systemctl status ml-platform.service
```

### Volumes Not Mounting

**Symptoms:**
- Data missing
- Permission errors
- Empty directories

**Fix:**
```bash
# Check permissions
ls -ld ml-platform/mlflow-server/data ml-platform/ray_compute/data

# Fix ownership
sudo chown -R $USER:$USER ml-platform/mlflow-server/data
sudo chown -R $USER:$USER ml-platform/ray_compute/data

# Restart
docker compose down
docker compose up -d
```

---

## Monitoring Issues

### Grafana Login Failed

**Symptoms:**
- Wrong password
- Can't access dashboards
- Reset needed

**Fix:**
```bash
# MLflow Grafana
docker exec mlflow-grafana grafana-cli admin reset-admin-password admin

# Ray Grafana
docker exec ray-grafana grafana-cli admin reset-admin-password admin

# Or check secrets
cat ml-platform/mlflow-server/secrets/grafana_password.txt
grep GRAFANA_ADMIN_PASSWORD ml-platform/ray_compute/.env
```

### Prometheus Not Scraping

**Symptoms:**
- No metrics
- Empty graphs
- Targets down

**Fix:**
```bash
# Check targets
curl http://localhost:9090/api/v1/targets | jq

# Check Prometheus config
docker exec mlflow-prometheus cat /etc/prometheus/prometheus.yml

# Check services exposing metrics
curl http://mlflow-server:5000/metrics
curl http://ray-head:8265/metrics

# Restart
docker restart mlflow-prometheus
```

---

## Emergency Procedures

### Complete System Reset

```bash
# DANGER: This deletes all data!

# Stop all
cd /home/axelofwar/Desktop/Projects
./stop_all.sh

# Remove data (BACKUP FIRST!)
rm -rf ml-platform/mlflow-server/data/*
rm -rf ml-platform/ray_compute/data/*

# Remove secrets (will regenerate)
rm ml-platform/mlflow-server/secrets/*
rm ml-platform/ray_compute/.env

# Recreate network
docker network rm ml-platform
docker network create ml-platform --driver bridge --subnet 172.30.0.0/16

# Start fresh
./start_all.sh
```

### Recover from Backup

```bash
# Stop services
docker compose down

# Restore MLflow data
cd mlflow-server
cp -r data.backup.20251122/* data/

# Restore database
gunzip -c backups/postgres/latest.sql.gz | \
  docker exec -i mlflow-postgres psql -U mlflow -d mlflow_db

# Start
docker compose up -d
```

---

## Getting Help

### Collect Debug Info

```bash
# Create debug report
cat > debug_report.txt << 'EOF'
=== SYSTEM INFO ===
$(uname -a)
$(docker --version)
$(docker compose version)

=== CONTAINERS ===
$(docker ps -a)

=== NETWORKS ===
$(docker network inspect ml-platform)

=== LOGS (last 50 lines each) ===
=== MLflow ===
$(docker logs mlflow-server --tail 50)

=== Traefik ===
$(docker logs traefik --tail 50)

=== Ray ===
$(docker logs ray-head --tail 50 2>/dev/null || echo "Not running")

=== DISK ===
$(df -h)

=== MEMORY ===
$(free -h)
EOF

# Share debug_report.txt for support
```

### Check Documentation

- [ARCHITECTURE.md](../architecture/index.md) - System design
- [API_REFERENCE.md](../api/index.md) - API details
- [INTEGRATION_GUIDE.md](../sdk/index.md) - Service communication
- [CURRENT_DEPLOYMENT.md](../architecture/services.md) - What's running
- ml-platform/mlflow-server/README.md - MLflow specifics
- ml-platform/ray_compute/README.md - Ray specifics

---

**Last Resort:** See archived/IMPLEMENTATION_CHECKLIST.md for full rebuild

**Updated:** 2025-11-22
