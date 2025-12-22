# Role Mapping Strategy & Implementation
## FusionAuth Roles vs Platform Access Requirements

**Date:** December 7, 2025  
**Status:** Authoritative Role Configuration  
**Purpose:** Define how FusionAuth roles map to platform access

---

## Current FusionAuth Role Configuration

### OAuth2-Proxy Application Roles

```
✓ viewer              (isDefault: true)  - Read-only, basic chat, rate limited
✓ developer           (isDefault: false) - Full dev access, ML workflow, no sandboxes
✓ elevated-developer  (isDefault: false) - Developer + code execution, model management
✓ admin               (isDefault: false, isSuperRole: true) - Full platform access
```

**Source:** `/fusionauth/kickstart/kickstart.json` lines 145-149

### Role Hierarchy (Inheritance)

```
viewer < developer < elevated-developer < admin
```

**Access Pattern:**
- `viewer` role = viewer access only
- `developer` role = viewer + developer access
- `elevated-developer` role = viewer + developer + elevated access
- `admin` role = viewer + developer + elevated + admin access (superRole)

---

## Role-Auth Middleware Configuration

**Location:** `/scripts/role-auth/nginx.conf`

### Endpoint: `/auth/viewer`
**Required Roles:** `viewer`, `developer`, `elevated-developer`, `admin`  
**Used For:** Grafana, Homer (monitoring dashboards)

### Endpoint: `/auth/developer`
**Required Roles:** `developer`, `elevated-developer`, `admin`  
**Used For:** MLflow, Ray, Agent Service, Chat UI, Dozzle

### Endpoint: `/auth/elevated-developer`
**Required Roles:** `elevated-developer`, `admin`  
**Used For:** Sandbox execution, model management, GitHub Actions

### Endpoint: `/auth/admin`
**Required Roles:** `admin`  
**Used For:** Traefik dashboard, Prometheus, Code-Server, FusionAuth Admin, Infisical

---

## API Key Configuration

### Required API Keys (3 keys minimum)

Based on the screenshot provided, we need these API keys configured in FusionAuth:

#### 1. Viewer API Key
- **ID/Name:** `[C]/[CD] Viewer key`
- **Roles:** `viewer`
- **Description:** Read-only access for monitoring dashboards
- **Usage:** Testing viewer-level access, external monitoring tools

#### 2. Developer API Key
- **ID/Name:** `[C]/[CD] Developer key`
- **Roles:** `developer`
- **Description:** Standard developer access for ML workflows
- **Usage:** CI/CD pipelines, developer tools, MLflow/Ray automation

#### 3. Admin API Key (Superkey)
- **ID/Name:** `[C]/[CD] Superkey`
- **Roles:** `admin`
- **Description:** Full platform access including infrastructure management
- **Usage:** Platform administration, emergency access, automation scripts

#### 4. Elevated-Developer API Key (Optional, Recommended)
- **ID/Name:** `[C]/[CD] Elevated Developer key`
- **Roles:** `elevated-developer`
- **Description:** Developer + sandbox execution for advanced workflows
- **Usage:** GitHub Actions, model training with code execution, agent sandboxes

---

## Service Access Matrix

| Service | Viewer | Developer | Elevated-Dev | Admin | Middleware |
|---------|--------|-----------|--------------|-------|------------|
| **Inference** (no auth) |
| Coding Models API | ✅ | ✅ | ✅ | ✅ | none |
| Chat API | ✅ | ✅ | ✅ | ✅ | none |
| Image Gen API | ✅ | ✅ | ✅ | ✅ | none |
| Vision Model API | ✅ | ✅ | ✅ | ✅ | none |
| Embedding Service | ✅ | ✅ | ✅ | ✅ | none |
| **User-Facing** |
| Chat UI | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| **ML Workflow** |
| MLflow UI | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| MLflow API | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| Ray Dashboard | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| Ray Jobs API | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| **Agent Service** |
| Agent REST API | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| Agent WebSocket | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| Agent Sandbox Exec | ❌ | ❌ | ✅ | ✅ | (role check in code) |
| **Monitoring** |
| Grafana | ✅ | ✅ | ✅ | ✅ | role-auth-viewer |
| Homer Dashboard | ✅ | ✅ | ✅ | ✅ | role-auth-viewer |
| Dozzle (Logs) | ❌ | ✅ | ✅ | ✅ | role-auth-developer |
| Prometheus | ❌ | ❌ | ❌ | ✅ | role-auth-admin |
| **Admin Tools** |
| Traefik Dashboard | ❌ | ❌ | ❌ | ✅ | role-auth-admin |
| Code-Server | ❌ | ❌ | ❌ | ✅ | role-auth-admin |
| FusionAuth Admin | ❌ | ❌ | ❌ | ✅ | role-auth-admin |
| Infisical (Secrets) | ❌ | ❌ | ❌ | ✅ | role-auth-admin |

