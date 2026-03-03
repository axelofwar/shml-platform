# Ray Authenticated Job Submission Architecture

**Date:** December 12, 2025  
**Expert Panel:** API Security Engineers, OAuth Specialists, Ray Platform Engineers, DevOps Architects  
**Status:** Design Phase

---

## Problem Statement

**Current Issue:**
- Job submission requires `docker exec` into containers (violates security boundaries)
- No authentication/authorization for programmatic job submission
- Cannot submit jobs remotely without exposing Docker ports

**Requirements:**
1. ✅ OAuth-authenticated job submission (FusionAuth integration)
2. ✅ Role-based access control (developer/admin roles can submit)
3. ✅ Works from host machine (no container exec)
4. ✅ Works remotely via Tailscale (no port exposure)
5. ✅ Audit logging (who submitted what job)
6. ✅ Resource quotas per user/role

---

## Expert Panel Recommendations

### 1. API Security Engineers

**Recommendation:** **OAuth2 + API Key Hybrid Authentication**

```
┌─────────────────────────────────────────────────────────────────┐
│                  AUTHENTICATED JOB SUBMISSION                    │
│                                                                  │
│  User (CLI/Host) → Traefik → OAuth2-Proxy → Ray Compute API    │
│                                 │                │               │
│                                 │                ├→ Verify Token │
│                                 │                ├→ Check RBAC   │
│                                 │                ├→ Log Audit    │
│                                 │                └→ Submit to    │
│                                 │                   Ray Head     │
│                                 ↓                                │
│                           FusionAuth                             │
│                           (Token Introspection)                  │
└─────────────────────────────────────────────────────────────────┘
```

**Key Points:**
- OAuth2 tokens for interactive users (browser, CLI with device flow)
- API keys for service accounts (CI/CD, automation)
- All tokens validated via FusionAuth introspection endpoint
- Ray Compute API acts as authenticated gateway to Ray cluster

### 2. OAuth Specialists

**Recommendation:** **Leverage Existing OAuth2-Proxy + FusionAuth Infrastructure**

**Current Stack (Already Deployed):**
- ✅ FusionAuth: OAuth provider with social logins (Google, GitHub, Twitter)
- ✅ OAuth2-Proxy: ForwardAuth middleware for Traefik
- ✅ role-auth: RBAC middleware (developer/admin role checking)
- ✅ X-Auth-Request-* headers: User identity propagation

**Authentication Flows:**

#### Flow 1: Browser-Based (UI)
```http
GET /ray/ui → OAuth2-Proxy → FusionAuth Login → Headers:
  X-Auth-Request-User: alice
  X-Auth-Request-Email: alice@example.com
  X-Auth-Request-Groups: developers,premium
  Authorization: Bearer <fusionauth-token>
```

#### Flow 2: CLI with OAuth Device Flow
```bash
# Step 1: Initiate device flow
$ shml-ray auth login
Visit: https://shml-platform.tail38b60a.ts.net/auth/device?user_code=ABCD-1234

# Step 2: User authenticates in browser
[User approves device in FusionAuth]

# Step 3: CLI polls for token
Token saved to ~/.shml/credentials

# Step 4: Submit job with token
$ shml-ray job submit --script train.py
Job ID: raysubmit_abc123
```

#### Flow 3: API Key for Automation
```bash
# Generate API key (admin only)
$ shml-ray apikey create --name "ci-pipeline" --role developer
API Key: shml_key_xyz789...

# Use in CI/CD
$ export SHML_API_KEY=shml_key_xyz789...
$ shml-ray job submit --script train.py
```

### 3. Ray Platform Engineers

**Recommendation:** **Ray Compute API as Authenticated Gateway**

**Architecture:**

```python
# ray_compute/api/server_v2.py

@app.post("/api/v1/jobs/submit")
async def submit_job(
    request: JobSubmitRequest,
    current_user: User = Depends(get_current_user),  # OAuth validation
    db: Session = Depends(get_db),
):
    """
    Submit job to Ray cluster with authentication

    Authentication:
    - OAuth token from FusionAuth (via Authorization header)
    - API key (via X-API-Key header)
    - OAuth2-Proxy headers (via X-Auth-Request-* when proxied)

    Authorization:
    - Requires 'developer' or 'admin' role
    - Enforces user quotas (max concurrent jobs, GPU limits)

    Audit:
    - Logs user, job details, timestamp to audit table
    """

    # Check role permissions
    if not can_submit_jobs(current_user.role):
        raise HTTPException(403, "Developer role required for job submission")

    # Check user quotas
    active_jobs = get_active_jobs_count(current_user.id, db)
    if active_jobs >= current_user.quota.max_concurrent_jobs:
        raise HTTPException(429, "Max concurrent jobs limit reached")

    # Audit log
    log_audit_event(
        user_id=current_user.id,
        action="job_submit",
        resource=f"job:{request.name}",
        details={"script": request.entrypoint, "gpu": request.gpu},
        db=db,
    )

    # Submit to Ray cluster (internal network, no auth needed)
    ray_client = JobSubmissionClient("http://ray-head:8265")
    job_id = ray_client.submit_job(
        entrypoint=request.entrypoint,
        runtime_env=request.runtime_env,
        metadata={
            "submitted_by": current_user.email,
            "submitted_at": datetime.utcnow().isoformat(),
        },
    )

    # Record job in database
    job = Job(
        ray_job_id=job_id,
        user_id=current_user.id,
        name=request.name,
        status="PENDING",
        created_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()

    return {"job_id": job_id, "status": "submitted"}
```

