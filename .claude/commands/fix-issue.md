---
description: "Investigate and fix a GitLab issue. Usage: /project:fix-issue <issue-number>"
---

# Fix Issue #$ARGUMENTS

## 1. Fetch Issue Details

```bash
python3 scripts/platform/gitlab_utils.py get-issue $ARGUMENTS 2>/dev/null || \
  python3 scripts/platform/gitlab_utils.py list-issues --state opened | grep -A5 "#$ARGUMENTS"
```

## 2. Understand the Problem

Based on the issue title, description, and labels:
- What is the expected behavior?
- What is the actual behavior?
- Which component/service is affected?
- What severity is this (`priority::critical`, `priority::high`, etc.)?

## 3. Locate the Code

Search for relevant files based on the issue description. Check:
- Component labels (e.g., `component::ray-compute`, `component::chat-ui`)
- Error messages or stack traces in the issue body
- Related files in `inference/`, `ray_compute/`, `mlflow-server/`, etc.

## 4. Root Cause Analysis

Read the relevant code. Identify:
- The root cause (not just the symptom)
- Why it happens (race condition, missing validation, wrong config, etc.)
- The minimal fix needed

## 5. Implement Fix

Apply the targeted fix:
- Don't refactor surrounding code unless directly necessary
- Add a test if the issue is a bug (prevent regression)
- Follow `.agent/rules/code-style.md` conventions

## 6. Verify

After implementing:
- Run relevant tests: `pytest tests/ -v -k <test_name>`
- Check the specific scenario described in the issue

## 7. Close the Issue

```bash
python3 scripts/platform/gitlab_utils.py upsert-issue "$ARGUMENTS" --comment "Fixed in <commit>. Root cause: <brief>"
```
