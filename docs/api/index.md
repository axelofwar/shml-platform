# API Reference

The SHML Platform exposes a REST API through the Traefik gateway. All
endpoints live under the `/api/ray` prefix and return JSON.

## Base URL

```
http://localhost
```

Traefik routes requests to the appropriate backend service. In remote
deployments, replace `localhost` with the gateway hostname.

## Authentication

Every request must include **one** of the following:

| Method | Header | Example |
|--------|--------|---------|
| API Key | `X-API-Key` | `X-API-Key: shml_abc123…` |
| OAuth2 Bearer | `Authorization` | `Authorization: Bearer eyJ…` |

!!! tip "Getting an API key"
    Generate one from the platform UI under **Settings → API Keys**, or via
    the CLI: `shml auth create-key`.

## Response Format

All successful responses return JSON with a top-level object.
Errors follow a consistent shape:

```json
{
  "error": "NotFound",
  "detail": "Job abc-123 not found"
}
```

| Status | Meaning |
|--------|---------|
| `200` | Success |
| `204` | Success (no body) |
| `400` | Bad request / validation error |
| `401` | Missing or invalid credentials |
| `403` | Insufficient permissions |
| `404` | Resource not found |
| `500` | Internal server error |

## Quick Endpoint Reference

### Jobs

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/ray/jobs` | [Submit a job](jobs.md#submit-a-job) |
| `GET` | `/api/ray/jobs` | [List jobs](jobs.md#list-jobs) |
| `GET` | `/api/ray/jobs/{id}` | [Job status](jobs.md#job-status) |
| `GET` | `/api/ray/jobs/{id}/logs` | [Job logs](jobs.md#job-logs) |
| `POST` | `/api/ray/jobs/{id}/cancel` | [Cancel job](jobs.md#cancel-a-job) |

### GPU

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/ray/gpu/status` | [GPU status](gpu.md#gpu-status) |
| `POST` | `/api/ray/gpu/yield` | [Yield GPU](gpu.md#yield-gpu) |
| `POST` | `/api/ray/gpu/reclaim` | [Reclaim GPU](gpu.md#reclaim-gpu) |

### User

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/ray/user/me` | [Current user profile](admin.md#current-user) |
| `GET` | `/api/ray/user/quota` | [User quota](admin.md#user-quota) |

### Admin

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/ray/admin/users` | [List users](admin.md#list-users) |
| `GET` | `/api/ray/admin/services` | [Service status](admin.md#service-status) |
