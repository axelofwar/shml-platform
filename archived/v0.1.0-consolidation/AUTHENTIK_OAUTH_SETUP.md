# Authentik OAuth Configuration Guide

## Overview

This guide walks through configuring Authentik as an OAuth 2.0/OIDC provider for the ML Platform, enabling production-ready authentication for remote access to MLflow, Ray Compute, and other services.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│   Client    │────▶│   Traefik    │────▶│  ML Platform   │
│  (Remote)   │     │  (Gateway)   │     │   Services     │
└─────────────┘     └──────────────┘     └────────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │  Authentik   │
                    │   (OAuth)    │
                    └──────────────┘
```

## Prerequisites

- ML Platform running (services accessible)
- Admin access to Authentik web UI
- Domain name or static IP for callback URLs
- SSL/TLS certificates (recommended for production)

## Quick Start

### 1. Access Authentik Admin Interface

```bash
# Authentik is accessible on:
http://localhost:9000
# Or via LAN:
http://localhost:9000
```

**Default credentials** (CHANGE IMMEDIATELY):
- Username: `akadmin`
- Password: Set during initial setup

### 2. Initial Setup

1. **First Login**: Navigate to http://localhost:9000
2. **Complete Setup Wizard**:
   - Set admin email
   - Create strong admin password
   - Configure default tenant

### 3. Create OAuth Provider for MLflow

#### Step 3.1: Create Application

1. Navigate to **Applications** → **Applications** → **Create**
2. Configure:
   - **Name**: `MLflow Tracking Server`
   - **Slug**: `mlflow`
   - **Group**: `Machine Learning Platform`
   - **Policy Engine Mode**: `ANY` (for development) or `ALL` (for production)

#### Step 3.2: Create OAuth Provider

1. Navigate to **Applications** → **Providers** → **Create**
2. Select **OAuth2/OpenID Provider**
3. Configure:

   **Basic Configuration:**
   ```
   Name: MLflow OAuth Provider
   Authorization Flow: implicit-consent
   Client Type: Confidential
   ```

   **URLs:**
   ```
   Redirect URIs:
     - http://localhost/mlflow/oauth/callback
     - http://localhost/mlflow/oauth/callback
     - http://${TAILSCALE_IP}/mlflow/oauth/callback  # VPN

   Signing Key: authentik Self-signed Certificate (auto-generated)
   ```

   **Scopes:**
   ```
   - openid
   - profile
   - email
   - offline_access
   ```

   **Advanced Settings:**
   ```
   Access Token Validity: 1 hour
   Refresh Token Validity: 7 days
   Include Claims in ID Token: Yes
   ```

#### Step 3.3: Link Provider to Application

1. Go back to **Applications** → **MLflow Tracking Server**
2. **Provider**: Select `MLflow OAuth Provider`
3. **Launch URL**: `http://localhost/mlflow/`
4. Save

#### Step 3.4: Capture OAuth Credentials

After creating the provider, note these values:
```
Client ID: <generated-client-id>
Client Secret: <generated-client-secret>
```

### 4. Create OAuth Provider for Ray Compute

Repeat steps 3.1-3.4 with these values:

```
Application Name: Ray Compute Platform
Slug: ray-compute
Provider Name: Ray Compute OAuth Provider

Redirect URIs:
  - http://localhost/ray/oauth/callback
  - http://localhost/ray/oauth/callback
  - http://${TAILSCALE_IP}/ray/oauth/callback

Launch URL: http://localhost/ray/
```

### 5. Configure Services to Use OAuth

#### MLflow Configuration

Create/update `.env` file in project root:

```bash
# MLflow OAuth Settings
MLFLOW_OAUTH_ENABLED=true
MLFLOW_OAUTH_PROVIDER=authentik
MLFLOW_OAUTH_CLIENT_ID=<mlflow-client-id>
MLFLOW_OAUTH_CLIENT_SECRET=<mlflow-client-secret>
MLFLOW_OAUTH_AUTHORIZATION_URL=http://localhost:9000/application/o/authorize/
MLFLOW_OAUTH_TOKEN_URL=http://authentik-server:9000/application/o/token/
MLFLOW_OAUTH_USERINFO_URL=http://authentik-server:9000/application/o/userinfo/
MLFLOW_OAUTH_REDIRECT_URI=http://localhost/mlflow/oauth/callback
MLFLOW_OAUTH_SCOPES=openid profile email
```

