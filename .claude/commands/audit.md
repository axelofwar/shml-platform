---
description: "Run a security audit of the codebase — checks secrets, auth, injection risks, and dependencies"
---

# Security Audit

Perform a security audit of this workspace. Focus areas:

## 1. Secret Detection

Search for potential hardcoded secrets:
```bash
grep -rn --include="*.py" --include="*.sh" --include="*.yml" --include="*.env*" \
  -E "(password|secret|token|api_key|apikey)\s*=\s*['\"][^'\"]{8,}" \
  --exclude-dir=".git" --exclude-dir="node_modules" .
```

## 2. Authentication & Authorization

Review all FastAPI routes for:
- Missing authentication decorators
- Missing authorization checks
- Endpoints that should be gated but aren't

Check OAuth2-Proxy header trust configuration (`.agent/rules/api-conventions.md`).

## 3. Docker Security

Review docker-compose files for:
- Containers running as root
- Exposed ports that shouldn't be public
- Missing security contexts
- Secrets mounted as environment variables (should use Docker secrets)

## 4. Input Validation

Check all FastAPI endpoints taking user input for:
- Path traversal vulnerabilities (`../` in file paths)
- SQL injection (raw string queries)
- Command injection (`shell=True` in subprocess calls)

## 5. Dependencies

```bash
pip-audit 2>/dev/null | head -30
```

Present findings grouped by severity: **CRITICAL** → **HIGH** → **MEDIUM** → **INFO**
