# Public Mirror Publication Gates

This document defines the minimum CI controls required before syncing private GitLab content into a public GitHub mirror.

## Required Gates

1. **Denylist path gate (blocking)**
   - Fail if any tracked file matches `.github/public-mirror-denylist.txt`.

2. **Allowlist scope gate (blocking)**
   - Fail if any mirrored file does not match `.github/public-mirror-allowlist.txt`.

3. **Secret detection gate (blocking)**
   - Run Gitleaks and TruffleHog in CI.
   - Local contributor requirement: `pre-commit` with `ggshield`.

4. **Doc redaction gate (blocking)**
   - Validate no internal hostnames, private IPs, or operational credential examples in public docs.

5. **Security review gate (blocking for policy changes)**
   - Any modification to allowlist/denylist requires security reviewer approval.

## Recommended Workflow Order

1. Build sanitized mirror workspace from private source.
2. Apply denylist filter.
3. Apply allowlist filter.
4. Run secret scanners.
5. Run documentation redaction checks.
6. Publish only if all gates pass.

## Ownership

- Security policy owner: Platform Security/Admin
- CI gate owner: DevOps/CI maintainers
- Escalation: Any gate bypass requires documented approval in PR

## GitLab Mirror Variables

Use these CI/CD variables in private GitLab for `.gitlab-ci.yml` mirror automation:

- `PUBLIC_MIRROR_ENABLED` — set to `true` to run mirror job on default branch pipelines.
- `PUBLIC_MIRROR_PUBLISH` — set to `true` to push exported mirror to GitHub.
- `PUBLIC_MIRROR_REPO_URL` — GitHub HTTPS repo URL without credentials (example: `https://github.com/org/repo.git`).
- `PUBLIC_MIRROR_GITHUB_TOKEN` — GitHub token with repo write access (protected + masked).
- `PUBLIC_MIRROR_BRANCH` — destination branch in GitHub mirror (default: `public-mirror`).
- `PUBLIC_MIRROR_GIT_NAME` / `PUBLIC_MIRROR_GIT_EMAIL` — bot identity for mirror commits.

When `PUBLIC_MIRROR_PUBLISH=true`, the pipeline runs a blocking Gitleaks scan against the exported mirror workspace before pushing to GitHub.
