---
title: "Security Standards"
domain: security
applies-to: "**/*.py,**/*.sh,**/*.yml,**/*.env*"
---

# 🔒 Security Standards

## ⚠️ CRITICAL: Pre-Commit Hooks (MANDATORY)

This project uses pre-commit hooks with GitGuardian to prevent secret leaks.

```bash
# Install hooks (required for all developers)
pip install pre-commit ggshield
pre-commit install
pre-commit install --hook-type pre-push

# Authenticate ggshield (one-time setup)
ggshield auth login
```

**What gets scanned:**
- Every commit is scanned for secrets before it's created
- Every push is scanned before reaching GitHub
- GitGuardian CI also scans all PRs

**If a secret is detected:**
1. The commit/push will be BLOCKED
2. You'll see which file/line contains the secret
3. Remove the secret and try again
4. Use environment variables or Docker secrets instead

## Secrets Management

**Git-Ignored Files (NEVER commit these):**
- `REMOTE_ACCESS_COMPLETE.sh` — Contains ALL credentials, IPs, passwords
- `mlflow-server/secrets/` — Database passwords
- `ray_compute/.env` — OAuth secrets, API keys
- `*/data/` — Persistent data volumes
- `*/logs/` — Service logs
- `*/backups/` — Database backups
- `*-env.backup` — Environment backups

**Safe to Commit:**
- `.env.example` — Templates with placeholders
- Documentation files
- Source code without secrets
- Configuration templates

## How to Handle Secrets in Code

**❌ NEVER do this:**
```python
# Hardcoded secrets — WILL BE BLOCKED by pre-commit
API_KEY = "sk-1234567890abcdef"
PASSWORD = "AiSolutions2350!"
SECRET_KEY = os.getenv("SECRET_KEY", "default_secret")  # Bad default!
```

**✅ ALWAYS do this:**
```python
# Load from environment — no fallback for secrets
API_KEY = os.environ["API_KEY"]  # Fails loudly if not set
PASSWORD = os.getenv("PASSWORD")
if not PASSWORD:
    raise ValueError("PASSWORD environment variable required")

# Or use Docker secrets
def load_secret(name: str) -> str:
    secret_path = f"/run/secrets/{name}"
    if os.path.exists(secret_path):
        with open(secret_path) as f:
            return f.read().strip()
    value = os.environ.get(name.upper())
    if not value:
        raise ValueError(f"Secret {name} not found in /run/secrets/ or environment")
    return value
```

## Placeholder Patterns

**Never in committed files:**
```
❌ PASSWORD=gNz8APgrUF8Q3hMe2sQXQK8DPGHs3CGcVhoPLbcqvi4=
❌ TAILSCALE_IP=100.x.x.x
❌ DB_HOST=192.168.1.100
❌ client_secret=JsDs6mClPCWKqEq...
```

**Always use:**
```
✅ PASSWORD=${DB_PASSWORD}
✅ TAILSCALE_IP=${TAILSCALE_IP}
✅ DB_HOST=<your-server-ip>
✅ client_secret=<from-authentik-dashboard>
```

## Security Scanning Tools

| Tool | When | What |
|------|------|------|
| **ggshield** | Pre-commit, pre-push | Blocks secrets before commit |
| **Gitleaks** | Pre-commit, CI | Additional secret patterns |
| **GitGuardian** | GitHub CI | Scans all PRs and pushes |
| **Trivy** | CI | Container vulnerabilities |
| **pip-audit** | CI | Python dependency CVEs |

## OWASP Top 10 Checklist

When writing code, verify:
- [ ] No hardcoded credentials or secrets
- [ ] Input validation at all system boundaries (user input, external APIs)
- [ ] No SQL injection (use parameterized queries)
- [ ] No XSS (escape output; use framework escaping)
- [ ] No command injection (avoid shell=True; use subprocess list form)
- [ ] Authentication checked before data access
- [ ] No path traversal (validate/sanitize file paths)
- [ ] Dependencies up to date (pip-audit, trivy)
- [ ] Errors don't leak sensitive info to users
- [ ] SSRF prevention: validate URLs before outbound requests

## Input Validation Pattern

```python
# External boundary validation (user input, external APIs, webhooks)
from pathlib import Path

def safe_path(base_dir: str, user_input: str) -> Path:
    """Prevent path traversal attacks."""
    base = Path(base_dir).resolve()
    target = (base / user_input).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError(f"Path traversal attempt: {user_input}")
    return target
```
