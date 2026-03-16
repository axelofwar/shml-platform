# GitHub Secrets Reference

This document lists all **GitHub Actions secrets** required by the CI/CD
workflows in this repository.  Configure them at:

> **Settings → Secrets and variables → Actions → New repository secret**

---

## Required Secrets

| Secret | Used In | Description |
|--------|---------|-------------|
| `FUSIONAUTH_API_KEY` | `ci.yml`, `security.yml`, shell scripts | Master FusionAuth API key for admin operations (creating apps, keys, roles). Also required at runtime by `scripts/auth/*.sh`. |
| `FUSIONAUTH_DEVELOPER_KEY` | `ci.yml` | FusionAuth API key scoped to the `elevated-developer` role. Used by live integration tests. |
| `FUSIONAUTH_VIEWER_KEY` | `ci.yml` | FusionAuth API key scoped to the read-only `viewer` role. Used by RBAC and integration tests. |
| `FUSIONAUTH_URL` | `ci.yml` | Base URL of the FusionAuth instance (e.g. `https://auth.example.com`). |
| `CHAT_API_URL` | `ci.yml` | Base URL of the deployed Chat API (e.g. `https://api.example.com`). Used by live chat-api tests. |
| `PUBLIC_DOMAIN` | `ci.yml` | Public-facing domain for the platform (e.g. `example.com`). Used by full-stack live tests. |
| `CODECOV_TOKEN` | `ci.yml` | Token for uploading coverage reports to Codecov (optional but recommended). |

## Optional / Environment-Only

These are **not** GitHub secrets but are referenced via `.env` or
`deploy/compose/docker-compose.dev.yml` for local development:

| Variable | Default | Description |
|----------|---------|-------------|
| `DEV_POSTGRES_PASSWORD` | `dev_password` | Postgres password for the local dev compose stack. Set in `.env` to override. |

## Notes

- **Never commit real secret values** to the repository. Use GitHub's
  encrypted secrets or a `.env` file (already in `.gitignore`).
- The `scripts/auth/*.sh` scripts require `FUSIONAUTH_API_KEY` to be
  exported in the shell environment — they will fail fast with a clear
  error if it is missing.
- Live-test jobs (`chat-api-live-tests`, `full-stack-live-tests`,
  `fusionauth-live-tests`) are only meaningful when secrets point at a
  running staging environment.
