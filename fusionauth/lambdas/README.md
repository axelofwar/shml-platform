# FusionAuth Lambda Configuration Guide

**Last Updated:** 2025-12-06

This directory contains FusionAuth Lambda functions that customize authentication behavior.

---

## ⚠️ CRITICAL: JWT Populate Lambda

**The JWT Populate lambda is MANDATORY for OAuth2-Proxy role-based access control to work.**

Without it:
- Users with assigned roles still experience redirect loops
- OAuth2-Proxy receives empty `X-Auth-Request-Groups` header
- Role-auth middleware always returns 403 Forbidden
- No roles appear in JWT tokens (even when assigned in FusionAuth)

**Symptom:** Users have roles in FusionAuth but keep getting redirected to sign-in page.

---

## Lambda Files

### 1. `jwt-populate-roles.js` - JWT Populate Lambda (REQUIRED)

**Purpose:** Include user's application roles in the JWT `id_token` as a "roles" claim.

**Type:** JWT Populate

**Trigger:** Every token generation (login, refresh, etc.)

**Configuration Steps:**

1. **Create the Lambda in FusionAuth:**
   ```
   FusionAuth Admin → Settings → Lambdas → ➕ Add Lambda

   Name: JWT Populate - Include Roles Claim
   Type: JWT populate
   Enabled: ✓ (checked)
   Debug: ✓ (checked, for initial setup)

   Copy-paste code from: fusionauth/lambdas/jwt-populate-roles.js

   Click: Save
   ```

2. **Attach Lambda to Tenant:**
   ```
   FusionAuth Admin → Tenants → ML Platform → Edit (pencil icon)

   Scroll to "JWT" section

   Id Token populate lambda: ▼ JWT Populate - Include Roles Claim

   Click: Save (💾 icon at top right)
   ```

3. **Verify Lambda is Active:**
   ```bash
   # Check FusionAuth Event Log
   FusionAuth Admin → System → Event Log

   # Look for: "Added roles to JWT for user <email>: viewer"
   # Or: "User <email> has no roles for application <id>" (warning)
   ```

4. **Test the Lambda:**
   ```bash
   # 1. Sign out completely
   # Clear browser cookies for: ${PUBLIC_DOMAIN}

   # 2. Sign in again

   # 3. Decode JWT to verify roles claim exists
   # Browser DevTools → Application → Cookies → _sfml_oauth2
   # Copy JWT value → Paste at jwt.io

   # Should see in payload:
   {
     "email": "user@example.com",
     "roles": ["viewer"],        # ← This is what OAuth2-Proxy reads
     "role": "viewer",            # ← Backup as comma-separated string
     ...
   }
   ```

---

### 2. `google-registration-default-role.js` - Google Reconcile Lambda (OPTIONAL)

**Purpose:** Automatically assign "viewer" role to new users signing in via Google OAuth.

**Type:** Google Reconcile

**Trigger:** Only when users sign in with Google (not email/password)

**Why Optional:** Manual role assignment in FusionAuth admin panel works fine. This lambda just automates the process for new users.

**Configuration Steps:**

1. **Create the Lambda:**
   ```
   FusionAuth Admin → Settings → Lambdas → ➕ Add Lambda

   Name: Google Registration - Assign Default Role
   Type: Google reconcile
   Enabled: ✓
   Debug: ✓ (for initial setup)

   Copy-paste code from: fusionauth/lambdas/google-registration-default-role.js

   Click: Save
   ```

2. **Attach Lambda to Google Identity Provider:**
   ```
   FusionAuth Admin → Settings → Identity Providers → Google → Edit

   Scroll to "Options" section

   Reconcile lambda: ▼ Google Registration - Assign Default Role

   Click: Save
   ```

3. **Verify Lambda Works:**
   ```bash
   # Test with a new Google account (not previously registered)

   # After sign-in, check:
   FusionAuth Admin → Users → [new user] → Registrations tab

   # OAuth2-Proxy registration should show "viewer" role automatically
   ```

---

## Troubleshooting

### Issue: Lambda doesn't execute

**Check:**
1. Lambda is enabled (checkbox in lambda settings)
2. Lambda is attached to tenant (for JWT Populate) or identity provider (for Reconcile)
3. Debug mode is enabled in lambda settings
4. Check Event Log for errors: `FusionAuth Admin → System → Event Log`

**Common Errors:**
```javascript
// Syntax error in lambda code
SyntaxError: Unexpected token

// Solution: Check JavaScript syntax, missing braces, etc.
```

### Issue: Roles still not appearing in JWT

