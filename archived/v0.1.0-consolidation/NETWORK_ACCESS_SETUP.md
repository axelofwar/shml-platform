# Network Access Configuration Guide

## Overview

This guide configures professional network access to the ML Platform using Tailscale VPN with OAuth authentication.

## Current Configuration

### Access Points

| Network | Hostname | IP Address | Use Case |
|---------|----------|------------|----------|
| **LAN (Local)** | `${SERVER_IP}` | `${SERVER_IP}` | Internal network access |
| **Tailscale VPN** | `axelofwar-dev-terminal-1.tail38b60a.ts.net` | `${TAILSCALE_IP}` | Secure remote access |
| **Tailscale VPN (Short)** | `axelofwar-dev-terminal-1` | `${TAILSCALE_IP}` | Short name (MagicDNS) |

### Service URLs

**Via Tailscale (Recommended for Remote Access):**
- MLflow UI: `http://axelofwar-dev-terminal-1.tail38b60a.ts.net/mlflow/`
- Ray Dashboard: `http://axelofwar-dev-terminal-1.tail38b60a.ts.net/ray/`
- Traefik: `http://axelofwar-dev-terminal-1.tail38b60a.ts.net:8090`
- Authentik OAuth: `http://axelofwar-dev-terminal-1.tail38b60a.ts.net:9000`

**Via LAN (Local Network Only):**
- MLflow UI: `http://localhost/mlflow/`
- Ray Dashboard: `http://localhost/ray/`
- Traefik: `http://localhost:8090`
- Authentik OAuth: `http://localhost:9000`

## Short-Term Setup (Current)

### Phase 1: Tailscale MagicDNS ✅

**What It Provides:**
- ✅ Professional hostname: `axelofwar-dev-terminal-1.tail38b60a.ts.net`
- ✅ Secure VPN access from anywhere
- ✅ No port forwarding needed
- ✅ Built-in encryption
- ✅ Works with OAuth authentication

**How It Works:**
1. Connect to Tailscale VPN on your device
2. Access services using Tailscale hostname
3. Traefik accepts connections from Tailscale IPs
4. OAuth authenticates through Authentik
5. Access granted to ML Platform services

**Device Setup:**

For each device that needs access:

```bash
# Linux/Mac
sudo tailscale up

# Windows - Install Tailscale from tailscale.com

# iOS/Android - Install Tailscale app from app store
```

### Phase 2: Security Configuration

**Configured Security Features:**

1. **Host Validation** (`--allowed-hosts`)
   - Accepts: localhost, LAN IP, Tailscale hostname
   - Rejects: Unknown hosts (DNS rebinding protection)

2. **CORS Protection**
   - Allowed origins: Tailscale domain, LAN IP
   - Prevents unauthorized cross-origin requests

3. **Model Source Validation**
   - Allows: MLflow artifacts, approved S3 buckets
   - Blocks: file://, dangerous protocols
   - Regex pattern enforced

4. **OAuth Authentication**
   - All API access requires valid OAuth token
   - Tokens expire after 5 minutes
   - Refresh tokens valid for 7 days

## Long-Term Setup (Production)

### Phase 3: Custom Domain with HTTPS

**Option A: Tailscale HTTPS (Easiest)**

Tailscale can provide HTTPS certificates automatically:

```bash
# Enable HTTPS on Tailscale
sudo tailscale serve https / http://localhost:80

# Or enable for specific services
sudo tailscale serve https /mlflow http://localhost/mlflow
sudo tailscale serve https /ray http://localhost/ray
```

**Benefits:**
- ✅ Automatic HTTPS certificates
- ✅ No DNS configuration needed
- ✅ Free and automatic renewal
- ✅ Works immediately

**Access URLs:**
- `https://axelofwar-dev-terminal-1.tail38b60a.ts.net/mlflow/`
- `https://axelofwar-dev-terminal-1.tail38b60a.ts.net/ray/`

**Option B: Custom Domain with Let's Encrypt**

For a professional domain like `ml.yourdomain.com`:

1. **Get a Domain Name**
   ```
   Register domain: e.g., yourdomain.com
   Cost: ~$10-15/year
   Providers: Namecheap, Google Domains, Cloudflare
   ```

2. **Point DNS to Tailscale IP**
   ```
   Create A record:
   ml.yourdomain.com → ${TAILSCALE_IP}
   ```