---

## Role Assignment Guidelines

### Default Role for New Users
**Recommended:** `viewer` (already configured as default)

**Rationale:**
- Secure by default (minimal access)
- Users can explore inference APIs without registration
- Must request upgrade for ML workflow access
- Clear upgrade path

### Upgrade Paths

```
viewer → developer:
  - User requests access
  - Admin verifies identity and need
  - Grants developer role in FusionAuth Admin UI

developer → elevated-developer:
  - User demonstrates need for sandbox execution
  - Admin reviews security implications
  - Grants elevated-developer role
  - User can now execute code, manage models

elevated-developer → admin:
  - Rare, only for trusted platform maintainers
  - Admin grants admin role
  - User can now manage infrastructure
```

### Social Login Auto-Assignment
**Current:** `viewer` (default role)  
**Recommendation:** Keep as `viewer` for security

**Alternative (Less Secure):**
- Auto-assign `developer` for verified email domains
- Requires email verification enabled
- Configure in FusionAuth: Application → Registration → Default Roles

---

## Implementation Checklist

### ✅ Already Configured

- [x] FusionAuth roles defined in kickstart.json
- [x] Role-auth middleware supports all 4 roles
- [x] Traefik middleware chains configured
- [x] Docker socket mounted for agent service (elevated+ only)
- [x] Agent service enforces role checks

### ⚠️ Need Verification

- [ ] API keys exist with correct roles assigned
- [ ] API keys tested against all endpoints
- [ ] Sandbox execution works with elevated-developer key
- [ ] Documentation updated to reflect actual roles

### 📋 Recommended Additions

- [ ] Create elevated-developer API key if not exists
- [ ] Document API key rotation policy
- [ ] Set up monitoring for failed auth attempts
- [ ] Create role upgrade request workflow

---

## Testing Role-Based Access

### Using Test Script

```bash
# Export API keys from FusionAuth Admin UI
export VIEWER_API_KEY="..."
export DEVELOPER_API_KEY="..."
export ADMIN_API_KEY="..."

# Run comprehensive tests
./scripts/test-role-auth.sh
```

### Expected Test Results

```
✓ Inference endpoints work without auth
✓ Viewer can access Grafana
✓ Viewer blocked from MLflow/Ray/Agent
✓ Developer can access MLflow/Ray/Agent
✓ Developer blocked from Prometheus/Traefik
✓ Admin can access everything
✓ Developer blocked from sandbox execution
✓ Admin can use sandbox execution
```

### Manual Testing

```bash
# Test viewer access
curl -H "Authorization: Bearer $VIEWER_API_KEY" \
  http://localhost/grafana/api/health
# Expected: 200 OK

curl -H "Authorization: Bearer $VIEWER_API_KEY" \
  http://localhost/mlflow/api/2.0/mlflow/experiments/list
# Expected: 403 Forbidden

# Test developer access
curl -H "Authorization: Bearer $DEVELOPER_API_KEY" \
  http://localhost/mlflow/api/2.0/mlflow/experiments/list
# Expected: 200 OK

curl -H "Authorization: Bearer $DEVELOPER_API_KEY" \
  http://localhost/prometheus/api/v1/query?query=up
# Expected: 403 Forbidden

# Test admin access
curl -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost/prometheus/api/v1/query?query=up
# Expected: 200 OK
```

---

## Security Considerations

### Docker Socket Access (Critical)

**Current Configuration:**
```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```

