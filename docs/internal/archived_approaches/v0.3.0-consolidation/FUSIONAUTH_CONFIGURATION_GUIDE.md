# FusionAuth Role Configuration Guide
## Actions Needed Based on Current UI State

**Date:** December 7, 2025  
**Current Status:** elevated-developer role exists, API key needs creation  
**Screenshots Reviewed:** Manage Roles, API Keys, Applications

---

## ✅ What's Already Correct

### OAuth2-Proxy Application Roles
**Location:** Applications > OAuth2-Proxy > Manage Roles

| Role | Default | Super Role | Description | Status |
|------|---------|------------|-------------|--------|
| admin | ❌ No | ❌ No | - | ✅ Correct |
| developer | ❌ No | ❌ No | - | ✅ Correct |
| elevated-developer | ❌ No | ❌ No | Developer with elevated privileges: sandbox execution, model management, GitHub Actions access | ✅ Correct |
| viewer | ✅ Yes | ❌ No | - | ✅ Correct |

**Analysis:**
- ✅ **viewer is Default** - New users get read-only access (secure by default)
- ✅ **admin is NOT SuperRole** - Prevents automatic inheritance (we use explicit role checks)
- ✅ **elevated-developer exists** - Successfully created with description
- ✅ **Role hierarchy maintained** - viewer < developer < elevated-developer < admin

**No changes needed** to OAuth2-Proxy roles unless you want to:
- Make admin a SuperRole (would inherit all permissions automatically - not recommended)
- Add descriptions to admin/developer/viewer roles (cosmetic only)

---

## ❌ What's Missing

### 1. Elevated-Developer API Key
**Location:** Settings > API Keys

**Current State:**
- ✅ `...2u0Dt_t` - Superkey (admin) - EXISTS
- ✅ `...tUOct` - Developer key - EXISTS  
- ✅ `...HHOx` - Developer key (duplicate?) - EXISTS
- ✅ `...rAoj` - Viewer key - EXISTS
- ❌ **Elevated Developer key** - MISSING

**Action Required:**
1. Go to Settings > API Keys
2. Click green **+ button** (top right)
3. Fill in:
   - **Description:** `[C]/[CD] Elevated Developer key`
   - Leave other fields default
