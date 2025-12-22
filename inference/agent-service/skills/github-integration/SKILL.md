---
name: github-integration
description: Interact with GitHub repositories - create issues, search code, list commits. Use when the user asks about GitHub, wants to create issues, search for code examples, or interact with repositories.
license: MIT
compatibility: Requires GitHub token for authenticated operations. Uses Composio integration.
metadata:
  author: shml-platform
  version: "1.0"
---

# GitHub Integration Skill

## When to use this skill
Use this skill when the user asks to:
- Create a GitHub issue
- Search code on GitHub
- List commits or pull requests
- Get file contents from a repo
- Interact with GitHub repositories

## Operations

### create_issue
Create a new issue in a repository.

**Parameters:**
- `repo` (required): "owner/repo" format
- `title` (required): Issue title
- `body` (optional): Issue description

**Example:**
```python
result = await execute("create_issue", {
    "repo": "anthropics/skills",
    "title": "Bug: Skill validation fails",
    "body": "When running skills-ref validate..."
})
```

### search_code
Search for code across GitHub.

**Parameters:**
- `query` (required): Search query

**Example:**
```python
result = await execute("search_code", {
    "query": "PyTorch DDP training language:python"
})
```

### list_commits
Get recent commits from a repository.

**Parameters:**
- `repo` (required): "owner/repo" format
- `count` (optional): Number of commits (default: 10)

### get_file_content
Get contents of a file from a repository.

**Parameters:**
- `repo` (required): "owner/repo" format
- `path` (required): File path in repo

## Authentication

GitHub operations require authentication via Composio:
1. Composio must be configured with GitHub OAuth
2. User must have authorized GitHub access

## Error Handling

| Code | Meaning | Action |
|------|---------|--------|
| 401 | Invalid token | Re-authenticate via Composio |
| 403 | Rate limited | Wait or use authenticated requests |
| 404 | Repo not found | Check repo name and permissions |

## Rate Limits

- Unauthenticated: 60 requests/hour
- Authenticated: 5000 requests/hour
- Search API: 30 requests/minute
