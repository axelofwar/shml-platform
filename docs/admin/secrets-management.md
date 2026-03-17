# Secrets Management

All sensitive credentials are stored as files in the `secrets/` directory and mounted into containers as Docker secrets.

---

## Directory Structure

```
secrets/
├── README.md                           # Documentation (tracked in git)
├── shared_db_password.txt              # PostgreSQL shared password
├── grafana_password.txt                # Grafana admin password
├── fusionauth_db_password.txt          # FusionAuth database password
├── oauth2_proxy_cookie_secret.txt      # OAuth2-Proxy cookie encryption
├── ray_db_password.txt                 # Ray compute database password
├── db_password.txt                     # MLflow database password (legacy alias)
├── authentik_secret_key.txt            # Authentik encryption key (legacy)
├── authentik_db_password.txt           # Authentik database password (legacy)
├── authentik_bootstrap_password.txt    # Authentik initial admin password (legacy)
├── ${PUBLIC_DOMAIN}.crt # Tailscale TLS certificate
├── ${PUBLIC_DOMAIN}.key # Tailscale TLS private key
├── <legacy-domain>.<tailnet-id>.ts.net.crt # Legacy TLS certificate
├── <legacy-domain>.<tailnet-id>.ts.net.key # Legacy TLS private key
└── certs/                              # Additional certificates
```

!!! danger "Git Ignored"
    All files in `secrets/` except `README.md` are in `.gitignore`. Never commit secret files to version control.

---

## Secret Usage by Service

| Secret File | Used By | Mounted As |
|------------|---------|------------|
| `shared_db_password.txt` | PostgreSQL, Ray API, Postgres Backup | `/run/secrets/shared_db_password` |
| `grafana_password.txt` | Grafana | `/run/secrets/grafana_password` |
| `fusionauth_db_password.txt` | FusionAuth | `/run/secrets/fusionauth_db_password` |
| `oauth2_proxy_cookie_secret.txt` | OAuth2-Proxy | Via `OAUTH2_PROXY_COOKIE_SECRET` env var |
| `db_password.txt` | MLflow Server | `/run/secrets/db_password` |
| `*.crt`, `*.key` | Traefik | Bind mount to `/etc/traefik/certs/` |

### Docker Secrets Declaration

In compose files, secrets are declared at the top level:

```yaml
secrets:
  shared_db_password:
    file: ./secrets/shared_db_password.txt
  grafana_password:
    file: ./secrets/grafana_password.txt
```

Services reference them via the `secrets:` key and read from `/run/secrets/<name>`:

```yaml
services:
  postgres:
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/shared_db_password
    secrets:
      - shared_db_password
```

---

## Generating Secrets

### Automated (Recommended)

```bash
sudo ./setup.sh
```

This generates all secrets, creates `.env`, and sets correct permissions.

### Manual

```bash
# 32-character password
openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c 32 > secrets/shared_db_password.txt

# Grafana password (24 chars)
openssl rand -base64 36 | tr -dc 'a-zA-Z0-9' | head -c 24 > secrets/grafana_password.txt

# OAuth2-Proxy cookie secret (must be 16, 24, or 32 bytes)
openssl rand -base64 32 | head -c 32 > secrets/oauth2_proxy_cookie_secret.txt

# Set permissions
chmod 600 secrets/*.txt
```

---

## Rotation Procedure

### Database Password

```bash
# 1. Generate new password
openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c 32 > secrets/shared_db_password.txt.new

# 2. Update password in PostgreSQL
docker exec -it shml-postgres psql -U postgres \
  -c "ALTER USER postgres PASSWORD '$(cat secrets/shared_db_password.txt.new)';"

# 3. Swap files
mv secrets/shared_db_password.txt secrets/shared_db_password.txt.old
mv secrets/shared_db_password.txt.new secrets/shared_db_password.txt

# 4. Update .env if SHARED_DB_PASSWORD is duplicated there
# 5. Restart services
./start_all_safe.sh
```

### Grafana Password

```bash
echo "new-password-here" > secrets/grafana_password.txt
chmod 600 secrets/grafana_password.txt
docker restart unified-grafana
```

### TLS Certificates

```bash
# Regenerate Tailscale certs
tailscale cert ${PUBLIC_DOMAIN}

# Copy to secrets/
cp ${PUBLIC_DOMAIN}.crt secrets/
cp ${PUBLIC_DOMAIN}.key secrets/

# Restart Traefik
docker restart shml-traefik
```

---

## Pre-Commit Scanning

The repository uses **ggshield** (GitGuardian) to prevent accidental secret commits:

```bash
# Install (required for all contributors)
pip install pre-commit ggshield
pre-commit install
pre-commit install --hook-type pre-push

# Authenticate
ggshield auth login

# Test
pre-commit run --all-files
```

!!! info "How It Works"
    Every `git commit` runs ggshield to scan staged files for passwords, API keys, tokens, and other secrets. If a secret is detected, the commit is **blocked** with a detailed explanation.

---

## Environment Variables vs Secret Files

| Mechanism | Used For | Example |
|-----------|----------|---------|
| **Secret files** (`secrets/*.txt`) | Database passwords, TLS keys | `shared_db_password.txt` |
| **`.env` variables** | Client IDs, non-file secrets | `FUSIONAUTH_PROXY_CLIENT_ID` |
| **`config/platform.env`** | Non-sensitive config only | `MLFLOW_TRACKING_URI` |

!!! warning "Rule of Thumb"
    If a value would cause a security incident if leaked, it belongs in `secrets/`. If it's a service URL or feature flag, it belongs in `config/platform.env`.