#### Ray Compute Configuration

Add to `.env`:

```bash
# Ray Compute OAuth Settings
RAY_OAUTH_ENABLED=true
RAY_OAUTH_PROVIDER=authentik
RAY_OAUTH_CLIENT_ID=<ray-compute-client-id>
RAY_OAUTH_CLIENT_SECRET=<ray-compute-client-secret>
RAY_OAUTH_AUTHORIZATION_URL=http://localhost:9000/application/o/authorize/
RAY_OAUTH_TOKEN_URL=http://authentik-server:9000/application/o/token/
RAY_OAUTH_USERINFO_URL=http://authentik-server:9000/application/o/userinfo/
RAY_OAUTH_REDIRECT_URI=http://localhost/ray/oauth/callback
RAY_OAUTH_SCOPES=openid profile email
```

### 6. Update docker-compose.yml

Add environment variables to services:

```yaml
mlflow-api:
  environment:
    # ... existing vars ...
    - OAUTH_ENABLED=${MLFLOW_OAUTH_ENABLED:-false}
    - OAUTH_CLIENT_ID=${MLFLOW_OAUTH_CLIENT_ID}
    - OAUTH_CLIENT_SECRET=${MLFLOW_OAUTH_CLIENT_SECRET}
    - OAUTH_AUTHORIZATION_URL=${MLFLOW_OAUTH_AUTHORIZATION_URL}
    - OAUTH_TOKEN_URL=${MLFLOW_OAUTH_TOKEN_URL}
    - OAUTH_USERINFO_URL=${MLFLOW_OAUTH_USERINFO_URL}
    - OAUTH_REDIRECT_URI=${MLFLOW_OAUTH_REDIRECT_URI}

ray-compute-api:
  environment:
    # ... existing vars ...
    - OAUTH_ENABLED=${RAY_OAUTH_ENABLED:-false}
    - OAUTH_CLIENT_ID=${RAY_OAUTH_CLIENT_ID}
    - OAUTH_CLIENT_SECRET=${RAY_OAUTH_CLIENT_SECRET}
    - OAUTH_AUTHORIZATION_URL=${RAY_OAUTH_AUTHORIZATION_URL}
    - OAUTH_TOKEN_URL=${RAY_OAUTH_TOKEN_URL}
    - OAUTH_USERINFO_URL=${RAY_OAUTH_USERINFO_URL}
    - OAUTH_REDIRECT_URI=${RAY_OAUTH_REDIRECT_URI}
```

### 7. Configure Traefik ForwardAuth (Recommended)

For centralized authentication at the gateway level:

#### Create Authentik Proxy Provider

1. **Applications** → **Providers** → **Create**
2. Select **Proxy Provider**
3. Configure:
   ```
   Name: ML Platform Gateway Proxy
   Authorization Flow: default-provider-authorization-implicit-consent
   Type: Forward auth (single application)
   External host: http://localhost
   ```

#### Update Traefik Configuration

Add to `traefik/dynamic/authentik.yml`:

```yaml
http:
  middlewares:
    authentik:
      forwardAuth:
        address: http://authentik-server:9000/outpost.goauthentik.io/auth/traefik
        trustForwardHeader: true
        authResponseHeaders:
          - X-authentik-username
          - X-authentik-groups
          - X-authentik-email
          - X-authentik-name
          - X-authentik-uid

  routers:
    # Apply to MLflow
    mlflow-ui:
      middlewares:
        - authentik
        - mlflow-stripprefix

    # Apply to Ray
    ray-dashboard:
      middlewares:
        - authentik
        - ray-stripprefix
```

### 8. Restart Services

