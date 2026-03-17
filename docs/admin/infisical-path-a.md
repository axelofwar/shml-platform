# Infisical Path A (Source of Truth)

Path A makes Infisical the source of truth for sensitive values, then distributes those values to:

- GitLab CI/CD masked/protected variables
- Local Docker secret files in `secrets/*.txt`

---

## Prerequisites

- Infisical is reachable at `/secrets` (already protected by OAuth + admin role middleware).
- `infisical` CLI is installed and authenticated.
- You know your Infisical project ID and environment slug.
- You have a GitLab token with `api` scope for the target project.

---

## Mapping Files

Edit these templates:

- `config/secrets/infisical-gitlab-variable-map.tsv`
- `config/secrets/infisical-docker-secret-map.tsv`

Each row is tab-separated and maps one Infisical secret to one destination.

---

## 1) Sync Infisical → GitLab Variables

Run from repo root:

```bash
export INFISICAL_PROJECT_ID="<project-id>"
export INFISICAL_ENV_SLUG="prod"
export GITLAB_PROJECT_ID="<numeric-id-or-encoded-path>"
export GITLAB_API_URL="https://<host>/gitlab/api/v4"
export GITLAB_API_TOKEN="<token-with-api-scope>"

bash scripts/security/sync_infisical_to_gitlab_vars.sh
```

What it does:

- Reads each mapping row.
- Fetches secret value from Infisical.
- Upserts GitLab CI variable with configured `masked/protected/environment_scope` settings.

---

## 2) Render Infisical → Local Secret Files

Run from repo root:

```bash
export INFISICAL_PROJECT_ID="<project-id>"
export INFISICAL_ENV_SLUG="prod"

bash scripts/security/render_infisical_secret_files.sh
```

What it does:

- Reads each mapping row.
- Fetches secret value from Infisical.
- Writes to destination file (for example `secrets/shared_db_password.txt`).
- Applies strict file permission (`600`).

---

## Optional GitLab Job

The repo includes a manual/scheduled GitLab job:

- Job: `path_a_sync_gitlab_variables`
- Condition variable: `PATH_A_SYNC_ENABLED=true`

Note: job expects `infisical` CLI to be installed in the runner environment.

---

## Rotation Workflow

1. Rotate secret in Infisical.
2. Run `sync_infisical_to_gitlab_vars.sh`.
3. Run `render_infisical_secret_files.sh`.
4. Restart only services that consume rotated file secrets.

This keeps Infisical as source of truth while preserving existing runtime integration patterns.