**Security Measures:**
1. **Read-Only Mount:** Prevents container modification
2. **Role Enforcement:** Agent service checks user role before container creation
3. **Kata Containers:** Sandboxes use hardware virtualization (not just namespaces)
4. **Resource Limits:** Sandboxes have CPU/memory limits
5. **Network Isolation:** Sandboxes on separate network

**Risk:** Even with :ro, Docker socket access allows container inspection  
**Mitigation:** Only elevated-developer and admin roles can access agent service sandbox features

### API Key Security

**Best Practices:**
1. **Rotation:** Rotate keys every 90 days
2. **Monitoring:** Log all API key usage in Grafana
3. **Least Privilege:** Use lowest role needed for each task
4. **Secure Storage:** Store keys in secrets manager (Infisical)
5. **Revocation:** Immediately revoke compromised keys

### Role Escalation Prevention

**Safeguards:**
1. **Admin-Only Role Assignment:** Only admins can grant roles
2. **Audit Logging:** All role changes logged in FusionAuth
3. **MFA for Admin:** Require MFA for admin accounts
4. **Session Timeout:** Tokens expire after 1 hour (configurable)
5. **Refresh Token Rotation:** Refresh tokens rotate on use

---

## Troubleshooting

### Issue: "Forbidden: requires one of: developer, elevated-developer, admin"

**Cause:** User has viewer role but trying to access developer-only endpoint

**Solution:**
1. Check user's roles in FusionAuth Admin UI
2. Grant developer role if appropriate
3. User must re-login to refresh token with new roles

### Issue: API key returns 401 Unauthorized

**Cause:** Invalid or expired API key

**Solution:**
1. Verify key exists in FusionAuth Admin → API Keys
2. Check key is not expired
3. Regenerate key if needed
4. Update environment variable with new key

### Issue: Sandbox execution fails with "elevated-developer role required"

**Cause:** User has developer role but not elevated-developer

**Solution:**
1. Request elevated-developer role from admin
2. Admin grants role in FusionAuth Admin UI
3. User re-authenticates to get updated token
4. Sandbox execution should now work

### Issue: Role-auth middleware returns 403 even with correct role

**Cause:** OAuth2-Proxy not forwarding `X-Auth-Request-Groups` header

**Solution:**
1. Check OAuth2-Proxy configuration in docker-compose.infra.yml
2. Verify `--set-xauthrequest=true` flag is set
3. Check nginx logs: `docker logs role-auth`
4. Verify FusionAuth returns roles in JWT claims

---

## Next Steps

### Immediate (This Session)

1. **Verify API Keys Exist:**
   - Check FusionAuth Admin UI screenshot
   - Verify viewer, developer, admin keys configured
   - Export keys to environment variables

2. **Run Auth Tests:**
   ```bash
   export VIEWER_API_KEY="..."
   export DEVELOPER_API_KEY="..."
   export ADMIN_API_KEY="..."
   ./scripts/test-role-auth.sh
   ```

3. **Test Sandbox Execution:**
   ```bash
   # With developer key (should fail)
   curl -X POST http://localhost/api/agent/v1/agent/execute \
     -H "Authorization: Bearer $DEVELOPER_API_KEY" \
     -d '{"task": "Execute code to print hello world", ...}'

   # With admin key (should succeed)
   curl -X POST http://localhost/api/agent/v1/agent/execute \
     -H "Authorization: Bearer $ADMIN_API_KEY" \
     -d '{"task": "Execute code to print hello world", ...}'
   ```

4. **Update Documentation:**
   - Replace "Guest" with "Viewer" in AUTH_FLOW_AND_USER_ACCESS.md
   - Add elevated-developer role explanations
   - Document sandbox access requirements

### Short-Term (Next Week)

1. **Create Elevated-Developer API Key:**
   - For GitHub Actions CI/CD pipelines
   - For automated model training workflows

2. **Set Up Monitoring:**
   - Grafana dashboard for auth failures
   - Alert on repeated 403 errors
   - Track API key usage by role

3. **Document Upgrade Process:**
   - Create request form for role upgrades
   - Define approval criteria
   - Document in CONTRIBUTING.md

---

**Prepared by:** AI Assistant  
**Date:** December 7, 2025  
**Status:** ✅ Authoritative Role Configuration  
**Action Required:** Verify API keys and run test-role-auth.sh
