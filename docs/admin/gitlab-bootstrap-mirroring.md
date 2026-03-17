# GitLab Bootstrap & Mirror Setup

End-to-end setup for adopting GitLab as private source-of-truth while keeping GitHub as sanitized public mirror.

---

## Scope and Architecture

This platform follows a split-trust model:

- **Private GitLab:** canonical repo, CI, registry, package distribution.
- **Public GitHub:** sanitized mirror only.

See also: [Repository Publication Policy](repository-publication-policy.md).

---

## Important Deployment Constraint

Current platform config exposes GitLab through HTTPS path routing (`/gitlab`) and does **not** expose an SSH Git port.

Practical consequence:

- **Use HTTPS + token now** for Git pushes/pulls.
- SSH keys for Git transport are optional until SSH is explicitly enabled on GitLab.

---

## Phase 1 — First-Time GitLab Hardening

1. Sign in to GitLab as admin/root.
2. Rotate root password and store in your secrets manager.
3. Enable 2FA for all admin users.
4. Disable public sign-up.
5. Enforce project defaults: private visibility, protected default branch.
6. Create a dedicated bot/service account for automation (recommended).

Recommended baseline settings:

- Default project visibility: **Private**
- Require approval for protected branch merges
- Disable force-push on protected branches
- Require 2FA for members with elevated roles

---

## Phase 2 — Create Private Canonical Project

Create project in GitLab UI (or API):

- Group: `ml-platform` (or your org group)
- Project: `shml-platform`
- Visibility: `Private`
- Initialize with README: **off** (you already have repo history)

---

## Phase 3 — Authentication Strategy (Best Practice)

### Human developer access

Use HTTPS with personal token (current deployment). Use short-lived, least-privilege tokens where possible.

Required token scopes (minimum):

- `read_repository`
- `write_repository`

### Automation access (mirror pipeline)

Use project/group/bot token (not a personal token).

- Create token dedicated to mirror publishing.
- Store as protected + masked CI variable.
- Rotate on a fixed schedule (e.g., 90 days).

### Do not keep tokens in `.env`

Use `.env` for non-sensitive runtime configuration only.

For GitLab/GitHub access tokens, prefer:

- GitLab CI/CD protected + masked variables
- Secret files under `secrets/` for local runtime integrations
- Optional external secret manager for centralized rotation

Why this matters:

- `.env` is easy to accidentally leak in shell history, logs, screenshots, or backups.
- `.env` values are broadly available to local processes; least-privilege is harder.
- CI variables and secret files give better auditability and tighter access boundaries.

If GitLab container crashes:

- **Project/group CI variables persist** in GitLab database storage (`gitlab-data` volume + PostgreSQL).
- **Secret files persist** on disk (`secrets/` directory) and are remounted on restart.
- You should still back up both GitLab data and `secrets/` regularly.

### Why move tokens out of `.env` (strong case)

Use `.env` for non-sensitive runtime defaults only. Keep access tokens in either GitLab masked/protected CI variables or secret files under `secrets/`.

Security reasons:

- `.env` tends to leak through shell history, troubleshooting copy/paste, screenshots, and ad-hoc debug logs.
- `.env` often gets sourced broadly, which increases blast radius when one process or user context is compromised.
- CI masked/protected variables enforce scope, branch/tag protections, and provide audit trails for updates.
- Secret files can be mounted only into services that need them, reducing privilege spread.

Operational reasons:

- Rotation is safer: update one CI variable or secret file without touching shared developer shells.
- Incident response is faster: revoke/replace in one control plane instead of chasing multiple `.env` copies.

### Recovery model if GitLab crashes or backups are missing

Treat runtime secret storage as **distribution**, not **source of truth**.

- Source of truth should be an external password manager or secret vault (manual or automated).
- GitLab masked variables and `secrets/` files are runtime copies derived from that source.

Recovery procedure:

1. Restore GitLab service and data stores.
2. Restore PostgreSQL backup containing the `gitlab` DB (contains CI variable metadata/values).
3. Restore `gitlab-data` Docker volume snapshot for repos/uploads/artifacts.
4. Restore encrypted `secrets/` backup for file-mounted secrets.
5. If any piece is missing, rehydrate secrets from external source of truth and rotate immediately.

### Does GitLab currently back up somewhere?