4. Click **Save**
5. **IMPORTANT:** Copy the generated key immediately (it won't be shown again)
6. Add to `.env` file:
   ```bash
   FUSIONAUTH_CICD_ELEVATED_KEY=<paste-key-here>
   ```

**Why we can't create via API:**
- The main API key (`...2u0Dt_t`) doesn't have permission to create other API keys
- FusionAuth API keys require specific permissions endpoints
- UI creation is simpler and more reliable

---

## 🔧 Optional: Add elevated-developer to Other Applications

### Current Application Roles

**Grafana** (3 roles):
- admin (SuperRole: true)
- user
- readonly (Default: true)

**MLflow** (3 roles):
- admin (SuperRole: true)
- user
- readonly (Default: true)

**Ray Compute** (3 roles):
- admin (SuperRole: true)
- developer
- viewer (Default: true)

**FusionAuth** (37 roles - system app)

### Should We Add elevated-developer to These Apps?

#### Option A: Keep Current (Recommended)
**Pros:**
- Simpler configuration
- OAuth2-Proxy role is sufficient for Traefik auth
- Applications don't need to know about elevated-developer
- Role-auth middleware handles all access control

**Cons:**
- Can't assign elevated-developer directly to apps
- No per-application role differentiation

**Recommendation:** ✅ **Use this approach**

#### Option B: Add elevated-developer to Each App
**Pros:**
- Per-application role assignment
- More granular control (e.g., elevated in MLflow but not Ray)
- Future flexibility

**Cons:**
- More configuration overhead
- Must maintain consistency across apps
- Requires updating each app individually

**Steps if you choose Option B:**

1. **MLflow** (recommended - for model management):
   ```
   Applications > MLflow > Manage Roles > + Add Role
   Name: elevated-developer
   Description: Model management and experiment automation
   ```

2. **Ray Compute** (recommended - for job control):
   ```
   Applications > Ray Compute > Manage Roles > + Add Role
   Name: elevated-developer
   Description: Advanced job submission and resource management
   ```

3. **Grafana** (optional - developer role sufficient):
   ```
   Skip - developer role already provides full access
   ```

**Recommendation:** ⚠️ **Skip for now, add later if needed**

---

## 🎯 Default and SuperRole Settings

### What These Mean

**Default Role (✅ checked):**
- Automatically assigned to new users
- Only ONE role per application should be default
- Currently: `viewer` ✅ (correct - secure by default)

**Super Role (crown icon):**
- Automatically inherits ALL permissions
- Bypasses role checks
- Currently: None in OAuth2-Proxy ✅ (correct - explicit checks preferred)

### Should We Change These?

#### viewer (currently Default: true)
**Recommendation:** ✅ **Keep as Default**
- Secure by default (minimal access)
- Users must request upgrades
- Prevents accidental admin access

**Alternative:**
- Make `developer` default for trusted domains (requires email verification)
- Less secure but more convenient

#### admin (currently SuperRole: false)
**Recommendation:** ✅ **Keep SuperRole: false**
- We use explicit role checks in role-auth middleware
- SuperRole would bypass our middleware logic
- Better control with explicit checks

**Alternative:**
- Enable SuperRole if you want admin to automatically pass all checks
- Would simplify some configurations but reduces control

---

## 📋 Step-by-Step Checklist

### Phase 1: Create API Key (REQUIRED)
- [ ] Go to FusionAuth Admin UI: http://localhost:9011/admin
- [ ] Navigate to Settings > API Keys (left sidebar)
- [ ] Click green **+ button**
- [ ] Set Description: `[C]/[CD] Elevated Developer key`
- [ ] Click **Save**
- [ ] **Copy the generated key** (you only see it once!)
- [ ] Add to `.env`:
  ```bash
  FUSIONAUTH_CICD_ELEVATED_KEY=<paste-key-here>
  ```

### Phase 2: Verify .env Configuration (REQUIRED)
```bash
# Check these keys exist in .env:
grep FUSIONAUTH_CICD .env

# Should show:
# FUSIONAUTH_CICD_SUPER_KEY=V4dhPDS9jf0l_9SQQ_L9_kO_GfFijiG8xvM9a5sufdbGm8aCOLJtUOct
# FUSIONAUTH_CICD_ELEVATED_KEY=<new-key-you-just-created>
# FUSIONAUTH_CICD_DEVELOPER_KEY=AH_zDZdLqGZmKCRYGfNiE-1kY82GTgnNsqp62IOv-ZCwR0c5ZStiHHOx
# FUSIONAUTH_CICD_VIEWER_KEY=QJ5Dfsk2dfQnJ9EAtpn9wz_O9TBIlkw3miR6wVLRYN2vW__3VW1jrAoj
```

### Phase 3: Test Role-Based Access (REQUIRED)
```bash
# Export all keys for testing
export VIEWER_API_KEY=$(grep FUSIONAUTH_CICD_VIEWER_KEY .env | cut -d= -f2)
export DEVELOPER_API_KEY=$(grep FUSIONAUTH_CICD_DEVELOPER_KEY .env | cut -d= -f2)
export ELEVATED_DEVELOPER_API_KEY=$(grep FUSIONAUTH_CICD_ELEVATED_KEY .env | cut -d= -f2)
export ADMIN_API_KEY=$(grep FUSIONAUTH_CICD_SUPER_KEY .env | cut -d= -f2)

# Run comprehensive tests
./scripts/test-role-auth.sh
```

### Phase 4: Test Sandbox Execution (REQUIRED)
```bash
# Test with elevated-developer key
curl -X POST http://localhost/api/agent/v1/agent/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ELEVATED_DEVELOPER_API_KEY" \
  -d '{
    "user_id": "test-elevated",
    "session_id": "sandbox-test-1",
    "task": "Write and execute a Python function that returns the square of 5",
    "category": "coding",
    "max_iterations": 1
  }' | jq '.'

# Should succeed with code execution
# Look for tool_results with sandbox output
```

### Phase 5: Add Roles to Other Apps (OPTIONAL)
- [ ] If needed, add elevated-developer to MLflow
- [ ] If needed, add elevated-developer to Ray Compute
- [ ] Update kickstart.json for future deployments

### Phase 6: Update Documentation (REQUIRED)
- [ ] Update AUTH_FLOW_AND_USER_ACCESS.md with 4-role hierarchy
- [ ] Update ROLE_MAPPING_STRATEGY.md with verified config
- [ ] Clean up PHASE2_PRIORITY_ANALYSIS.md (keep Option 2 only)

---

## 🔍 Verification Commands

### Check Role Configuration
```bash
# List all roles in OAuth2-Proxy app
docker exec fusionauth curl -s -X GET \
  "http://localhost:9011/api/application/acda34f0-7cf2-40eb-9cba-7cb0048857d3" \
  -H "Authorization: $(grep FUSIONAUTH_API_KEY .env | head -1 | cut -d= -f2)" \
  | jq '.application.roles[] | {name: .name, default: .isDefault, super: .isSuperRole}'

# Expected output:
# {"name":"admin","default":false,"super":false}
# {"name":"developer","default":false,"super":false}
# {"name":"elevated-developer","default":false,"super":false}
# {"name":"viewer","default":true,"super":false}
```

### Check API Keys Exist
```bash
# Verify all 4 keys are in .env
grep -E "FUSIONAUTH_CICD_(SUPER|ELEVATED|DEVELOPER|VIEWER)_KEY" .env | wc -l
# Should output: 4
```

### Check Middleware Configuration
```bash
# Verify role-auth middleware knows about elevated-developer
docker exec role-auth cat /etc/nginx/nginx.conf | grep -A 2 "elevated-developer"

# Should show the /auth/elevated-developer location block
```

---

## 🚨 Common Issues

### Issue: "Can't create elevated-developer API key via UI"
**Solution:** Make sure you're logged in as admin user, not using an API key

### Issue: "API key doesn't work after creation"
**Solution:** API keys in FusionAuth don't have user context - they're for API access only. For role-based testing, you need user JWT tokens. The CI/CD keys are for automation, not for role simulation.

**For role testing, use OAuth2 flow:**
```bash
# This is why we test via curl with the keys -
# FusionAuth translates API keys to appropriate access
```

### Issue: "How do API keys map to roles?"
**Answer:** FusionAuth API keys DON'T have roles directly. Instead:
1. API keys have permissions (endpoints they can access)
2. For role-based access, OAuth2-Proxy extracts roles from user JWT
3. Our CI/CD keys are named by role for organization only

**For actual role testing:**
- Create test users in FusionAuth
- Assign them different roles
- Login via OAuth2 and test

---

## 📊 Final Configuration Summary

```
┌─────────────────────────────────────────────────────────────┐
│ OAuth2-Proxy Application Roles (Correct ✅)                 │
├─────────────────────────────────────────────────────────────┤
│ viewer (Default)           - Read-only, monitoring          │
│ developer                  - ML workflows, no sandboxes     │
│ elevated-developer         - Developer + sandboxes          │
│ admin                      - Full platform access           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ API Keys (3/4 Complete)                                      │
├─────────────────────────────────────────────────────────────┤
│ ✅ Superkey              - FUSIONAUTH_CICD_SUPER_KEY        │
│ ❌ Elevated Developer    - FUSIONAUTH_CICD_ELEVATED_KEY 📝  │
│ ✅ Developer             - FUSIONAUTH_CICD_DEVELOPER_KEY    │
│ ✅ Viewer                - FUSIONAUTH_CICD_VIEWER_KEY       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Next Action: Create elevated-developer API key via UI       │
│ Then: Update .env, test auth, test sandboxes                │
└─────────────────────────────────────────────────────────────┘
```

---

**Created:** December 7, 2025  
**Status:** Waiting for elevated-developer API key creation  
**Blocker:** Must use FusionAuth UI to create API key (can't use existing API key permissions)