**Diagnosis:**
```bash
# 1. Verify user has roles assigned
FusionAuth Admin → Users → [user] → Registrations → OAuth2-Proxy
# Should show checked roles (viewer, developer, etc.)

# 2. Verify JWT Populate lambda is attached to tenant
FusionAuth Admin → Tenants → ML Platform → Edit
# "Id Token populate lambda" should show lambda name

# 3. Check lambda execution in Event Log
FusionAuth Admin → System → Event Log
# Filter by: Type = "Debug" or "Information"
# Should see: "Added roles to JWT for user..."

# 4. Decode a fresh JWT
# Sign out, clear cookies, sign in again
# Decode _sfml_oauth2 cookie at jwt.io
# Look for "roles": [...] in payload
```

**Solution:**
- If lambda not in Event Log → Lambda not attached to tenant
- If "no roles" warning → User registration missing roles
- If JWT still missing roles → Lambda has syntax error (check Event Log)

### Issue: OAuth redirect loop persists after adding lambda

**Diagnosis:**
```bash
# Users MUST sign out and sign back in for new JWT with roles
# Old JWT tokens (before lambda) are still valid but missing roles

# Force fresh tokens:
# 1. Clear browser cookies for domain
# 2. Or restart oauth2-proxy container
docker restart oauth2-proxy
```

---

## Lambda Development Tips

### Testing Lambda Code

FusionAuth provides a **Lambda test console**:

```
FusionAuth Admin → Settings → Lambdas → [Your Lambda] → Test tab

# Provide sample input:
{
  "user": {
    "email": "test@example.com",
    "id": "test-user-id"
  },
  "registration": {
    "applicationId": "app-id",
    "roles": ["viewer", "developer"]
  }
}

# Click "Run" to see output and console.log() messages
```

### Debugging Techniques

```javascript
// Use console.log(), console.info(), console.warn() in lambda
// Output appears in FusionAuth Event Log (if Debug enabled)

function populate(jwt, user, registration) {
  console.info('=== JWT Populate Lambda Start ===');
  console.info('User: ' + user.email);
  console.info('Application: ' + jwt.aud);
  console.info('Registration roles: ' + JSON.stringify(registration?.roles));

  // Your lambda logic here

  console.info('JWT roles claim: ' + JSON.stringify(jwt.roles));
  console.info('=== JWT Populate Lambda End ===');
}
```

### Lambda Execution Order

**For Google OAuth sign-in:**
1. **Google Reconcile Lambda** (if configured) - assigns roles to registration
2. **JWT Populate Lambda** (required) - adds roles to JWT token
3. Token issued to OAuth2-Proxy
4. OAuth2-Proxy reads `roles` claim as groups
5. Traefik forwardAuth passes `X-Auth-Request-Groups` header
6. role-auth middleware validates roles

---

## Security Notes

### Lambda Permissions

Lambdas have **full access** to FusionAuth API and can:
- Read/modify user data
- Assign roles
- Revoke registrations
- Access all tenant data

**Best Practices:**
- Keep lambdas simple and focused
- Avoid external API calls (can't make HTTP requests anyway)
- Log all changes for audit trail
- Test thoroughly before production use

### Lambda Performance

- Lambdas run **synchronously** during authentication
- Slow lambdas delay user sign-in
- Keep execution time <100ms
- Avoid complex logic or loops

---

## Quick Reference

### Lambda Types Used in This Project

| Lambda Type | Purpose | File | Status |
|-------------|---------|------|--------|
| **JWT Populate** | Add roles to id_token | `jwt-populate-roles.js` | ✅ REQUIRED |
| **Google Reconcile** | Assign default role to Google users | `google-registration-default-role.js` | ⚪ OPTIONAL |

### Environment Setup Checklist

- [ ] JWT Populate lambda created in FusionAuth
- [ ] JWT Populate lambda attached to tenant
- [ ] Lambda debug mode enabled (for setup)
- [ ] Test user has roles assigned in FusionAuth
- [ ] Users cleared cookies and signed in again
- [ ] JWT decoded shows `"roles": ["viewer"]` claim
- [ ] OAuth2-Proxy logs show roles in X-Auth-Request-Groups
- [ ] Homer/Grafana accessible without redirect loop

---

## Additional Resources

- **FusionAuth Lambda Documentation:** https://fusionauth.io/docs/v1/tech/lambdas/
- **JWT.io Debugger:** https://jwt.io (decode tokens to verify claims)
- **OAuth2-Proxy Docs:** https://oauth2-proxy.github.io/oauth2-proxy/

---

**For urgent OAuth issues, check:**
1. `docs/internal/TROUBLESHOOTING.md` - OAuth redirect loop section
2. `deploy/compose/docker-compose.infra.yml` - OAuth2-Proxy configuration
3. FusionAuth Event Log - Lambda execution logs