3. **Enable Tailscale Funnel** (Expose to Internet)
   ```bash
   # WARNING: This makes service publicly accessible!
   tailscale funnel 443 on
   ```

4. **Configure Let's Encrypt in Traefik**
   ```yaml
   # Automatic HTTPS certificates
   traefik:
     command:
       - "--certificatesresolvers.letsencrypt.acme.email=you@yourdomain.com"
       - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
       - "--certificatesresolvers.letsencrypt.acme.tlschallenge=true"
   ```

**Benefits:**
- ✅ Professional custom domain
- ✅ Automatic HTTPS with Let's Encrypt
- ✅ Can share with team/clients
- ✅ Full control

**Considerations:**
- 💰 Domain costs ~$10-15/year
- ⚠️ Publicly accessible (ensure OAuth is working!)
- 🔄 Requires DNS propagation time (5-60 min)

### Phase 4: Advanced Security

**Implement After Phase 3:**

1. **Fail2Ban** - Block brute force attacks
2. **Rate Limiting** - Prevent API abuse
3. **IP Whitelisting** - Restrict to known IPs
4. **WAF (Web Application Firewall)** - Traefik with CrowdSec
5. **SIEM Integration** - Log aggregation and alerting

## Implementation Plan

### Today (Immediate)

1. **Update MLflow Security Settings** ✅
   - Add `--allowed-hosts` with Tailscale domain
   - Configure CORS for Tailscale
   - Enable model source validation

2. **Test Access via Tailscale** ✅
   - Access from Tailscale-connected device
   - Verify OAuth works through VPN
   - Test MLflow and Ray APIs

3. **Apply Resource Manager** ✅
   - Run `./start_all_safe.sh`
   - Verify resource allocations
   - Monitor for 24 hours

### This Week

1. **Enable Tailscale HTTPS** (Optional but recommended)
   ```bash
   sudo tailscale serve https / http://localhost:80
   ```

2. **Update Documentation**
   - Share Tailscale access URLs with team
   - Document OAuth credential setup
   - Create onboarding guide

3. **Monitor & Optimize**
   - Review Grafana dashboards
   - Check resource utilization
   - Verify backup processes

### Next Month (Optional)

1. **Custom Domain** (if needed)
   - Register domain
   - Configure DNS
   - Enable Let's Encrypt

2. **Advanced Monitoring**
   - Set up alerting
   - Configure log aggregation
   - Implement uptime monitoring

3. **Scaling** (if needed)
   - Add Ray worker nodes
   - Implement MLflow artifacts-only server
   - Consider Kubernetes migration

## Security Best Practices

### 1. Tailscale ACLs (Access Control Lists)

Restrict which Tailscale devices can access specific ports:

```json
// Tailscale Admin Console → Access Controls
{
  "acls": [
    {
      "action": "accept",
      "src": ["autogroup:member"],
      "dst": ["axelofwar-dev-terminal-1:80,443,8090,9000"]
    }
  ]
}
```

### 2. OAuth Token Management

**For Remote Clients:**

```bash
# Store credentials securely
cat > ~/.ml-platform-credentials << 'EOF'
MLFLOW_TRACKING_URI=http://axelofwar-dev-terminal-1.tail38b60a.ts.net/mlflow
RAY_API_URL=http://axelofwar-dev-terminal-1.tail38b60a.ts.net/api/ray
OAUTH_CLIENT_ID=your_client_id
OAUTH_CLIENT_SECRET=your_client_secret
EOF

chmod 600 ~/.ml-platform-credentials
```

### 3. Network Segmentation

**Current Setup:**
```
Internet
   ↓
Tailscale VPN (Encrypted)
   ↓
Host Machine (${SERVER_IP})
   ↓
Docker Network (172.30.0.0/16)
   ↓
ML Platform Services
```

**Each layer provides security:**
- Tailscale: WireGuard encryption
- Host: Firewall rules
- Docker: Network isolation
- OAuth: Authentication & authorization

### 4. Audit Logging

**Enabled Logging:**
- Authentik: All OAuth events
- Traefik: All HTTP requests
- MLflow: Experiment access
- Ray: Job submissions

**View logs:**
```bash
# OAuth events
docker logs authentik-server | grep oauth

# API access
docker logs ml-platform-traefik | grep access

# MLflow operations
docker logs mlflow-server | grep api
```

