# Authentication Flow & User Access Patterns
## Role-Based Access Control for All Platform Services

**Date:** December 7, 2025  
**Status:** Comprehensive Analysis  
**Auth Stack:** FusionAuth + OAuth2-Proxy + Custom Role-Auth Middleware

---

## Executive Summary

The platform uses a **three-tier authentication system**:
1. **FusionAuth** - OAuth/SSO provider with social login (Google, GitHub, Twitter)
2. **OAuth2-Proxy** - OAuth middleware for Traefik
3. **Role-Auth Middleware** - Custom role verification service

**Three User Roles:**
- **Guest** - Inference endpoints only (no auth required for API, auth required for UI)
- **Developer** - Full inference + MLflow + Ray + Chat UI + Agent Service
- **Elevated-Developer** - Developer + Code execution (sandboxes, elevated operations)
- **Admin** - Full platform access + Traefik dashboard + Prometheus + Code-Server

---

## Authentication Architecture

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER REQUEST                                 │
│                              │                                       │
│                              ▼                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    TRAEFIK GATEWAY                              │ │
│  │                                                                  │ │
│  │   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐   │ │
│  │   │ oauth2-errors│ ──▶ │ oauth2-auth  │ ──▶ │ role-auth-*  │   │ │
│  │   │  (handle)    │     │  (FusionAuth)│     │  (verify)    │   │ │
│  │   └──────────────┘     └──────────────┘     └──────────────┘   │ │
│  │                              │                      │            │ │
│  │                              ▼                      ▼            │ │
│  │                        Authenticated?          Has role?        │ │
│  │                              │                      │            │ │
│  └──────────────────────────────┼──────────────────────┼───────────┘ │
│                                 │                      │              │
│                   NO ───────────┘                      └───── NO     │
│                   │                                          │        │
│                   ▼                                          ▼        │
│          Redirect to FusionAuth                    403 Forbidden     │
│          Login (Google/GitHub/Twitter)                               │
│                   │                                                  │
│                   │ YES                                              │
│                   ▼                                                  │
│          ┌──────────────────┐                                        │
│          │   BACKEND        │                                        │
│          │   SERVICE        │                                        │
│          └──────────────────┘                                        │
└─────────────────────────────────────────────────────────────────────┘
```

### Middleware Chain by Role

```yaml
# Guest access (inference endpoints)
- No auth middleware required for API
- oauth2-auth required for UI access

# Developer access (most services)
middlewares: oauth2-errors,oauth2-auth,role-auth-developer

# Elevated-Developer access (sandboxes, elevated ops)
middlewares: oauth2-errors,oauth2-auth,role-auth-elevated

