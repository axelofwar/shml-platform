# Tailscale Reset Recovery Guide

## Overview

When Tailscale is reset (due to TPM lockout, re-authentication, or machine re-registration), several platform components need to be updated. This guide documents all the configuration points and how to recover.

## Prevention

The `start_all_safe.sh` script now includes a **pre-flight check** that detects Tailscale IP mismatches before starting services. If you see this error:

```
✗ TAILSCALE IP MISMATCH DETECTED!
  Current Tailscale IP:    100.x.x.x
  Configured in .env:      100.y.y.y
```

Run the recovery script before proceeding.

## Quick Recovery

Run the automated recovery script:
```bash
sudo ./scripts/recover-tailscale.sh
```

## What Changes After a Tailscale Reset

| Component | What Changes | What Stays Same |
|-----------|--------------|-----------------|
| Tailscale IP | New IP assigned (e.g., 100.x.x.x) | - |
| Hostname | Resets to machine name | Can force to `shml-platform` |
| Domain | Stays same if hostname matches | `<hostname>.<tailnet>.ts.net` |
| Funnel | Must be re-enabled | - |

## Configuration Files That Reference Tailscale

### Primary Configuration (Single Source of Truth)

**`.env`** - Main environment file
```bash
TAILSCALE_IP=100.66.26.115
PUBLIC_DOMAIN=shml-platform.tail38b60a.ts.net
```

### Files Using Environment Variables (Auto-Updated)

These files use `${PUBLIC_DOMAIN}` or `${TAILSCALE_IP}` and don't need manual updates:

- `docker-compose.infra.yml` - OAuth2-Proxy OIDC issuer, cookies, redirects, extra_hosts
- `mlflow-server/docker-compose.yml` - MLFLOW_ALLOWED_HOSTS
- `docker-compose.yml` - Main compose file

### Files That May Need Manual Updates

- `ray_compute/.env` - TAILSCALE_IP
- `mlflow-server/.env` - SERVER_TAILSCALE_IP

## Common Issues After Tailscale Reset

### 1. OAuth Login Loop (Sign In → Auth Success → Sign In again)

**Symptoms:**
- OAuth2 Proxy logs show `[AuthSuccess]` but user returns to sign-in page
- Browser shows 401 or 403 after successful authentication

**Causes & Fixes:**

| Cause | Fix |
|-------|-----|
| MLflow returns 403 (Host not allowed) | Add `PUBLIC_DOMAIN` to `MLFLOW_ALLOWED_HOSTS` in mlflow-server/docker-compose.yml |
| X-Forwarded-Proto not set (cookie issue) | Ensure `oauth2-proxy-headers` middleware is configured in Traefik |
| User registration not verified | Delete and recreate user registration in FusionAuth |
| FusionAuth redirect URIs wrong | Update OAuth app redirect URIs in FusionAuth admin |

### 2. MLflow Returns 403 Forbidden

**Symptoms:**
```
WARNING mlflow.server.fastapi_security: Rejected request with invalid Host header: <hostname>
```

**Fix:**
Ensure `MLFLOW_ALLOWED_HOSTS` includes `${PUBLIC_DOMAIN}`:
```yaml
MLFLOW_ALLOWED_HOSTS: "localhost,127.0.0.1,mlflow-server,...,${PUBLIC_DOMAIN}"
```

### 3. OAuth2 Proxy Can't Perform OIDC Discovery

**Symptoms:**
```
error performing request: Get "https://shml-platform.tail38b60a.ts.net/.well-known/openid-configuration": connection refused
```

**Fix:**
Add `extra_hosts` to oauth2-proxy in docker-compose.infra.yml:
```yaml
extra_hosts:
  - "shml-platform.tail38b60a.ts.net:${TAILSCALE_IP}"
```

### 4. Cookies Not Being Set (X-Forwarded-Proto Issue)

**Symptoms:**
- Auth succeeds but cookie not stored
- OAuth2 Proxy logs show `X-Forwarded-Proto:[http]` instead of `https`

**Fix:**
Ensure oauth2-proxy router has headers middleware:
```yaml
- "traefik.http.middlewares.oauth2-proxy-headers.headers.customrequestheaders.X-Forwarded-Proto=https"
- "traefik.http.routers.oauth2-proxy.middlewares=oauth2-proxy-headers"
```

## Systemd Services for Persistence

These services ensure Tailscale configuration persists across reboots:

```
/etc/systemd/system/tailscaled.service.d/no-tpm.conf  # Disables TPM
/etc/systemd/system/tailscale-hostname.service         # Sets hostname to shml-platform
/etc/systemd/system/tailscale-funnel.service          # Enables Funnel on boot
/etc/systemd/system/shml-platform.service             # Starts Docker containers
```

## Manual Recovery Steps

If the automated script fails, follow these steps:

### Step 1: Fix Tailscale Configuration
```bash
# Authenticate if needed
sudo tailscale up

# Set hostname (persists across restarts)
sudo tailscale set --hostname=shml-platform

# Enable Funnel
sudo tailscale funnel --set-path=/ --bg 80

# Get new IP
tailscale ip -4
```

### Step 2: Update Environment Files
```bash
# Edit .env with new IP
nano .env
# Update: TAILSCALE_IP=<new-ip>

# Also update sub-project .env files
nano ray_compute/.env
nano mlflow-server/.env
```

### Step 3: Restart Services
```bash
docker compose down
docker compose up -d
```

### Step 4: Verify FusionAuth OAuth Configuration

1. Go to FusionAuth Admin: `http://<tailscale-ip>:9011/admin/`
2. Navigate to Applications → OAuth2-Proxy
3. Verify Authorized Redirect URIs include:
   - `https://shml-platform.tail38b60a.ts.net/oauth2-proxy/callback`
4. Verify Authorized Origin URLs include:
   - `https://shml-platform.tail38b60a.ts.net`

### Step 5: Clear Browser State
- Clear cookies for `shml-platform.tail38b60a.ts.net`
- Try incognito/private window for testing

## Verification Commands

```bash
# Check Tailscale status
tailscale status

# Test OIDC discovery
curl -sk https://shml-platform.tail38b60a.ts.net/.well-known/openid-configuration | jq .issuer

# Check OAuth2 Proxy
docker logs oauth2-proxy 2>&1 | tail -20

# Check MLflow allowed hosts
docker logs mlflow-server 2>&1 | grep "Allowed hosts"

# Test MLflow health
curl -sk https://shml-platform.tail38b60a.ts.net/mlflow/health
```

## Prevention: TPM Lockout

The TPM lockout occurs when BIOS settings change (like enabling DOCP/XMP). To prevent issues:

1. **Before BIOS Changes:**
   ```bash
   # Note current Tailscale state
   tailscale status
   tailscale ip -4
   ```

2. **TPM Workaround (Already Applied):**
   ```bash
   # /etc/systemd/system/tailscaled.service.d/no-tpm.conf
   [Service]
   Environment="TS_DEBUG_USE_TPM=false"
   ```

3. **After BIOS Changes:**
   ```bash
   # If Tailscale fails to start, clear state
   sudo systemctl stop tailscaled
   sudo rm -rf /var/lib/tailscale/*
   sudo systemctl start tailscaled
   sudo tailscale up
   sudo ./scripts/recover-tailscale.sh
   ```