**Key Features:**
1. ✅ Authentication via `get_current_user()` dependency (OAuth or API key)
2. ✅ Role-based authorization (`can_submit_jobs()`)
3. ✅ Quota enforcement (max concurrent jobs, GPU limits)
4. ✅ Audit logging (who submitted what, when)
5. ✅ Internal Ray submission (no authentication needed within Docker network)

### 4. DevOps Architects

**Recommendation:** **Zero-Port-Exposure Design**

**Current Traefik Routing (Already Configured):**
```yaml
# Ray Compute API accessible via Traefik
traefik.http.routers.ray-api.rule=PathPrefix(`/ray/api`)
traefik.http.routers.ray-api.middlewares=oauth2-errors,oauth2-auth,role-auth-developer
traefik.http.services.ray-api.loadbalancer.server.port=8000
```

**Access Methods:**

| Location | URL | Authentication |
|----------|-----|----------------|
| **Local Host** | `http://localhost/ray/api` | OAuth2-Proxy → FusionAuth |
| **Remote (Tailscale)** | `https://shml-platform.tail38b60a.ts.net/ray/api` | OAuth2-Proxy → FusionAuth |
| **CI/CD** | `http://localhost/ray/api` + API Key | X-API-Key header |

**Benefits:**
- ✅ No Docker port exposure (8265 stays internal)
- ✅ Works from any location (local or remote via Tailscale Funnel)
- ✅ Authentication handled by existing infrastructure
- ✅ HTTPS via Tailscale (automatic cert)

---

## Implementation Plan

### Phase 1: Enhance Ray Compute API (2-3 hours)

**Tasks:**
1. ✅ Add `/api/v1/jobs/submit` endpoint to `ray_compute/api/server_v2.py`
2. ✅ Implement OAuth token validation (FusionAuth introspection)
3. ✅ Add API key authentication (X-API-Key header)
4. ✅ Implement RBAC checks (developer role required)
5. ✅ Add quota enforcement (max concurrent jobs)
6. ✅ Add audit logging to database
7. ✅ Test with existing OAuth2-Proxy + role-auth middleware

**Files to Modify:**
- `ray_compute/api/server_v2.py` - Add job submission endpoint
- `ray_compute/api/auth.py` - Add API key validation
- `ray_compute/api/models.py` - Add Job and AuditLog models
- `ray_compute/api/database.py` - Add audit logging functions

### Phase 2: Create Host-Side CLI Tool (1-2 hours)

**Tasks:**
1. ✅ Create `scripts/shml_ray_cli.py` using `uv`
2. ✅ Implement OAuth device flow for interactive auth
3. ✅ Implement API key auth for automation
4. ✅ Add `job submit` command
5. ✅ Add `job list` command
6. ✅ Add `job logs` command
7. ✅ Add `apikey create` command (admin only)

**CLI Commands:**
```bash
# Install CLI
$ uv pip install --break-system-packages typer httpx

# Authenticate (interactive)
$ python3 scripts/shml_ray_cli.py auth login
Visit: https://shml-platform.tail38b60a.ts.net/auth/device?user_code=WXYZ

# Submit job
$ python3 scripts/shml_ray_cli.py job submit \
    --script ray_compute/jobs/training/phase1_foundation.py \
    --name "phase1-wider-200ep" \
    --gpu 1

# List jobs
$ python3 scripts/shml_ray_cli.py job list

# View logs
$ python3 scripts/shml_ray_cli.py job logs raysubmit_abc123

# Generate API key (for CI/CD)
$ python3 scripts/shml_ray_cli.py apikey create --name "github-ci"
```

### Phase 3: Update Traefik Routing (Optional)

**Current routing works, but may need adjustment for `/api/v1/jobs/submit`:**

```yaml
# Ensure Ray API has developer role requirement
traefik.http.routers.ray-api.rule=PathPrefix(`/ray/api`)
traefik.http.routers.ray-api.middlewares=oauth2-errors,oauth2-auth,role-auth-developer
traefik.http.routers.ray-api.priority=2147483647  # Max priority
```

**Note:** Already configured in `ray_compute/docker-compose.yml`

### Phase 4: Testing & Validation (30 min)

**Test Cases:**
1. ✅ Unauthenticated request → 401 (OAuth2-Proxy blocks)
2. ✅ Authenticated viewer → 403 (role-auth-developer blocks)
3. ✅ Authenticated developer → 200 (job submitted)
4. ✅ Quota exceeded → 429 (rate limit)
5. ✅ API key auth → 200 (bypasses OAuth2-Proxy)
6. ✅ Remote submission via Tailscale → 200