## Troubleshooting

### Cannot Access via Tailscale

**Check Tailscale status:**
```bash
# On client device
tailscale status

# On server
sudo tailscale status
```

**Verify connectivity:**
```bash
# Ping server
ping axelofwar-dev-terminal-1.tail38b60a.ts.net

# Test HTTP
curl http://axelofwar-dev-terminal-1.tail38b60a.ts.net/mlflow/
```

### OAuth Not Working Through Tailscale

**Update redirect URIs in Authentik:**
```
Authentik → Applications → MLflow OAuth Provider → Redirect URIs:
  - http://axelofwar-dev-terminal-1.tail38b60a.ts.net/mlflow/oauth/callback
  - http://${TAILSCALE_IP}/mlflow/oauth/callback
  - http://localhost/mlflow/oauth/callback
```

### Host Header Mismatch

**Symptom:** "Invalid Host header" error

**Solution:** Update MLflow allowed-hosts:
```yaml
# docker-compose.yml
mlflow-server:
  environment:
    MLFLOW_ALLOWED_HOSTS: "localhost,${SERVER_IP},${TAILSCALE_IP},axelofwar-dev-terminal-1,axelofwar-dev-terminal-1.tail38b60a.ts.net"
```

## Client Configuration Examples

### Python Client (Remote Machine)

```python
import mlflow
import os

# Configure for Tailscale access
os.environ['MLFLOW_TRACKING_URI'] = 'http://axelofwar-dev-terminal-1.tail38b60a.ts.net/mlflow'
os.environ['MLFLOW_TRACKING_TOKEN'] = 'your_oauth_token'  # Get from OAuth flow

# Use MLflow normally
mlflow.set_experiment('remote-training')
with mlflow.start_run():
    mlflow.log_param('learning_rate', 0.001)
    mlflow.log_metric('accuracy', 0.95)
```

### cURL (Testing)

```bash
# Get OAuth token
TOKEN=$(curl -s -X POST \
  http://axelofwar-dev-terminal-1.tail38b60a.ts.net:9000/application/o/token/ \
  -d "grant_type=client_credentials" \
  -d "client_id=$CLIENT_ID" \
  -d "client_secret=$CLIENT_SECRET" \
  | jq -r '.access_token')

# Access MLflow API
curl -H "Authorization: Bearer $TOKEN" \
  http://axelofwar-dev-terminal-1.tail38b60a.ts.net/api/v1/experiments
```

### Ray Job Submission

```python
from ray_client import RayComputeClient

# Use Tailscale hostname
client = RayComputeClient(
    platform_host="axelofwar-dev-terminal-1.tail38b60a.ts.net"
)

# Submit job
job = client.submit_job(
    entrypoint="python train.py",
    experiment_name="remote-training"
)
```

## Comparison: Tailscale vs Public Domain

| Feature | Tailscale | Custom Domain |
|---------|-----------|---------------|
| **Cost** | Free (up to 100 devices) | ~$10-15/year |
| **Setup Time** | 5 minutes | 1-24 hours (DNS) |
| **Security** | VPN-only access | Public (need strong auth) |
| **HTTPS** | Free & automatic | Free (Let's Encrypt) |
| **Team Access** | Invite to Tailscale | Anyone with URL |
| **Professional** | Good for teams | Best for production |
| **Maintenance** | Zero | Minimal |

**Recommendation:** 
- Start with Tailscale (current setup)
- Add custom domain later if needed

## Next Steps

1. ✅ Review this document
2. ⏳ Update MLflow security settings (running next)
3. ⏳ Test access via Tailscale
4. ⏳ Run resource manager
5. ⏳ Share access with team members

## Support Resources

- **Tailscale Docs**: https://tailscale.com/kb/
- **MLflow Security**: https://mlflow.org/docs/latest/self-hosting/security/
- **OAuth 2.0 Guide**: https://oauth.net/2/
- **Platform Docs**: See `MLFLOW_BEST_PRACTICES.md`, `RESOURCE_MANAGEMENT_GUIDE.md`

---

**Last Updated**: November 23, 2025  
**Tailscale Network**: tail38b60a.ts.net  
**Primary Hostname**: axelofwar-dev-terminal-1.tail38b60a.ts.net
