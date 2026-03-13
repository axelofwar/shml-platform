```skill
---
name: gitlab-integration
description: Interact with the local GitLab CE instance — create and manage issues, query pipelines, search code, list commits. Use when the user asks about GitLab, project issues, CI/CD status, or wants to track tasks.
license: MIT
compatibility: Requires GITLAB_API_TOKEN set in the agent-service environment. Talks to the internal GitLab CE container (shml-gitlab) via Docker network.
metadata:
  author: shml-platform
  version: "1.0"
---

# GitLab Integration Skill

## When to use this skill
Use this skill when the user asks to:
- Create a GitLab issue to track a bug, feature, or task
- List open issues or search for specific issues
- Check CI/CD pipeline status
- Add comments to existing issues
- Close or reopen issues
- List recent commits or milestones
- Check the project board state
- Track autoresearch or training progress via issues

## Operations

### create_issue
Create a new issue in the SHML Platform project.

**Parameters:**
- `title` (required): Issue title
- `description` (optional): Issue body in Markdown
- `labels` (optional): Comma-separated labels (e.g. "type::bug,priority::high")

**Example:**
```python
result = await execute("create_issue", {
    "title": "GPU 0 thermal throttling during autoresearch",
    "description": "GPU 0 temperature exceeded 85°C during training round 5.",
    "labels": "type::bug,priority::high,component::infra"
})
```

### list_issues
List open issues with optional filters.

**Parameters:**
- `state` (optional): "opened" | "closed" | "all" (default: "opened")
- `labels` (optional): Filter by labels
- `search` (optional): Search string

**Example:**
```python
result = await execute("list_issues", {
    "labels": "source::watchdog",
    "state": "opened"
})
```

### add_comment
Add a comment to an existing issue.

**Parameters:**
- `iid` (required): Issue number (IID)
- `body` (required): Comment text in Markdown

### close_issue
Close an issue.

**Parameters:**
- `iid` (required): Issue number (IID)

### reopen_issue
Reopen a closed issue.

**Parameters:**
- `iid` (required): Issue number (IID)

### upsert_issue
Find an existing open issue by title search and add a comment, or create a new one if not found. Useful for idempotent issue tracking.

**Parameters:**
- `search_title` (required): Title substring to search for
- `title` (optional): Full title for new issue creation
- `description` (optional): Body for new issue
- `labels` (optional): Labels for new issue
- `comment` (optional): Comment to add if existing issue found
- `close` (optional): If true, close the matched issue

### get_pipeline_status
Get the latest CI/CD pipeline status.

**Parameters:**
- `ref` (optional): Branch name (default: "main")

**Example:**
```python
result = await execute("get_pipeline_status", {"ref": "main"})
# Returns: {"id": 2293, "status": "success", "jobs": [...]}
```

### get_pipeline_jobs
List all jobs in a specific pipeline.

**Parameters:**
- `pipeline_id` (required): Pipeline ID

## Available Labels

### Type Labels
| Label | Color | Usage |
|-------|-------|-------|
| `type::bug` | Red | Bug or regression |
| `type::feature` | Blue | New feature or enhancement |
| `type::chore` | Green | Infrastructure, CI, maintenance |
| `type::training` | Gray | ML training run or experiment |
| `type::security` | Pink | Security concern or fix |

### Priority Labels
| Label | Color | Usage |
|-------|-------|-------|
| `priority::critical` | Red | Needs immediate attention |
| `priority::high` | Orange | Important, schedule soon |
| `priority::medium` | Blue | Normal priority |
| `priority::low` | Green | Nice to have |

### Component Labels
| Label | Usage |
|-------|-------|
| `component::watchdog` | Self-healing watchdog |
| `component::ci-cd` | CI/CD pipeline |
| `component::autoresearch` | Autoresearch training |
| `component::agent-service` | Agent service / skills |
| `component::chat-ui` | Chat UI frontend |
| `component::fusionauth` | FusionAuth / auth |
| `component::infra` | Docker, Traefik, networking |

### Source Labels
| Label | Usage |
|-------|-------|
| `source::watchdog` | Auto-created by watchdog |
| `source::scan` | Auto-created by scan_repo_state |
| `source::autoresearch` | Auto-created by autoresearch |
| `source::ci` | Auto-created by CI pipeline |

## Authentication

GitLab operations use the `GITLAB_API_TOKEN` environment variable (Personal Access Token with `api` scope). The token is injected into the agent-service container via the `.env` file.

## Internal URL

All API calls go to `http://shml-gitlab:8929/gitlab/api/v4/` via the Docker network — no OAuth2-proxy authentication required.

## Error Handling

| Code | Meaning | Action |
|------|---------|--------|
| 401 | Invalid or expired token | Regenerate PAT in GitLab admin |
| 404 | Issue or project not found | Check project ID (should be 2) |
| 409 | Conflict (e.g. duplicate label) | Safe to ignore, already exists |
| 500 | GitLab internal error | Retry or check GitLab container health |

## Implementation

This skill uses `scripts/platform/gitlab_utils.py` as the backend.
The utility module provides both a Python import API and a CLI interface.

```python
# Python import usage:
from scripts.platform.gitlab_utils import create_issue, list_issues, upsert_issue

# CLI usage from shell:
python3 scripts/platform/gitlab_utils.py create-issue "Title" --labels "type::bug"
python3 scripts/platform/gitlab_utils.py upsert-issue "Search Title" --comment "Update"
python3 scripts/platform/gitlab_utils.py list-issues --state opened
```
```
