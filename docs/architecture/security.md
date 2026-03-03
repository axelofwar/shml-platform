# SHML Chat API - Security & Access Control

## Authentication Matrix

| Interface | Path | Authentication | Required Role | Rate Limit |
|-----------|------|----------------|---------------|------------|
| **Web Chat UI** | `/chat-ui/` | OAuth (FusionAuth) | Developer, Admin | Role-based |
| **Chat API (Browser)** | `/chat/` | OAuth (FusionAuth) | Developer, Admin | Role-based |
| **Chat API (Direct)** | `/api/chat/` | API Key | Any valid key | Role-based |
| **Coding Model** | `/api/coding` | OAuth (FusionAuth) | Developer, Admin | Role-based |

## Rate Limits by Role

| Role | Requests/Minute | API Key Creation |
|------|-----------------|------------------|
| **Admin** | Unlimited | Can create for any user |
| **Developer** | 100 | Can create for self only |
| **Viewer** | 20 | Cannot create |

## Authentication Flow

### 1. Web Interface (Chat UI, Chat API browser)

```
User -> Traefik -> oauth2-proxy -> FusionAuth -> role-auth-developer -> Service
```

- Traefik routes request to oauth2-proxy
- oauth2-proxy redirects to FusionAuth login if not authenticated
- After login, oauth2-proxy validates session and sets headers
- role-auth middleware checks user has developer/admin role
- If role check fails, returns 403 Forbidden

### 2. Direct API (Cursor, editors)

```
User -> Traefik -> Chat API Service (validates API key internally)
```

- No OAuth redirect (would break API clients)
- Chat API service validates API key from Authorization header
- Returns 401 if key invalid or missing
- API key inherits user's FusionAuth role for rate limiting

## Security Layers

### Layer 1: Traefik Middleware (OAuth routes)

```yaml
middlewares: oauth2-errors,oauth2-auth,role-auth-developer,chat-strip
```

- `oauth2-errors`: Error pages for auth failures
- `oauth2-auth`: Forward auth to oauth2-proxy
- `role-auth-developer`: Check user has developer or admin role
- `chat-strip`: Strip path prefix

### Layer 2: Service Authentication (API routes)

```python
# auth.py - get_current_user()
if authorization and authorization.credentials:
    user = await db.validate_api_key(api_key)
    if not user:
        raise HTTPException(401, "Invalid or expired API key")
```

- Validates API key from Bearer token
- Checks key is active and not expired
- Returns user with role from key creation

### Layer 3: Rate Limiting (All routes)

```python
# rate_limit.py - record()
if user.role == UserRole.ADMIN:
    return True  # Unlimited
elif user.role == UserRole.DEVELOPER:
    limit = RATE_LIMIT_DEVELOPER  # 100
elif user.role == UserRole.VIEWER:
    limit = RATE_LIMIT_VIEWER  # 20
```

- Redis-based sliding window
- Per-user limits based on role
- Returns 429 when exceeded

## Ask-Only Mode (Web Chat)

Web chat requests include `source: "web"` which triggers ask-only mode:

```python
# model_router.py
if request.source == RequestSource.WEB:
    system_prompt_parts.append(ASK_ONLY_SYSTEM_PROMPT)
```

This ensures web chat users cannot:
- Edit or modify files
- Execute commands
- Access external systems

They CAN:
- Ask questions about the platform
- Get code explanations
- Receive learning examples

## API Key Management

### Creating Keys

- **Admins**: Can create keys for any user with any role
- **Developers**: Can create keys only for themselves
- **Viewers**: Cannot create keys (must be provisioned by admin)

### Key Format

```
shml_<48-character-random-string>
```

### Key Storage

- Keys are hashed (SHA-256) before storage
- Original key shown only at creation time
- Keys can be set to expire

## Testing Authentication

Run the test suite:

```bash
cd /home/axelofwar/Projects/shml-platform
./tests/chat-api/run_tests.sh
```

Tests cover:
- No auth returns 401
- Invalid API key returns 401
- Valid API key grants access
- OAuth headers parsed correctly
- Role requirements enforced
- Rate limits applied correctly
- Ask-only mode injection for web requests
