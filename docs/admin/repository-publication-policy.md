# Repository Publication Policy

Policy for what can be published to a public GitHub mirror vs what must remain in private GitLab.

---

## Purpose

This platform uses a split-trust model:

- **Private GitLab (source of truth):** deployable infrastructure, environment-specific security configuration, operational runbooks, and all secret-bearing assets.
- **Public GitHub (sanitized mirror):** reusable code, templates, and redacted documentation.

This follows standard infra security practice: architecture patterns can be public, but operational security data stays private.

---

## Classification Matrix

| Path | Classification | Rationale | Publication Rule |
|------|----------------|-----------|------------------|
| `.env`, `.env.*` | Private-Only | Contains credential and token material | Never publish |
| `secrets/`, `**/secrets/` | Private-Only | Secret files and TLS key/cert material | Never publish |
| `logs/`, `data/`, `runs/`, `backups/` | Private-Only | Runtime/state artifacts may leak metadata or data | Never publish |
| `docs/internal/` | Private-Only | Internal operational runbooks and topology detail | Never publish |
| `deploy/compose/docker-compose.secrets.yml` | Public-Redacted | Useful structure but often references secret wiring | Publish only with secret-safe placeholders |
| `fusionauth/`, `oauth2-proxy/` | Public-Redacted | Good reference implementation with potential bootstrap defaults | Remove default credentials and local-only assumptions |
| `docs/` (except `docs/internal/`) | Public-Redacted | Valuable docs may include internal endpoint details | Redact hostnames, IPs, and operational secrets |
| `cli/`, `libs/`, `sdk/`, `tests/` | Public (scanned) | Core platform code intended for collaboration | Publish after automated secret scans |
| `inference/`, `ray_compute/`, `mlflow-server/` | Public-Redacted | Service code is shareable; configs may carry env coupling | Redact environment-specific details |

---

## Legacy and Archive Policy

- `sfml-platform-original/` remains **Private-Only archive**.
- No direct public mirroring of archive trees.
- Any public reuse from archived material requires explicit extraction into new sanitized files.

---

## Automation Rules

Public mirror jobs must enforce both of these files:

- `.github/public-mirror-allowlist.txt`
- `.github/public-mirror-denylist.txt`

Required behavior:

1. Fail if any tracked file matches denylist patterns.
2. Fail if mirrored output contains files outside allowlist patterns.
3. Fail if secret scanners detect potential credentials.

---

## Release Gate Checklist

Before publishing to GitHub mirror:

- [ ] Denylist path check passes
- [ ] Allowlist scope check passes
- [ ] Secret scan passes (Gitleaks + TruffleHog + ggshield locally)
- [ ] Documentation redaction review passes (no internal hostnames/IPs)
- [ ] Security reviewer approval recorded

---

## Ownership

- **Policy owner:** Platform Security / Admin team
- **Enforcement owner:** CI maintainers
- **Change control:** Any classification change requires security review
