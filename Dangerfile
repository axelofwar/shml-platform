# Dangerfile — MR hygiene checks for SHML Platform
# Runs via danger-python in CI on merge_request_event pipelines.

import re

# ---------------------------------------------------------------------------
# 1. MR description must be meaningful
# ---------------------------------------------------------------------------
if not danger.gitlab.mr.description or len(danger.gitlab.mr.description.strip()) < 20:
    warn("MR description is missing or too short. Please describe what this MR does and why.")

# ---------------------------------------------------------------------------
# 2. Labels should be present
# ---------------------------------------------------------------------------
if not danger.gitlab.mr.labels:
    warn("This MR has no labels. Please add at least one label (e.g., `type::feature`, `type::bug`).")

# ---------------------------------------------------------------------------
# 3. WIP / Draft check
# ---------------------------------------------------------------------------
title = danger.gitlab.mr.title or ""
if title.startswith("WIP:") or title.startswith("Draft:") or "[WIP]" in title:
    warn("This MR is marked as WIP/Draft. Remove the prefix when ready for review.")

# ---------------------------------------------------------------------------
# 4. Large MR warning
# ---------------------------------------------------------------------------
file_count = len(danger.git.modified_files) + len(danger.git.created_files) + len(danger.git.deleted_files)
if file_count > 30:
    warn(f"This MR touches {file_count} files. Consider splitting into smaller MRs.")

# ---------------------------------------------------------------------------
# 5. Sensitive file changes
# ---------------------------------------------------------------------------
sensitive_patterns = [
    r"\.env$", r"\.env\.", r"secrets/", r".*\.key$", r".*\.pem$",
    r"docker-compose.*\.yml$", r"Dockerfile", r"\.gitlab-ci\.yml$",
    r"Taskfile\.yml$", r"start_all_safe\.sh$",
]

all_changed = danger.git.modified_files + danger.git.created_files
sensitive_files = []
for f in all_changed:
    fname = f if isinstance(f, str) else getattr(f, 'path', str(f))
    for pattern in sensitive_patterns:
        if re.search(pattern, fname):
            sensitive_files.append(fname)
            break

if sensitive_files:
    file_list = "\n".join(f"- `{f}`" for f in sensitive_files[:10])
    warn(f"Sensitive files modified — ensure no secrets are committed:\n{file_list}")

# ---------------------------------------------------------------------------
# 6. Docker compose changes need review
# ---------------------------------------------------------------------------
compose_files = [
    f for f in all_changed
    if re.search(r"docker-compose.*\.yml$", f if isinstance(f, str) else getattr(f, 'path', str(f)))
]
if compose_files:
    warn("Docker Compose files modified. Verify: network attachments, health checks, Traefik priority labels.")

# ---------------------------------------------------------------------------
# 7. Test coverage for code changes
# ---------------------------------------------------------------------------
code_patterns = [r"\.py$", r"\.ts$", r"\.tsx$"]
test_patterns = [r"test_", r"_test\.py$", r"tests/", r"\.test\.", r"\.spec\."]

has_code = any(re.search(p, f if isinstance(f, str) else getattr(f, 'path', str(f))) for f in all_changed for p in code_patterns)
has_tests = any(re.search(p, f if isinstance(f, str) else getattr(f, 'path', str(f))) for f in all_changed for p in test_patterns)

if has_code and not has_tests:
    warn("Code changes without test changes. Consider adding tests.")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
message(f"📊 MR Stats: {file_count} files changed, {len(danger.git.deleted_files)} deleted")