Current state in this repo:

- **PostgreSQL scheduled backup exists** (`postgres-backup` service) and now includes `gitlab` DB.
- **GitLab volumes are persistent** (`gitlab-config`, `gitlab-logs`, `gitlab-data`) but are **not automatically archived off-host** by default.

Important implication:

- DB backup protects GitLab metadata (including CI variables in DB),
- but full GitLab disaster recovery still requires periodic backup/snapshot of `gitlab-data` volume and off-host copy of `secrets/`.

---

## Phase 4 — Add GitLab Remote to Existing Local Repo

If you already have `shml-platform` cloned locally (you do), **do not run `git clone` again in that same working directory**.
Use a second remote instead.

From repository root:

```bash
# Keep GitHub as origin (already configured)
git remote -v

# Add GitLab as secondary remote
git remote add gitlab https://<gitlab-host>/gitlab/<group>/shml-platform.git

# Verify
git remote -v
```

Push current branch to GitLab:

```bash
git push -u gitlab main
```

If `gitlab` remote already exists, update it instead of re-adding:

```bash
git remote set-url gitlab https://<gitlab-host>/gitlab/<group>/shml-platform.git
```

Optional: push all branches/tags once during migration:

```bash
git push gitlab --all
git push gitlab --tags
```

---

## Phase 5 — Configure CI Variables for Mirror Workflow

Path A implementation in this repo uses Infisical as source of truth, then syncs to GitLab variables via:

- `scripts/security/sync_infisical_to_gitlab_vars.sh`
- mapping file: `config/secrets/infisical-gitlab-variable-map.tsv`

Runbook: [Infisical Path A](infisical-path-a.md).

Set these in GitLab project CI/CD variables:

- `PUBLIC_MIRROR_ENABLED=true`
- `PUBLIC_MIRROR_PUBLISH=true` (only when ready)
- `PUBLIC_MIRROR_REPO_URL=https://github.com/<org>/shml-platform.git`
- `PUBLIC_MIRROR_GITHUB_TOKEN=<github_token_with_repo_write>`
- `PUBLIC_MIRROR_BRANCH=public-mirror`
- `PUBLIC_MIRROR_GIT_NAME=SHML Mirror Bot`
- `PUBLIC_MIRROR_GIT_EMAIL=mirror-bot@your-domain`

Keep all sensitive values masked/protected.

### Runner hardening (compose-managed)

`deploy/compose/docker-compose.infra.yml` includes a persistent `gitlab-runner` service that:

- reuses volume `${PLATFORM_PREFIX:-shml}-gitlab-runner-config`
- auto-registers on first boot when `GITLAB_RUNNER_REGISTRATION_TOKEN` is provided
- enforces internal clone URL and Docker network mode for reliable in-cluster fetches

Set these in `.env` (or secret manager synced into env):

- `GITLAB_RUNNER_REGISTRATION_TOKEN=<project_or_group_registration_token>`
- optional: `GITLAB_RUNNER_NETWORK_MODE=<platform-network-name>` if not `shml-platform`

---

## Phase 6 — Validate End-to-End Flow

1. Run GitLab pipeline manually (`public_mirror_sync`) with publish disabled first.
2. Confirm artifacts include:
   - `.public-mirror/`
   - `.public-mirror-report.txt`
3. Enable publish and rerun.
4. Confirm GitHub `public-mirror` branch updates.
5. Confirm GitHub workflows enforce boundary and security scans.

---

## Registry and Runner Gap-Fill Plan

High-value GitLab additions (in order):

1. **Container Registry**
   - Push internal images to GitLab registry.
   - Tag by commit SHA and semver.
2. **Package Registry (PyPI)**
   - Publish internal SDK/wheels for controlled install.
3. **Self-hosted Runners (GPU node)**
   - Route heavy training/test jobs to your hardware.
   - Keep lightweight lint/security checks on shared runners.

---

## Optional: Enabling SSH Git Access Later

SSH is strong for developer ergonomics, but requires infrastructure changes in this deployment.

You need to:

1. Expose GitLab SSH service port from container.
2. Set `gitlab_shell_ssh_port` in Omnibus config.
3. Open firewall/Tailscale ACL for SSH port.
4. Add user SSH keys in GitLab profile.

Until then, HTTPS + token is the secure and practical default.