# Admin access (platform management)
middlewares: oauth2-errors,oauth2-auth,role-auth-admin
```

---

## Role-Based Service Access Matrix

| Service | Guest | Developer | Elevated-Dev | Admin | Endpoint |
|---------|-------|-----------|--------------|-------|----------|
| **Inference Stack** |
| Coding Models API | ✅ | ✅ | ✅ | ✅ | `/api/coding/*` |
| Chat API | ✅ | ✅ | ✅ | ✅ | `/api/chat/*` |
| Chat UI | ❌ | ✅ | ✅ | ✅ | `/chat` |
| Image Gen (Z-Image) | ✅ | ✅ | ✅ | ✅ | `/api/image/*` |
| Vision Model (Qwen-VL) | ✅ | ✅ | ✅ | ✅ | `/api/llm/*` |
| Embedding Service | ✅ | ✅ | ✅ | ✅ | `/api/embeddings/*` |
| **Agent Service** |
| Agent REST API | ❌ | ✅ | ✅ | ✅ | `/api/agent/*` |
| Agent WebSocket | ❌ | ✅ | ✅ | ✅ | `ws://*/ws/agent/*` |
| Agent Sandbox Exec | ❌ | ❌ | ✅ | ✅ | (via agent) |
| **ML Workflow** |
| MLflow UI | ❌ | ✅ | ✅ | ✅ | `/mlflow/` |
| MLflow API | ❌ | ✅ | ✅ | ✅ | `/api/2.0/mlflow/*` |
| Ray Dashboard | ❌ | ✅ | ✅ | ✅ | `/ray/` |
| Ray Jobs API | ❌ | ✅ | ✅ | ✅ | `/api/ray/*` |
| **Monitoring** |
| Grafana | ❌ | ✅ | ✅ | ✅ | `/grafana/` |
| Prometheus | ❌ | ❌ | ❌ | ✅ | `/prometheus/` |
| Dozzle (Logs) | ❌ | ✅ | ✅ | ✅ | `/dozzle/` |
| **Admin Tools** |
| Traefik Dashboard | ❌ | ❌ | ❌ | ✅ | `:8090` |
| Code-Server (VS Code) | ❌ | ❌ | ❌ | ✅ | `/code/` |
| FusionAuth Admin | ❌ | ❌ | ❌ | ✅ | `/auth/admin/` |

---

## Access Pattern 1: Chat UI (Browser)

### User Flow for Each Role

#### Guest User
```
1. Navigate to https://shml-platform.tail38b60a.ts.net/chat
2. ❌ Redirect to FusionAuth login
3. Login required (create account or use social login)
4. After login → Upgrade to Developer role required
```

**Access:**
- ❌ Chat UI (requires Developer+)
- ✅ Can access inference APIs directly (no auth)

#### Developer User
```
1. Navigate to https://shml-platform.tail38b60a.ts.net/chat
2. OAuth2 redirect to FusionAuth
3. Login with Google/GitHub/Twitter or email
4. ✅ Access granted to Chat UI
5. Chat with Qwen2.5-Coder models (32B primary, 7B fallback)
6. Access to Agent Service (G-R-C workflow)
7. Access to MLflow experiment tracking
8. Access to Ray job submission
```

**Features Available:**
- ✅ Multi-turn conversations
- ✅ Code syntax highlighting
- ✅ Model switching (32B ↔ 7B based on training)
- ✅ Agent orchestration (G-R-C workflow)
- ✅ Screenshot upload (multimodal - future)
- ✅ Session history
- ✅ MLflow experiment tracking
- ✅ Ray job submission

**Limitations:**
- ❌ No code execution (sandbox)
- ❌ No elevated agent operations

#### Elevated-Developer User
```
Same as Developer +
- ✅ Code execution in sandboxes (Kata Containers)
- ✅ Elevated agent operations (file system access)
- ✅ Advanced debugging tools
```

#### Admin User
```
Same as Elevated-Developer +
- ✅ Platform configuration
- ✅ User management (FusionAuth)
- ✅ Service monitoring (Prometheus)
- ✅ Infrastructure debugging (Traefik)
```

---

## Access Pattern 2: Direct API (curl, Postman, scripts)

### Inference APIs (No Auth Required)

```bash
# Coding model - NO AUTH REQUIRED
curl -X POST https://shml-platform.tail38b60a.ts.net/api/coding/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5-coder-32b",
    "messages": [{"role": "user", "content": "Write a Python function"}],
    "max_tokens": 500
  }'

# ✅ Works for all users (no auth)
# Response: {"choices": [{"message": {"content": "def example()..."}}]}
```

```bash
# Image generation - NO AUTH REQUIRED
curl -X POST https://shml-platform.tail38b60a.ts.net/api/image/v1/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A futuristic AI assistant",
    "num_inference_steps": 4
  }'

# ✅ Works for all users (no auth)
# Response: {"image": "data:image/png;base64,..."}
```

### Agent API (Developer+ Required)

```bash
# Agent execution - REQUIRES DEVELOPER+ ROLE
curl -X POST https://shml-platform.tail38b60a.ts.net/api/agent/v1/agent/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $FUSIONAUTH_TOKEN" \
  -d '{
    "user_id": "user-123",
    "session_id": "session-456",
    "task": "Train YOLOv8 model on face detection",
    "category": "ml-workflow",
    "max_iterations": 5
  }'

# ✅ Developer+ with valid token
# Response: {"session_id": "session-456", "generator_output": "...", "rubric_scores": {...}}

# ❌ Guest user (no token)
# Response: 401 Unauthorized

# ❌ Developer without token
# Response: 401 Unauthorized
```

### MLflow API (Developer+ Required)

```bash
# Create experiment - REQUIRES DEVELOPER+ ROLE
curl -X POST https://shml-platform.tail38b60a.ts.net/api/2.0/mlflow/experiments/create \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $FUSIONAUTH_TOKEN" \
  -d '{
    "name": "face-detection-v2",
    "artifact_location": "s3://mlflow-artifacts/face-detection"
  }'

# ✅ Developer+ with valid token
# Response: {"experiment_id": "1"}

# ❌ Guest user
# Response: 401 Unauthorized
```

### Obtaining FusionAuth Token

```bash
# OAuth2 flow (for Developer+ users)
1. Navigate to https://shml-platform.tail38b60a.ts.net/auth/oauth2/authorize
2. Login with Google/GitHub/Twitter
3. Extract access_token from redirect URL or cookie
4. Use in Authorization header

# Example with FusionAuth API
curl -X POST https://shml-platform.tail38b60a.ts.net/auth/api/login \
  -H "Content-Type: application/json" \
  -d '{
    "loginId": "user@example.com",
    "password": "password",
    "applicationId": "$APPLICATION_ID"
  }' | jq -r '.token'

# Save token
export FUSIONAUTH_TOKEN="eyJhbGciOi..."
```

---

## Access Pattern 3: Cursor IDE Integration

### Setup for Each Role

#### Guest User (Inference Only)

**Cursor Settings (No Auth):**

```json
{
  "cursor.chat.models": [
    {
      "name": "SHML Platform - Qwen2.5-Coder-32B",
      "apiUrl": "https://shml-platform.tail38b60a.ts.net/api/coding/v1/chat/completions",
      "model": "qwen2.5-coder-32b",
      "contextLength": 4096,
      "requiresAuth": false
    }
  ]
}
```

**Features:**
- ✅ Code completion
- ✅ Chat with coding model
- ✅ Code generation
- ❌ No agent orchestration
- ❌ No MLflow integration
- ❌ No Ray job submission

#### Developer User (Full Platform)

**Cursor Settings (With Auth):**

```json
{
  "cursor.chat.models": [
    {
      "name": "SHML Platform - Qwen2.5-Coder-32B",
      "apiUrl": "https://shml-platform.tail38b60a.ts.net/api/coding/v1/chat/completions",
      "model": "qwen2.5-coder-32b",
      "contextLength": 4096,
      "requiresAuth": false  // Inference no auth
    },
    {
      "name": "SHML Agent Service",
      "apiUrl": "https://shml-platform.tail38b60a.ts.net/api/agent/v1/agent/execute",
      "model": "agent-grc",
      "contextLength": 8192,
      "requiresAuth": true,
      "authToken": "${env:FUSIONAUTH_TOKEN}"
    }
  ],
  "cursor.mlflow.enabled": true,
  "cursor.mlflow.trackingUri": "https://shml-platform.tail38b60a.ts.net/mlflow",
  "cursor.mlflow.authToken": "${env:FUSIONAUTH_TOKEN}"
}
```

**Environment Variables:**
```bash
# ~/.bashrc or ~/.zshrc
export FUSIONAUTH_TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
export MLFLOW_TRACKING_URI="https://shml-platform.tail38b60a.ts.net/mlflow"
export MLFLOW_TRACKING_TOKEN="$FUSIONAUTH_TOKEN"
```

**Features:**
- ✅ Code completion with 32B model
- ✅ Agent orchestration (G-R-C workflow)
- ✅ MLflow experiment tracking
- ✅ Ray job submission
- ✅ Multi-skill workflows
- ❌ No code execution (sandbox)

#### Elevated-Developer User

**Additional Features:**
```json
{
  "cursor.agent.sandboxEnabled": true,
  "cursor.agent.elevatedOperations": true
}
```

**Features:**
- ✅ All Developer features +
- ✅ Code execution in sandboxes
- ✅ File system operations
- ✅ Elevated agent skills

---

## Token Management & Security

### Obtaining Tokens

**Method 1: FusionAuth API (Programmatic)**
```bash
curl -X POST https://shml-platform.tail38b60a.ts.net/auth/api/login \
  -H "Content-Type: application/json" \
  -d '{
    "loginId": "user@example.com",
    "password": "password",
    "applicationId": "YOUR_APP_ID"
  }' | jq -r '.token'
```

**Method 2: OAuth2 Flow (Browser)**
```
1. Open https://shml-platform.tail38b60a.ts.net/auth/oauth2/authorize
2. Login with Google/GitHub/Twitter
3. Extract token from cookie or redirect
4. Save to environment variable
```

**Method 3: Long-Lived API Keys (Recommended)**
```
1. Login to FusionAuth Admin: https://shml-platform.tail38b60a.ts.net/auth/admin/
2. Navigate to Users → Select User
3. API Keys tab → Generate New Key
4. Set expiration (90 days recommended)
5. Save key securely
```

### Token Storage

**Linux/macOS:**
```bash
# Store in environment variable (session only)
export FUSIONAUTH_TOKEN="your-token-here"

# Store in .bashrc/.zshrc (persistent)
echo 'export FUSIONAUTH_TOKEN="your-token-here"' >> ~/.bashrc
source ~/.bashrc

# Store in keyring (most secure)
secret-tool store --label="FusionAuth Token" fusionauth token
# Retrieve with:
secret-tool lookup fusionauth token
```

**Windows:**
```powershell
# Store in environment variable (session only)
$env:FUSIONAUTH_TOKEN = "your-token-here"

# Store in user profile (persistent)
[System.Environment]::SetEnvironmentVariable("FUSIONAUTH_TOKEN", "your-token-here", "User")

# Store in Credential Manager
cmdkey /generic:FusionAuth /user:token /pass:"your-token-here"
```

### Token Security Best Practices

1. **Never commit tokens to git**
   - Use `.gitignore` for `.env` files
   - Use environment variables or secret managers

2. **Rotate tokens regularly**
   - Set expiration (30-90 days)
   - Regenerate before expiration

3. **Use minimal scopes**
   - Developer role for most work
   - Elevated-Developer only when needed
   - Admin only for platform management

4. **Revoke compromised tokens immediately**
   - FusionAuth Admin → API Keys → Revoke

---

## User Flow Examples

### Example 1: Developer Using Chat UI

```
1. Navigate to https://shml-platform.tail38b60a.ts.net/chat
2. Redirected to FusionAuth login
3. Click "Login with Google"
4. Google OAuth consent screen
5. Redirected back to Chat UI (authenticated)
6. Start conversation: "Write a Python function to process images"
7. Qwen2.5-Coder-32B responds with code
8. Click "Run with Agent" button
9. Agent Service (G-R-C workflow):
   - Generator creates action plan
   - Reflector evaluates with rubric scores
   - Curator extracts lessons
10. Results displayed in UI with stage outputs
```

### Example 2: Developer Using API

```bash
# 1. Obtain token
TOKEN=$(curl -X POST https://shml-platform.tail38b60a.ts.net/auth/api/login \
  -H "Content-Type: application/json" \
  -d '{"loginId":"dev@example.com","password":"pass123"}' \
  | jq -r '.token')

# 2. Call inference API (no auth needed)
curl -X POST https://shml-platform.tail38b60a.ts.net/api/coding/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5-coder-32b","messages":[{"role":"user","content":"Explain async/await"}]}'

# 3. Call agent API (auth required)
curl -X POST https://shml-platform.tail38b60a.ts.net/api/agent/v1/agent/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "user_id": "dev-user",
    "session_id": "session-1",
    "task": "Create MLflow experiment for YOLOv8 training",
    "category": "ml-workflow"
  }'

# 4. Result: Agent orchestrates MLflow + Ray
# - Creates experiment in MLflow
# - Submits Ray job for training
# - Monitors progress
# - Registers model in MLflow
# - Updates documentation
```

### Example 3: Elevated-Developer Using Cursor

```
1. Set environment variables in ~/.bashrc:
   export FUSIONAUTH_TOKEN="..."
   export MLFLOW_TRACKING_URI="https://shml-platform.tail38b60a.ts.net/mlflow"

2. Configure Cursor settings.json with SHML models

3. In Cursor, start coding:
   - Code completion uses Qwen2.5-Coder-32B
   - Chat uses agent service for complex tasks

4. Ask Cursor: "Train YOLOv8 on my dataset and log to MLflow"

5. Agent orchestrates:
   - Analyzes dataset structure
   - Creates MLflow experiment
   - Submits Ray job for training (GPU)
   - Monitors progress
   - Logs metrics in real-time
   - Registers model when complete
   - Updates project documentation

6. View results:
   - MLflow UI: https://shml-platform.tail38b60a.ts.net/mlflow
   - Ray Dashboard: https://shml-platform.tail38b60a.ts.net/ray
```

---

## Service Access URLs

### Public URLs (Tailscale Funnel)

| Service | URL | Auth Required |
|---------|-----|---------------|
| Chat UI | https://shml-platform.tail38b60a.ts.net/chat | Yes (Developer+) |
| Coding API | https://shml-platform.tail38b60a.ts.net/api/coding/* | No |
| Image Gen API | https://shml-platform.tail38b60a.ts.net/api/image/* | No |
| Agent API | https://shml-platform.tail38b60a.ts.net/api/agent/* | Yes (Developer+) |
| MLflow | https://shml-platform.tail38b60a.ts.net/mlflow | Yes (Developer+) |
| Ray Dashboard | https://shml-platform.tail38b60a.ts.net/ray | Yes (Developer+) |
| Grafana | https://shml-platform.tail38b60a.ts.net/grafana | Yes (Developer+) |
| FusionAuth | https://shml-platform.tail38b60a.ts.net/auth | No (login page) |
| FusionAuth Admin | https://shml-platform.tail38b60a.ts.net/auth/admin | Yes (Admin only) |

### Local URLs (Development)

| Service | URL | Auth Required |
|---------|-----|---------------|
| Chat UI | http://localhost/chat | Yes (Developer+) |
| Coding API | http://localhost/api/coding/* | No |
| Agent API | http://localhost/api/agent/* | Yes (Developer+) |
| MLflow | http://localhost/mlflow | Yes (Developer+) |
| Ray Dashboard | http://localhost/ray | Yes (Developer+) |
| Traefik Dashboard | http://localhost:8090 | Yes (Admin only) |

---

## Role Assignment

### Assigning Roles in FusionAuth

**Via FusionAuth Admin UI:**
```
1. Login: https://shml-platform.tail38b60a.ts.net/auth/admin
2. Navigate to Users
3. Click user to edit
4. Registrations tab → ML Platform Application
5. Add roles:
   - guest (default)
   - developer (full platform access)
   - elevated-developer (sandbox execution)
   - admin (platform management)
6. Save
```

**Via FusionAuth API:**
```bash
curl -X POST https://shml-platform.tail38b60a.ts.net/auth/api/user/registration/$USER_ID \
  -H "Authorization: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "registration": {
      "applicationId": "$APP_ID",
      "roles": ["developer", "elevated-developer"]
    }
  }'
```

### Default Roles

| User Type | Default Role | Upgrade Path |
|-----------|--------------|--------------|
| New User | guest | Request upgrade from admin |
| Social Login | guest | Auto-upgrade to developer (configurable) |
| Email Signup | guest | Email verification → developer |
| Invited User | developer | Set by admin in invitation |
| Admin | admin | Manual assignment only |

---

## Troubleshooting Access Issues

### Issue: 401 Unauthorized

**Cause:** Missing or invalid token  
**Solution:**
```bash
# Check token
echo $FUSIONAUTH_TOKEN

# Regenerate token
TOKEN=$(curl -X POST https://shml-platform.tail38b60a.ts.net/auth/api/login ...)

# Test token
curl -H "Authorization: Bearer $TOKEN" https://shml-platform.tail38b60a.ts.net/api/agent/health
```

### Issue: 403 Forbidden

**Cause:** User lacks required role  
**Solution:**
1. Check user roles in FusionAuth Admin
2. Verify middleware chain in service labels
3. Check role-auth service logs:
   ```bash
   docker logs role-auth
   ```

### Issue: Redirect Loop

**Cause:** OAuth2 misconfiguration  
**Solution:**
```bash
# Run OAuth fix script
./start_all_safe.sh fix-oauth

# Check OAuth2-Proxy logs
docker logs oauth2-proxy

# Verify callback URLs in FusionAuth
```

### Issue: Token Expired

**Cause:** Token TTL exceeded  
**Solution:**
```bash
# Generate new token with longer TTL
curl -X POST https://shml-platform.tail38b60a.ts.net/auth/api/login \
  -H "Content-Type: application/json" \
  -d '{
    "loginId": "user@example.com",
    "password": "password",
    "applicationId": "$APP_ID",
    "noJWT": false  # Get JWT with refresh token
  }'
```

---

## Next Steps

1. **For Developers:**
   - Obtain FusionAuth account (request from admin)
   - Generate long-lived API key
   - Configure Cursor with SHML models
   - Start building with agent orchestration

2. **For Admins:**
   - Set up user accounts in FusionAuth
   - Configure default roles for new users
   - Monitor role-auth middleware logs
   - Review access patterns in Grafana

3. **For Platform Integration:**
   - Implement Cursor extension for SHML models
   - Create VSCode extension with agent integration
   - Build Slack bot with agent backend
   - Add GitHub Actions integration

---

**Prepared by:** AI Assistant  
**Date:** December 7, 2025  
**Status:** ✅ Comprehensive Auth Flow Documentation