---

## Security Considerations

### 1. Token Security

**OAuth Tokens:**
- ✅ Short-lived (15 min default, FusionAuth configurable)
- ✅ Validated via introspection (cannot be forged)
- ✅ Automatically refreshed by OAuth2-Proxy
- ✅ Revocable in FusionAuth admin panel

**API Keys:**
- ✅ Long-lived (for automation), stored hashed in database
- ✅ Scoped to specific roles (developer, admin)
- ✅ Revocable via CLI or admin API
- ✅ Audit logged on every use

### 2. Network Security

- ✅ Ray Job API (8265) NOT exposed to host
- ✅ All access via Traefik (HTTPS via Tailscale)
- ✅ OAuth2-Proxy enforces authentication before reaching API
- ✅ role-auth enforces RBAC (developer role required)

### 3. Audit Logging

**Every job submission logged:**
```sql
INSERT INTO audit_log (
    user_id,
    action,
    resource,
    details,
    ip_address,
    timestamp
) VALUES (
    123,
    'job_submit',
    'job:phase1-wider-200ep',
    '{"script": "phase1_foundation.py", "gpu": 1}',
    '100.66.26.115',
    '2025-12-12T10:30:00Z'
);
```

**Queryable:**
```sql
-- Who submitted the most jobs?
SELECT user_id, COUNT(*) FROM audit_log
WHERE action = 'job_submit'
GROUP BY user_id ORDER BY COUNT(*) DESC;

-- What jobs did Alice submit?
SELECT * FROM audit_log
WHERE user_id = (SELECT id FROM users WHERE email = 'alice@example.com')
AND action = 'job_submit';
```

---

## Migration Path (No Downtime)

### Current State
- Job submission via `docker exec ray-head ray job submit`
- No authentication/authorization
- No audit logging

### Target State
- Job submission via authenticated Ray Compute API
- OAuth or API key required
- Developer role required
- Full audit trail

### Migration Steps

1. ✅ **Deploy API enhancements** (no breaking changes)
   - Add `/api/v1/jobs/submit` endpoint
   - Keep existing Ray dashboard functional
   - OAuth2-Proxy + role-auth already deployed

2. ✅ **Test new submission flow** (parallel to old method)
   - Submit test job via new API
   - Verify authentication works
   - Verify RBAC works
   - Verify audit logging works

3. ✅ **Update documentation** (INTEGRATION_GUIDE.md)
   - Document new submission method
   - Provide CLI tool instructions
   - Mark `docker exec` method as deprecated

4. ✅ **Announce deprecation** (README.md)
   - "Direct container access will be removed in v0.4.0"
   - "Use shml-ray CLI or Ray Compute API"
   - Provide migration deadline (e.g., 3 months)

5. ✅ **Remove docker exec access** (future release)
   - Update Docker Compose to remove shell access
   - Force all submissions via authenticated API

---

## Success Criteria

✅ **Functional:**
- [ ] Submit job from host without docker exec
- [ ] Submit job remotely via Tailscale
- [ ] Submit job from CI/CD with API key
- [ ] OAuth authentication works (FusionAuth integration)
- [ ] RBAC enforces developer role requirement
- [ ] Quotas prevent abuse (max concurrent jobs)
- [ ] Audit logging tracks all submissions

✅ **Security:**
- [ ] No Docker port exposure (8265 stays internal)
- [ ] All access via authenticated Traefik routes
- [ ] Tokens validated via FusionAuth introspection
- [ ] API keys stored hashed in database
- [ ] Audit log immutable and queryable

✅ **Usability:**
- [ ] CLI tool works with `uv` (no venv needed)
- [ ] OAuth device flow for interactive auth
- [ ] API keys for automation (CI/CD)
- [ ] Clear error messages (401, 403, 429)
- [ ] Documentation updated (INTEGRATION_GUIDE.md)

---

## Next Steps

1. **Implement API enhancements** (Task 2)
   - Add job submission endpoint to Ray Compute API
   - Integrate with existing OAuth2-Proxy + role-auth
   - Add audit logging to database

2. **Create CLI tool** (Task 3)
   - Build `scripts/shml_ray_cli.py` using Typer
   - Implement OAuth device flow and API key auth
   - Add job submit/list/logs commands

3. **Launch Phase 1 training** (Task 4)
   - Submit phase1_foundation.py via new authenticated API
   - Monitor via Grafana unified dashboard
   - Verify audit logging works

4. **Start parallel tasks** (Tasks 5-8)
   - Remove old Grafana dashboards
   - Start YFCC100M downloader
   - Install SAM2
   - Setup MLflow model registry

---

**Expert Panel Sign-Off:**
- ✅ API Security Engineers: Architecture approved
- ✅ OAuth Specialists: Integration with existing FusionAuth stack approved
- ✅ Ray Platform Engineers: Gateway pattern approved
- ✅ DevOps Architects: Zero-port-exposure design approved

**Status:** Ready for implementation  
**Estimated Time:** 3-4 hours total  
**Risk:** Low (leverages existing OAuth infrastructure)
