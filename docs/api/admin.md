# Admin API

Administrative endpoints for user management and service monitoring.

!!! danger "Admin role required"
    All endpoints on this page require the **admin** role. Requests with
    insufficient privileges receive a `403 Forbidden` response.

---

## Current User

**`GET /api/ray/user/me`**

Returns the profile of the authenticated user. Available to **all**
authenticated roles.

```bash
curl http://localhost/api/ray/user/me \
  -H "X-API-Key: $SHML_API_KEY"
```

### Response

```json
{
  "user_id": "u-abc123",
  "email": "user@example.com",
  "roles": ["user"],
  "created_at": "2026-01-15T08:30:00Z"
}
```

---

## User Quota

**`GET /api/ray/user/quota`**

Returns resource quotas and current usage for the authenticated user.

```bash
curl http://localhost/api/ray/user/quota \
  -H "X-API-Key: $SHML_API_KEY"
```

### Response

```json
{
  "gpu_hours_used": 12.5,
  "gpu_hours_limit": 100,
  "jobs_active": 1,
  "jobs_limit": 5
}
```

---

## List Users

**`GET /api/ray/admin/users`**

List all registered platform users. Admin only.

```bash
curl http://localhost/api/ray/admin/users \
  -H "X-API-Key: $SHML_ADMIN_KEY"
```

### Response

```json
{
  "users": [
    {
      "user_id": "u-abc123",
      "email": "user@example.com",
      "roles": ["user"],
      "active": true
    }
  ]
}
```

---

## Service Status

**`GET /api/ray/admin/services`**

Returns health status for every integrated service. Useful for
dashboards and alerting.

```bash
curl http://localhost/api/ray/admin/services \
  -H "X-API-Key: $SHML_ADMIN_KEY"
```

### Response

```json
{
  "mlflow": true,
  "nessie": true,
  "fiftyone": true,
  "features": true,
  "prometheus": true
}
```

!!! info "SDK equivalent"
    The Python SDK exposes the same check via:
    ```python
    from shml import Client
    with Client() as c:
        print(c.health_check())
    ```