```bash
./stop_all.sh
./start_all.sh
```

## User Management

### Create User Accounts

1. Navigate to **Directory** → **Users** → **Create**
2. Configure:
   ```
   Username: researcher1
   Name: Research User
   Email: researcher@example.com
   Password: (set strong password)
   Groups: ml-platform-users
   ```

### Create Groups

1. Navigate to **Directory** → **Groups** → **Create**
2. Example groups:
   ```
   - ml-platform-admins (full access)
   - ml-platform-users (read/write experiments)
   - ml-platform-viewers (read-only)
   ```

### Assign Group Permissions

1. Navigate to **Applications** → **MLflow Tracking Server**
2. **Policy Bindings** → **Create Binding**
3. Configure:
   ```
   Policy: Group-based policy
   Group: ml-platform-users
   Order: 10
   ```

## Advanced Configuration

### LDAP/AD Integration

For enterprise environments with existing LDAP/Active Directory:

1. **Directory** → **Federation** → **Create**
2. Select **LDAP Source**
3. Configure:
   ```
   Name: Corporate LDAP
   Server URI: ldaps://ldap.company.com:636
   Bind CN: cn=svc-authentik,ou=services,dc=company,dc=com
   Bind Password: <service-account-password>
   Base DN: dc=company,dc=com
   User Object Filter: (objectClass=person)
   Group Object Filter: (objectClass=group)
   ```

### Multi-Factor Authentication (MFA)

1. **Flows** → **default-authentication-flow** → **Edit**
2. Add **MFA Validation Stage**:
   ```
   Device Classes:
     - TOTP (Time-based OTP)
     - WebAuthn (Hardware keys)
   ```

### Email Notifications

Configure SMTP for password resets and notifications:

1. **System** → **Settings** → **Email**
2. Configure:
   ```
   Host: smtp.gmail.com
   Port: 587
   Use TLS: Yes
   Username: notifications@company.com
   Password: <app-password>
   From Address: ML Platform <noreply@company.com>
   ```

## Security Best Practices

### 1. Change Default Credentials

```bash
# Change Authentik admin password immediately
# Navigate to: Admin Interface → User Settings → Change Password
```

### 2. Enable HTTPS

Generate SSL certificates:

```bash
# For production, use Let's Encrypt or company CA
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout authentik.key -out authentik.crt \
  -days 365 -subj "/CN=${SERVER_IP}"
```

Update docker-compose.yml:

```yaml
authentik-server:
  ports:
    - "9443:9443"
  volumes:
    - ./certs/authentik.crt:/certs/cert.pem:ro
    - ./certs/authentik.key:/certs/key.pem:ro
  environment:
    - AUTHENTIK_LISTEN__HTTPS=0.0.0.0:9443
    - AUTHENTIK_LISTEN__HTTP=0.0.0.0:9000
```

### 3. Use Strong Secret Keys

Generate cryptographically secure keys:

```bash
# Generate Authentik secret key
openssl rand -base64 50

# Add to .env
AUTHENTIK_SECRET_KEY=<generated-key>
```

### 4. Configure Session Timeouts

1. **Flows** → **default-provider-authorization-implicit-consent**
2. **Session valid not after**: 8 hours
3. **Refresh Token Validity**: 7 days

### 5. Enable Audit Logging

All authentication events are logged automatically:

1. **Events** → **Logs** (view all auth events)
2. Monitor for:
   - Failed login attempts
   - Permission changes
   - User creation/deletion

## Testing OAuth Flow

### Manual Test

1. **Logout** from all services
2. Navigate to: `http://localhost/mlflow/`
3. Should redirect to: `http://localhost:9000/application/o/authorize/...`
4. **Login** with test credentials
5. Should redirect back to MLflow authenticated

### Programmatic Test (Python)

