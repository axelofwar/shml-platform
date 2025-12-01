# Secrets Directory

This directory contains sensitive credentials for the ML Platform. **These files are gitignored and must be generated locally.**

## ⚠️ Security Warning

- **NEVER** commit actual secrets to version control
- **NEVER** share secrets via unencrypted channels
- **ALWAYS** use strong, randomly generated passwords
- **ALWAYS** backup secrets securely before system changes

## Directory Structure

```
secrets/
├── README.md                       # This file (tracked)
├── shared_db_password.txt          # PostgreSQL shared database password
├── grafana_password.txt            # Grafana admin password  
├── authentik_secret_key.txt        # Authentik encryption key
├── authentik_db_password.txt       # Authentik PostgreSQL password
├── authentik_bootstrap_password.txt # Authentik initial admin password
├── ray_db_password.txt             # Ray compute database password (optional)
└── db_password.txt                 # MLflow database password (legacy)
```

## Generating Secrets

### Automatic (Recommended)

Run the unified setup script:

```bash
sudo ./setup.sh
```

This will:
1. Generate cryptographically secure passwords
2. Create all required secret files
3. Populate the `.env` file
4. Set correct file permissions (600)

### Manual Generation

If you need to regenerate specific secrets:

```bash
# Generate a 32-character password
openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c 32 > secrets/shared_db_password.txt

# Generate a 50-character secret key
openssl rand -base64 75 | tr -dc 'a-zA-Z0-9' | head -c 50 > secrets/authentik_secret_key.txt

# Generate Grafana password (24 chars)
openssl rand -base64 36 | tr -dc 'a-zA-Z0-9' | head -c 24 > secrets/grafana_password.txt

# Set secure permissions
chmod 600 secrets/*.txt
```

## Using Secrets in Docker Compose

Secrets are mounted as Docker secrets:

```yaml
# docker-compose.infra.yml
secrets:
  shared_db_password:
    file: ./secrets/shared_db_password.txt
  grafana_password:
    file: ./secrets/grafana_password.txt

services:
  shared-postgres:
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/shared_db_password
    secrets:
      - shared_db_password

  unified-grafana:
    environment:
      GF_SECURITY_ADMIN_PASSWORD_FILE: /run/secrets/grafana_password
    secrets:
      - grafana_password
```

## Viewing Secrets

To view current secrets (for debugging or client configuration):

```bash
# View all secrets
for f in secrets/*.txt; do echo "=== $f ==="; cat "$f"; echo; done

# View specific secret
cat secrets/grafana_password.txt
```

## Rotating Secrets

To rotate a secret:

1. Stop affected services
2. Generate new secret
3. Update any dependent services
4. Restart services

```bash
# Example: Rotate Grafana password
./stop_all.sh
openssl rand -base64 36 | tr -dc 'a-zA-Z0-9' | head -c 24 > secrets/grafana_password.txt
./start_all_safe.sh
```

**Note:** Database passwords require additional steps (ALTER USER in PostgreSQL).

## Backup Secrets

Before any major changes, backup your secrets:

```bash
# Create encrypted backup
tar -czf - secrets/ | openssl enc -aes-256-cbc -salt -out secrets_backup_$(date +%Y%m%d).tar.gz.enc

# Restore from backup
openssl enc -d -aes-256-cbc -in secrets_backup_YYYYMMDD.tar.gz.enc | tar -xzf -
```

## Environment Variables

Secrets can also be loaded from `.env`:

| Secret File | Environment Variable |
|-------------|---------------------|
| `shared_db_password.txt` | `SHARED_DB_PASSWORD` |
| `grafana_password.txt` | `GRAFANA_ADMIN_PASSWORD` |
| `authentik_secret_key.txt` | `AUTHENTIK_SECRET_KEY` |
| `authentik_db_password.txt` | `AUTHENTIK_DB_PASSWORD` |
| `authentik_bootstrap_password.txt` | `AUTHENTIK_BOOTSTRAP_PASSWORD` |

## Troubleshooting

### "Secret file not found"

```bash
# Check secrets exist
ls -la secrets/

# Regenerate missing secrets
sudo ./setup.sh --secrets-only
```

### "Permission denied"

```bash
# Fix permissions
sudo chown $(whoami):$(whoami) secrets/*.txt
chmod 600 secrets/*.txt
```

### Service fails to start with secret error

```bash
# Verify secret file content (no newlines, correct format)
xxd secrets/shared_db_password.txt | head

# Ensure no trailing newline
echo -n "$(cat secrets/shared_db_password.txt)" > secrets/shared_db_password.txt
```

## Security Best Practices

1. **Least Privilege**: Each service only has access to secrets it needs
2. **File Permissions**: All secret files are mode 600 (owner read/write only)
3. **No Logging**: Secrets are never logged or displayed in error messages
4. **Rotation**: Rotate secrets periodically, especially after personnel changes
5. **Encryption**: Use encrypted backups for secret storage
6. **Audit**: Monitor access to secret files via auditd

## Related Documentation

- `../.env.example` - Environment variable template
- `../ARCHITECTURE.md` - Platform architecture with security design
- `../setup.sh` - Unified setup with secret generation