```python
import requests
from requests_oauthlib import OAuth2Session

# Configuration
client_id = "your-client-id"
client_secret = "your-client-secret"
authorization_base_url = "http://localhost:9000/application/o/authorize/"
token_url = "http://localhost:9000/application/o/token/"
redirect_uri = "http://localhost/mlflow/oauth/callback"

# OAuth flow
oauth = OAuth2Session(client_id, redirect_uri=redirect_uri)
authorization_url, state = oauth.authorization_url(authorization_base_url)

print(f"Visit: {authorization_url}")
# User logs in and authorizes
redirect_response = input("Paste redirect URL: ")

# Exchange code for token
token = oauth.fetch_token(
    token_url,
    authorization_response=redirect_response,
    client_secret=client_secret
)

print(f"Access Token: {token['access_token']}")

# Use token to access MLflow API
headers = {"Authorization": f"Bearer {token['access_token']}"}
response = requests.get("http://localhost/api/v1/health", headers=headers)
print(f"API Response: {response.json()}")
```

## Remote Access via LAN

### Client Configuration

On remote machines accessing via LAN (10.0.0.x):

```python
import mlflow
import os

# Set tracking URI
mlflow.set_tracking_uri("http://localhost/mlflow")

# Configure OAuth (if using programmatic access)
os.environ["MLFLOW_TRACKING_TOKEN"] = "<your-oauth-token>"

# Now use MLflow normally
mlflow.set_experiment("remote-experiment")
with mlflow.start_run():
    mlflow.log_param("optimizer", "adam")
    mlflow.log_metric("accuracy", 0.95)
```

### Browser-based Access

Users can access via browser at:
- **MLflow UI**: http://localhost/mlflow/
- **Ray Dashboard**: http://localhost/ray/
- **Grafana (MLflow)**: http://localhost/mlflow-grafana/
- **Grafana (Ray)**: http://localhost/ray-grafana/

All will redirect through Authentik for authentication.

## Troubleshooting

### Common Issues

#### Issue: "Redirect URI mismatch"

**Solution**: Ensure redirect URIs in Authentik exactly match what the client sends:
```bash
# Check Authentik Provider settings
Redirect URIs:
  - http://localhost/mlflow/oauth/callback  # Must match exactly
  - http://localhost/ray/oauth/callback
```

#### Issue: "Invalid client credentials"

**Solution**: Verify client ID and secret are correct:
```bash
# Re-check provider configuration
Applications → MLflow OAuth Provider → Credentials
```

#### Issue: Token expired

**Solution**: Implement token refresh:
```python
from requests_oauthlib import OAuth2Session

oauth = OAuth2Session(client_id, token=token)
# Automatically refreshes token when expired
response = oauth.get("http://localhost/api/v1/health")
```

#### Issue: CORS errors in browser

**Solution**: Add CORS headers to Authentik responses:
```yaml
# In Authentik provider settings
CORS Allowed Origins:
  - http://localhost
  - http://localhost
  - http://${TAILSCALE_IP}
```

### Debug Logging

Enable debug logging:

```yaml
# docker-compose.yml - authentik-server
environment:
  - AUTHENTIK_LOG_LEVEL=debug
  - AUTHENTIK_DEBUG=true
```

View logs:
```bash
docker logs -f authentik-server
```

## Next Steps

1. ✅ Authentik OAuth providers configured
2. ✅ Services configured to use OAuth
3. ✅ User accounts and groups created
4. ✅ Test authentication flow
5. ⏭️ Enable ForwardAuth for centralized authentication
6. ⏭️ Configure HTTPS for production
7. ⏭️ Set up LDAP integration (if needed)
8. ⏭️ Enable MFA for enhanced security

## References

- [Authentik Documentation](https://goauthentik.io/docs/)
- [OAuth 2.0 RFC](https://datatracker.ietf.org/doc/html/rfc6749)
- [OpenID Connect Specification](https://openid.net/specs/openid-connect-core-1_0.html)
- [Traefik ForwardAuth](https://doc.traefik.io/traefik/middlewares/http/forwardauth/)

## Support

For issues or questions:
- Check Authentik logs: `docker logs authentik-server`
- Review Traefik logs: `docker logs ml-platform-traefik`
- Consult service logs: `./view_logs.sh mlflow-api`
