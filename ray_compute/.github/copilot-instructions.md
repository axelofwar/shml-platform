# GitHub Copilot Instructions - Ray Compute

**Last Updated:** 2025-11-23  
**Version:** 0.1.0  
**Part of:** ML Platform (MLflow + Ray + Traefik)  
**License:** MIT

---

## Repository Context

**Project:** ML Platform v0.1.0 - Production-ready distributed ML infrastructure  
**This Component:** Ray Compute cluster (10 containers) with GPU support  
**Integration:** MLflow tracking via shared `ml-platform` network and Traefik gateway  
**Status:** ✅ Fully operational, all services healthy

**Key Principles:**
- All secrets in `.env` (git-ignored)
- OAuth via Authentik (configured, not enforced)
- Documentation <20 files total (currently 17)
- Professional GitHub-ready structure

---

## ⚠️ DOCUMENTATION POLICY - READ FIRST

### Documentation Structure (v0.1.0)

**Project maintains <20 total documentation files. Current: 17 files.**

### Core Documentation (11 files)

**Root Level:**
1. **README.md** - Project overview, quick start, status
2. **ARCHITECTURE.md** - System design, infrastructure, monitoring
3. **API_REFERENCE.md** - All APIs (MLflow, Ray, Traefik)
4. **INTEGRATION_GUIDE.md** - Ray jobs, OAuth, service integration, best practices
5. **TROUBLESHOOTING.md** - Issues and solutions (800+ lines)
6. **LESSONS_LEARNED.md** - Critical patterns (Ray memory allocation, Traefik routing, startup)
7. **REMOTE_QUICK_REFERENCE.md** - Remote access guide (public)
8. **NEW_GPU_SETUP.md** - GPU configuration (exportable)

**Subproject:**
9. **mlflow-server/README.md** - MLflow operations
10. **ray_compute/README.md** - Ray operations (this directory)

**AI Context:**
11. **Copilot instructions** (this file + mlflow-server/.github/copilot-instructions.md)

**Project Files (6):** CHANGELOG.md, CONTRIBUTING.md, LICENSE, CODE_OF_CONDUCT.md, .gitignore, REMOTE_ACCESS_COMPLETE.sh

### Rules for Documentation Changes

1. **ALWAYS update existing docs** - Never create new files

2. **Check these files first:**
   - Ray usage/jobs → INTEGRATION_GUIDE.md
   - Ray memory/GPU → LESSONS_LEARNED.md
   - Ray issues → TROUBLESHOOTING.md
   - System design → ARCHITECTURE.md
   - APIs → API_REFERENCE.md
   - Ray operations → ray_compute/README.md

3. **If new file absolutely needed:**
   - Explain why existing docs can't accommodate
   - Show it won't exceed 20 file limit  
   - Get explicit approval

4. **Never create:**
   - Duplicate guides (we consolidated 74 → 17 files in v0.1.0)
   - Status files (use README.md)
   - OAuth guides (use INTEGRATION_GUIDE.md)
   - Troubleshooting docs (use TROUBLESHOOTING.md)

5. **Update CHANGELOG.md** for all changes

**Example dialogue:**
```
User: "Document the scheduler algorithm"
Bad: Create SCHEDULER_DESIGN.md
Good: "Adding scheduler section to ARCHITECTURE.md because it's core architecture decision"
```

---

## Critical OAuth Patterns

**Problem:** NextAuth.js circular redirects with Authentik
**Solution:** Manual issuer/JWKS config (see LESSONS_LEARNED.md)

**Problem:** React hydration errors
**Solution:** Mounting guard pattern (see LESSONS_LEARNED.md)
- **Solution:** ALWAYS use manual endpoint configuration:
```typescript
export const authOptions: NextAuthOptions = {
  providers: [
    {
      id: "authentik",
      name: "Authentik",
      type: "oauth",
      clientId: process.env.AUTHENTIK_CLIENT_ID!,
      clientSecret: process.env.AUTHENTIK_CLIENT_SECRET!,
      // CRITICAL: Must manually specify ALL endpoints
      authorization: {
        url: `${process.env.NEXT_PUBLIC_AUTHENTIK_URL}/application/o/authorize/`,
        params: { scope: "openid email profile" }
      },
      token: `${process.env.AUTHENTIK_URL}/application/o/token/`,
      userinfo: `${process.env.AUTHENTIK_URL}/application/o/userinfo/`,
      // CRITICAL: Must specify issuer and jwks_endpoint
      issuer: process.env.AUTHENTIK_URL,
      jwks_endpoint: `${process.env.AUTHENTIK_URL}/application/o/ray-compute-api/jwks/`,
      profile(profile) {
        return {
          id: profile.sub,
          email: profile.email,
          name: profile.name || profile.email,
        }
      },
    },
  ],
  // CRITICAL: callbacks are required for proper session handling
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account) {
        token.accessToken = account.access_token;
        token.idToken = account.id_token;
      }
      return token;
    },
    async session({ session, token }) {
      session.accessToken = token.accessToken as string;
      return session;
    },
  },
};
```

**Problem 2: Docker Networking - Dual URL Strategy**
- **Root Cause:** Browser needs public URL, server-side code needs internal Docker URL
- **Solution:** ALWAYS use TWO different environment variables:
```bash
# Public URL for browser (client-side)
NEXT_PUBLIC_AUTHENTIK_URL=http://${TAILSCALE_IP}:9000

# Internal URL for server-side (container-to-container)
AUTHENTIK_URL=http://authentik:9000
```
- **Why:** Browser can't resolve Docker service names, server can't use external IPs

### React Hydration Errors (MUST FOLLOW)

**Problem: "Minified React error #310" or "Text content does not match"**
- **Root Cause:** Accessing browser-only APIs during SSR
- **Solution:** ALWAYS use mounting guard pattern:
```typescript
'use client';

export default function MyComponent() {
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  // During SSR and first client render, return consistent fallback
  if (!isMounted) {
    return <div>Loading...</div>;
  }

  // After mounting, safe to use browser APIs
  const data = localStorage.getItem('key');
  return <div>{data}</div>;
}
```
- **Never:** Access `window`, `localStorage`, `document` outside useEffect
- **Never:** Return different content on server vs initial client render

### Tailwind CSS in Docker Production (CRITICAL)

**Problem: Styles Not Loading in Production Build**
- **Root Cause 1:** Missing `tailwindcss-animate` in dependencies
- **Root Cause 2:** Missing `postcss.config.js`
- **Root Cause 3:** Using `npm ci --production` which skips devDependencies

**Solution - ALWAYS verify these files exist:**

1. **package.json** - `tailwindcss-animate` in dependencies (NOT devDependencies):
```json
{
  "dependencies": {
    "tailwindcss-animate": "^1.0.7"
  }
}
```

2. **postcss.config.js** - MUST exist in web_ui root:
```javascript
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

3. **tailwind.config.js** - Use JavaScript (not TypeScript) to avoid require() errors:
```javascript
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  plugins: [require("tailwindcss-animate")],
};
```

4. **Dockerfile** - NEVER use `--production` flag:
```dockerfile
# WRONG
RUN npm ci --production

# CORRECT
RUN npm ci
```

**Verification:**
```bash
# CSS file should be >15KB (not 2KB)
docker run --rm IMAGE sh -c 'wc -c /app/.next/static/css/*.css'
# Should show ~16000 bytes, not ~2000
```

### Next.js 14 Standalone Build (REQUIRED FOR DOCKER)

**Dockerfile Pattern:**
```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

# CRITICAL: Copy all three directories
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
```

**next.config.js:**
```javascript
module.exports = {
  output: 'standalone',  // CRITICAL for Docker
}
```

### Environment Variables Pattern

**ALWAYS follow this pattern:**
```bash
# .env file
# Public URLs (browser access) - use NEXT_PUBLIC_ prefix
NEXT_PUBLIC_AUTHENTIK_URL=http://${TAILSCALE_IP}:9000
NEXT_PUBLIC_API_URL=http://${TAILSCALE_IP}:8000

# Internal URLs (server-side, container-to-container) - NO prefix
AUTHENTIK_URL=http://authentik:9000
API_URL=http://api:8000

# Secrets (server-side only) - NO prefix
NEXTAUTH_SECRET=<openssl rand -base64 32>
AUTHENTIK_CLIENT_SECRET=<openssl rand -base64 96>

# NextAuth URL (public, for callbacks)
NEXTAUTH_URL=http://${TAILSCALE_IP}:3002
```

### Testing Configuration

**Jest Setup (jest.config.js):**
```javascript
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
    '\\.(css|less|scss|sass)$': 'identity-obj-proxy',
  },
  coverageThreshold: {
    global: {
      branches: 70,
      functions: 70,
      lines: 70,
      statements: 70,
    },
  },
};
```

**Jest Setup (jest.setup.js) - ALWAYS mock these:**
```javascript
import '@testing-library/jest-dom';

// Mock next-auth (NO TypeScript annotations in .js files)
jest.mock('next-auth/react', () => ({
  useSession: jest.fn(() => ({ data: null, status: 'loading' })),
  signIn: jest.fn(),
  signOut: jest.fn(),
  SessionProvider: ({ children }) => children,
}));

// Mock next/navigation
jest.mock('next/navigation', () => ({
  useRouter: jest.fn(() => ({
    push: jest.fn(),
    replace: jest.fn(),
    prefetch: jest.fn(),
  })),
  usePathname: jest.fn(),
}));
```

---

## 🏗️ Architecture & Services

### Service Topology

```
ray_compute/
├── api/                        # FastAPI server (OAuth-enabled)
├── config/                     # Configuration templates
├── docker/                     # Service dockerfiles
├── scripts/                    # Management utilities
├── data/                       # Persistent data (gitignored)
├── logs/                       # Service logs (gitignored)
├── secrets/                    # Sensitive files (gitignored)
└── backups/                    # Database backups (gitignored)
```

### Running Services

| Service | Container | Port | Purpose | Credentials Location |
|---------|-----------|------|---------|---------------------|
| **Web UI** | `ray-compute-ui` | 3002 | Next.js dashboard with OAuth | `.env`: NEXTAUTH_SECRET |
| **Authentik Server** | `authentik-server` | 9000, 9443 | OAuth2/OpenID provider | `.env`: AUTHENTIK_SECRET_KEY |
| **Authentik Worker** | `authentik-worker` | - | Background tasks | Same as server |
| **Authentik PostgreSQL** | `authentik-postgres` | - | Authentik database | `.env`: AUTHENTIK_DB_PASSWORD |
| **Authentik Redis** | `authentik-redis` | - | Cache/sessions | No password |
| **Ray Compute API** | `ray-compute-api` | 8000, 8266 | Job submission API | `.env`: API_SECRET_KEY |
| **Ray Compute DB** | PostgreSQL | 5432 | Jobs/users/quotas | `.env`: POSTGRES_PASSWORD |
| **Ray Redis** | `ray-redis` | 6379 | Job queue | No password |
| **Prometheus** | `ray-prometheus` | 9090 | Metrics collection | No auth |
| **Loki** | `ray-loki` | 3100 | Log aggregation | No auth |
| **Promtail** | `ray-promtail` | - | Log shipping | - |
| **Grafana** | `ray-grafana` | 3001 | Visualization | `.env`: GRAFANA_ADMIN_PASSWORD |
| **Node Exporter** | `ray-node-exporter` | 9100 | Host metrics | - |
| **GPU Exporter** | `ray-gpu-exporter` | 9835 | GPU metrics | - |

### Service Access URLs

**Local Access:**
```bash
# Web UI
http://localhost:3002              # Next.js Dashboard

# Authentication
http://localhost:9000              # Authentik (OAuth)

# API & Job Management
http://localhost:8000              # Ray Compute API
http://localhost:8000/docs         # API Documentation (Swagger)

# Monitoring
http://localhost:3001              # Grafana
http://localhost:9090              # Prometheus
http://localhost:3100              # Loki
http://localhost:9100              # Node Exporter

# Database
postgresql://localhost:5432/ray_compute  # Ray Compute DB
```

**Tailscale VPN Access:**
```bash
# Use TAILSCALE_IP from .env (detect dynamically)
TAILSCALE_IP=$(tailscale ip -4)

http://${TAILSCALE_IP}:3002        # Web UI Dashboard
http://${TAILSCALE_IP}:9000        # Authentik
http://${TAILSCALE_IP}:8000        # Ray Compute API
http://${TAILSCALE_IP}:3001        # Grafana
```

---

## 🔒 Security & Secrets Management

### Critical Rules

1. **NEVER hardcode secrets, IPs, or passwords**
2. **NEVER commit `.env`, `CURRENT_DEPLOYMENT.md`, `secrets/`, `data/`, or `logs/`**
3. **ALWAYS use environment variables and placeholders in committed files**
4. **ALWAYS validate `.gitignore` before creating new files with secrets**

### Where Secrets Live

```bash
# Primary configuration
.env                             # All secrets and config (gitignored)
.env.example                     # Template only (safe to commit)

# OAuth credentials
AUTHENTIK_CLIENT_ID              # In .env
AUTHENTIK_CLIENT_SECRET          # In .env (128-char secret)

# Database passwords
POSTGRES_PASSWORD                # Ray Compute DB (in .env)
AUTHENTIK_DB_PASSWORD            # Authentik internal DB (in .env)

# API keys
API_SECRET_KEY                   # For JWT tokens (in .env)

# Monitoring
GRAFANA_ADMIN_PASSWORD           # In .env

# Notifications
NTFY_ADMIN_TOPIC                 # In .env (with random ID)
NTFY_USER_TOPIC                  # In .env (with random ID)
```

### Safe Placeholder Patterns

**❌ WRONG:**
```python
AUTHENTIK_URL = "http://${TAILSCALE_IP}:9000"
CLIENT_SECRET = "5fPlqHZ7xHRmnG7Lf93YhAy5GCLPXX..."
DB_PASSWORD = "VlzT9Rg374pYWpjUGGV3QSU..."
```

**✅ CORRECT:**
```python
# In code
AUTHENTIK_URL = os.getenv("AUTHENTIK_URL")
CLIENT_SECRET = os.getenv("AUTHENTIK_CLIENT_SECRET")

# In documentation
AUTHENTIK_URL=http://<TAILSCALE_IP>:9000
CLIENT_SECRET=<from-authentik-oauth-provider>
DB_PASSWORD=<generated-by-setup-script>

# In docker-compose.yml
environment:
  - AUTHENTIK_URL=${AUTHENTIK_URL}
  - CLIENT_SECRET=${AUTHENTIK_CLIENT_SECRET}
```

---

## 🐳 Docker Architecture & Service Management

### Multi-Service Deployment

```bash
# Three separate compose files for modularity
docker-compose.auth.yml          # Authentik OAuth (4 containers)
docker-compose.observability.yml # Monitoring stack (6 containers)
docker-compose.api.yml           # Ray Compute API (1 container)
```

### Service Management Commands

**✅ ALWAYS use start_all_safe.sh from project root:**
```bash
# Navigate to project root first
cd /home/axelofwar/Projects/shml-platform

# Restart Ray services (CORRECT METHOD)
./start_all_safe.sh restart ray

# Start Ray services
./start_all_safe.sh start ray

# Stop Ray services
./start_all_safe.sh stop ray

# Check platform status
./start_all_safe.sh status
```

**❌ NEVER use direct docker compose commands:**
```bash
# ❌ WRONG - skips migrations, wrong order, orphaned containers
docker-compose -f ray_compute/docker-compose.yml restart ray-compute-api
docker compose up -d --build ray-compute-ui
docker-compose down
```

**View logs (read-only, always safe):**
```bash
docker logs ray-compute-api -f
docker logs ray-compute-ui -f
docker logs ray-head -f
```

### Container Networking

```bash
# All services use shared network
networks:
  ray-compute:
    name: ray-compute
    external: true

# Create network (if needed)
docker network create ray-compute
```

---

## 📊 Database Schema & Models

### PostgreSQL Tables

**Location:** `config/database_schema.sql`

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `users` | User accounts | user_id, username, email, role, oauth_sub |
| `user_quotas` | Resource limits | max_concurrent_jobs, max_gpu_hours_per_day, priority_weight |
| `jobs` | Job execution records | job_id, user_id, status, gpu_requested, artifact_path |
| `job_queue` | Scheduling queue | queue_id, priority_score, position_in_queue |
| `artifact_versions` | Output versioning | artifact_id, job_id, version, expires_at |
| `resource_usage_daily` | Usage aggregation | user_id, usage_date, cpu_hours, gpu_hours |
| `audit_log` | Security tracking | user_id, action, resource_type, ip_address |
| `system_alerts` | System notifications | severity, alert_type, message, resolved_at |

### ORM Models

**Location:** `api/models.py`

```python
# SQLAlchemy models mirror database schema
from api.models import User, Job, UserQuota, JobQueue

# Example query
from api.database import get_db
db = next(get_db())
user = db.query(User).filter(User.email == "user@example.com").first()
jobs = db.query(Job).filter(Job.user_id == user.user_id).all()
```

### Database Access

```bash
# Connect to Ray Compute database
PGPASSWORD=$(grep POSTGRES_PASSWORD .env | cut -d= -f2) \
  psql -h localhost -U ray_compute -d ray_compute

# Run queries
\dt                              # List tables
\d users                         # Describe users table
SELECT * FROM users;             # Query users
SELECT COUNT(*) FROM jobs WHERE status='RUNNING';

# Apply schema changes
psql -h localhost -U ray_compute -d ray_compute -f config/database_schema.sql
```

---

## 🔐 OAuth Authentication Flow

### Authentik Configuration

**Admin Interface:** `http://localhost:9000` or `http://${TAILSCALE_IP}:9000`

**Login:**
- Username: `akadmin`
- Password: Reset using recovery token (see setup script)

### OAuth Provider Setup

**Provider Name:** Ray Compute API  
**Client Type:** Confidential  
**Client ID:** `ray-compute-api` (in `.env`)  
**Client Secret:** 128-char secret (in `.env`)  
**Redirect URIs:**
```
http://localhost:8000/auth/callback
http://${TAILSCALE_IP}:8000/auth/callback
```

### User Groups & Tiers

| Group | Tier | Max Jobs | GPU Limit | Special Privileges |
|-------|------|----------|-----------|-------------------|
| `admins` | admin | 999 | 1.0 | Custom Docker, skip validation, unlimited timeout |
| `premium` | premium | 10 | 1.0 | Custom Docker |
| `users` | user | 3 | 0.5 | Standard access |

### API Authentication

```python
# Client-side: Get OAuth token
import requests

# Authorize endpoint
auth_url = f"{AUTHENTIK_URL}/application/o/authorize/"
params = {
    "client_id": CLIENT_ID,
    "redirect_uri": "http://localhost:8000/auth/callback",
    "response_type": "code",
    "scope": "openid email profile groups"
}

# Exchange code for token
token_url = f"{AUTHENTIK_URL}/application/o/token/"
data = {
    "grant_type": "authorization_code",
    "code": auth_code,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri": redirect_uri
}
token = requests.post(token_url, data=data).json()["access_token"]

# Use token in API requests
headers = {"Authorization": f"Bearer {token}"}
response = requests.get("http://localhost:8000/api/v1/user/me", headers=headers)
```

---

## 📈 Monitoring & Observability

### Metrics Collection (Prometheus)

**Configuration:** `config/prometheus.yml`

**Scrape Targets:**
- API server: `:8000/metrics`
- Node exporter: `:9100/metrics`
- GPU exporter: `:9835/metrics`
- Prometheus self: `:9090/metrics`
- Ray dashboard: `:8265/metrics`

**Query Examples:**
```promql
# Job queue length
ray_job_queue_length

# GPU utilization
nvidia_gpu_utilization_percent

# API request rate
rate(api_requests_total[5m])

# Error rate
rate(api_errors_total[5m])
```

### Log Aggregation (Loki)

**Configuration:** `config/loki.yml`

**Log Sources (via Promtail):**
- API server: `/app/logs/*.log`
- Ray logs: `/opt/ray/logs/*.log`
- System logs: `/var/log/*.log`
- Docker containers: Docker API

**Query Examples (LogQL):**
```logql
# API errors
{job="ray-compute-api"} |= "ERROR"

# Authentication failures
{job="authentik"} |= "login failed"

# GPU allocation events
{job="ray-compute-api"} |= "GPU allocated"
```

### Visualization (Grafana)

**Access:** `http://localhost:3001`  
**Credentials:**
- Username: `admin`
- Password: See `.env` → `GRAFANA_ADMIN_PASSWORD`

**Datasources (pre-configured):**
- Prometheus: `http://ray-prometheus:9090`
- Loki: `http://ray-loki:3100`

**Dashboard Locations:** `config/grafana/dashboards/` (to be created)

---

## 🔔 Notifications (ntfy.sh + Apprise)

### Configuration

**Config File:** `config/notifications.conf`

**Topics (zero-cost, public ntfy.sh):**
```bash
# Admin alerts (storage, GPU temp, services down)
NTFY_ADMIN_TOPIC=ray-compute-admin-<random-id>

# User job notifications (completion, failures)
NTFY_USER_TOPIC=ray-compute-jobs-<random-id>

# System alerts (health checks)
NTFY_SYSTEM_TOPIC=ray-compute-system-<random-id>
```

### Subscribe to Notifications

**On Mobile:**
1. Install ntfy app (iOS/Android)
2. Add topic: `ray-compute-admin-<id>` (from `.env`)
3. Enable notifications

**Test Notification:**
```bash
# Admin alert
curl -d "Test admin alert" https://ntfy.sh/ray-compute-admin-<id>

# Job notification
curl -d "Job completed: job-123" https://ntfy.sh/ray-compute-jobs-<id>
```

### Notification Triggers

**Automatic Alerts:**
- Storage > 90% → Admin
- GPU temp > 80°C → Admin
- Service down > 5min → Admin
- Job completed → User
- Job failed → User
- Quota exceeded → User

---

## 🚀 API Server Development

### FastAPI Structure

```
api/
├── __init__.py                 # Package init
├── server_v2.py                # Main FastAPI app
├── auth.py                     # OAuth middleware
├── models.py                   # SQLAlchemy ORM
├── database.py                 # DB connection
├── validators.py               # Input validation (TODO)
├── scheduler.py                # GPU scheduler (TODO)
├── queue.py                    # Job queue (TODO)
├── notifications.py            # Apprise integration (TODO)
└── admin_api.py                # Admin endpoints (TODO)
```

### Running the API Server

**Development (local):**
```bash
# Install dependencies
pip install -r requirements.txt

# Run with uvicorn
python -m uvicorn api.server_v2:app --host 0.0.0.0 --port 8000 --reload
```

**Production (Docker):**
```bash
# Build image
docker build -t ray-compute-api:latest -f Dockerfile.api .

# Start with compose
docker-compose -f docker-compose.api.yml up -d

# View logs
docker logs ray-compute-api -f
```

### API Endpoints

**User Endpoints:**
```
GET  /                          # API info
GET  /health                    # Health check
GET  /docs                      # Swagger UI
GET  /api/v1/user/me            # Current user profile
GET  /api/v1/user/quota         # User quotas
GET  /api/v1/jobs               # List jobs (paginated)
GET  /api/v1/jobs/{job_id}      # Job details
POST /api/v1/jobs               # Submit job
DELETE /api/v1/jobs/{job_id}    # Cancel job
```

**Admin Endpoints (TODO):**
```
GET  /api/v1/admin/users        # List all users
POST /api/v1/admin/users/{id}/suspend  # Suspend user
GET  /api/v1/admin/system       # System stats
GET  /api/v1/admin/alerts       # System alerts
```

---

## 🎛️ Configuration Management

### Environment Variables

**Core Config (`.env`):**
```bash
# Database
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=ray_compute
POSTGRES_USER=ray_compute
POSTGRES_PASSWORD=<generated>

# Authentik OAuth
AUTHENTIK_URL=http://<TAILSCALE_IP>:9000
AUTHENTIK_CLIENT_ID=ray-compute-api
AUTHENTIK_CLIENT_SECRET=<128-char-secret>

# API
API_HOST=0.0.0.0
API_PORT=8000
API_SECRET_KEY=<generated>
CORS_ORIGINS=http://localhost:3000,http://<TAILSCALE_IP>:3000

# Monitoring
GRAFANA_ADMIN_PASSWORD=<generated>

# Notifications
NTFY_ADMIN_TOPIC=ray-compute-admin-<random>
NTFY_USER_TOPIC=ray-compute-jobs-<random>

# Tailscale
TAILSCALE_IP=<detected-dynamically>
```

### Dynamic IP Detection

```bash
# Never hardcode IPs!
TAILSCALE_IP=$(tailscale ip -4)
echo "TAILSCALE_IP=$TAILSCALE_IP" >> .env
```

---

## 📁 File Organization & Best Practices

### Safe to Commit

```
✅ COMMIT THESE:
├── .env.example                # Template
├── README.md                   # Public docs
├── INFRASTRUCTURE_STATUS.md    # Status template
├── IMPLEMENTATION_GUIDE_V2.md  # Implementation guide
├── api/*.py                    # Source code
├── config/*.yml                # Config templates
├── docker/*.dockerfile         # Dockerfiles
├── scripts/*.sh                # Utility scripts
└── .github/                    # Copilot instructions
```

### Never Commit

```
❌ NEVER COMMIT:
├── .env                        # Actual secrets
├── CURRENT_DEPLOYMENT.md       # Live status
├── secrets/                    # Password files
├── data/                       # Persistent data
├── logs/                       # Service logs
├── backups/                    # Database backups
└── __pycache__/                # Python cache
```

### Documentation Structure

```
docs/                           # (To be created)
├── README.md                   # Documentation index
├── API_REFERENCE.md            # API endpoints
├── AUTHENTICATION.md           # OAuth setup
├── DEPLOYMENT.md               # Deployment guide
├── MONITORING.md               # Observability guide
└── TROUBLESHOOTING.md          # Common issues
```

---

## 🛠️ Common Operations

### Setup & Deployment

```bash
# Initial setup
chmod +x scripts/setup_enhanced.sh
./scripts/setup_enhanced.sh

# Start all services
docker-compose -f docker-compose.auth.yml up -d
docker-compose -f docker-compose.observability.yml up -d
docker-compose -f docker-compose.api.yml up -d

# Verify all services
docker ps
curl http://localhost:9000/.well-known/openid-configuration
curl http://localhost:8000/health
```

### Daily Operations

```bash
# Check service status
docker ps --filter "name=ray-" --filter "name=authentik-"

# View API logs
docker logs ray-compute-api --tail 100 -f

# Check database
PGPASSWORD=$(grep POSTGRES_PASSWORD .env | cut -d= -f2) \
  psql -h localhost -U ray_compute -d ray_compute -c "SELECT COUNT(*) FROM jobs;"

# Monitor metrics
open http://localhost:9090      # Prometheus
open http://localhost:3001      # Grafana
```

### Troubleshooting

```bash
# Service won't start
docker logs <container-name>
docker-compose -f <compose-file> down
docker-compose -f <compose-file> up -d

# Database connection issues
docker exec authentik-postgres pg_isready
docker restart authentik-postgres

# OAuth errors
docker logs authentik-server | grep ERROR
docker restart authentik-server

# API errors
docker logs ray-compute-api | grep ERROR
docker exec ray-compute-api env  # Check environment
```

---

## ⚠️ Critical Warnings

### Never Do This

❌ **Hardcode secrets in code:**
```python
# WRONG
AUTHENTIK_CLIENT_SECRET = "5fPlqHZ7xHRmnG7Lf93YhAy5GCLPXX..."
```

❌ **Commit files with secrets:**
```bash
# WRONG
git add .env
git add CURRENT_DEPLOYMENT.md
```

❌ **Use production secrets in documentation:**
```markdown
# WRONG
Password: VlzT9Rg374pYWpjUGGV3QSUTWg7JVdhl
```

❌ **Disable security features:**
```yaml
# WRONG
- GF_AUTH_ANONYMOUS_ENABLED=true
- GF_AUTH_DISABLE_LOGIN_FORM=true
```

### Always Do This

✅ **Load from environment:**
```python
CLIENT_SECRET = os.getenv("AUTHENTIK_CLIENT_SECRET")
```

✅ **Use placeholders in docs:**
```markdown
Password: <from-.env-POSTGRES_PASSWORD>
```

✅ **Validate before committing:**
```bash
git status
grep -r "VlzT9Rg374" .  # Check for leaked secrets
```

✅ **Keep privacy-first:**
```yaml
- GF_ANALYTICS_REPORTING_ENABLED=false
- GF_SECURITY_DISABLE_GRAVATAR=true
```

---

## 🚀 Ray Head Resource Allocation (CRITICAL)

### Memory Allocation Best Practices

**Problem:** Ray head crashes with "amount of memory available for tasks and actors is less than -112%" error.

**Root Cause:** Mismatch between Ray's object store memory allocation and container memory limits.
- Ray tries to allocate: object_store_memory + redis overhead + system overhead
- Container limit may be insufficient
- Object store default (huge) doesn't account for container limits

**Solution Pattern:**
```yaml
# docker-compose.yml - ray-head service
command: >
  ray start --head
  --port=6379
  --dashboard-host=0.0.0.0
  --dashboard-port=8265
  --num-cpus=4                      # Reduced for stability
  --num-gpus=1
  --object-store-memory=1000000000  # 1GB - MUST be < container memory
  --block

shm_size: 2gb                       # Shared memory for Ray

deploy:
  resources:
    limits:
      cpus: '4.0'
      memory: 4G                      # MUST be > object_store + 2GB overhead
    reservations:
      cpus: '1.0'
      memory: 2G
```

**Calculation Rule:**
```
container_memory ≥ object_store_memory + shm_size + 1GB (system overhead)

Example:
- object_store: 1GB
- shm_size: 2GB  
- overhead: ~1GB
- Minimum container memory: 4GB
```

**System Resource Allocation:**
- AMD Ryzen 9 3900X: 24 threads → Allocate 4-8 CPUs to Ray
- 16GB RAM system → Limit Ray to 4GB max (leaves 12GB for host + other services)
- Single GPU → Always `--num-gpus=1`

**Verification:**
```bash
# Check Ray started successfully
docker logs ray-head | grep "Ray runtime started"

# Should NOT see:
# "ValueError: amount of memory...is less than"

# Monitor actual usage
docker stats ray-head --no-stream
```

**Never Do:**
```yaml
# ❌ WRONG - Will crash
command: --object-store-memory=4000000000  # 4GB
deploy:
  resources:
    limits:
      memory: 2G  # Only 2GB container limit!
```

---

## 🐳 Docker & Networking Critical Fixes

### Docker Inter-Container Communication Fix (MANDATORY)

**Problem:** After migrating from snap Docker to apt Docker (docker.io package), containers cannot communicate with each other. Symptoms:
- `docker exec container1 ping container2` returns 100% packet loss
- MLflow cannot connect to PostgreSQL despite being on same network
- Ray services cannot reach each other
- All containers show healthy but fail to communicate

**Root Cause:** Ubuntu's apt Docker package enables `bridge-nf-call-iptables=1` by default. This causes iptables rules (including FORWARD chain DROP policies) to be applied to Docker bridge network traffic, blocking inter-container communication even though they're on the same bridge network.

**Solution (Run Once After Docker Installation):**

```bash
# Disable bridge netfilter - prevents iptables from filtering bridge traffic
sudo sysctl -w net.bridge.bridge-nf-call-iptables=0
sudo sysctl -w net.bridge.bridge-nf-call-ip6tables=0

# Make persistent across reboots
echo "net.bridge.bridge-nf-call-iptables=0" | sudo tee -a /etc/sysctl.conf
echo "net.bridge.bridge-nf-call-ip6tables=0" | sudo tee -a /etc/sysctl.conf

# Restart Docker to apply changes
sudo systemctl restart docker

# Recreate containers with fixed networking
docker-compose down && docker-compose up -d
```

**Verification:**
```bash
# Test inter-container communication
docker run -d --name test1 --network mynetwork alpine sleep 60
docker run -d --name test2 --network mynetwork alpine sleep 60
docker exec test1 ping -c 2 test2  # Should succeed with 0% packet loss
docker rm -f test1 test2
```

**Why This Works:**
- Docker bridge networks create virtual interfaces (br-xxxx) that connect containers
- With bridge-nf-call-iptables=1, all bridge traffic passes through iptables FORWARD chain
- Default FORWARD policy is DROP, blocking container-to-container communication
- Setting bridge-nf-call-iptables=0 bypasses iptables for bridge-local traffic
- Containers can communicate freely while still isolated from external networks

**When To Apply:**
- After installing docker.io via apt (Ubuntu/Debian)
- After system upgrades that reset sysctl settings
- If containers suddenly can't communicate after Docker reinstall
- When migrating from snap Docker to apt Docker

**Alternative (Less Recommended):**
```bash
# If you need bridge netfilter enabled for other reasons
sudo iptables -P FORWARD ACCEPT  # Changes default policy
# But this affects all forwarding, not just Docker
```

---

## 🔧 Service Startup Best Practices

### Phased Startup Pattern (RECOMMENDED)

**Problem:** Starting all services simultaneously causes:
- Dependency race conditions (app starts before database is ready)
- Resource contention (all services competing for CPU/memory)
- Health check failures (dependencies not available yet)
- Orphaned containers from manual docker commands

**Solution:** Use `start_all_safe.sh` pattern with phased startup:

```bash
#!/bin/bash
# Phase 1: Infrastructure (databases, caches, gateway)
docker-compose up -d traefik redis postgres
sleep 10

# Phase 2: Core services (depends on Phase 1)
docker-compose up -d mlflow-server ray-head authentik-server  
sleep 30  # Wait for health checks

# Phase 3: API services (depends on Phase 2)
docker-compose up -d mlflow-api ray-compute-api authentik-worker
sleep 20

# Phase 4: Monitoring & extras
docker-compose up -d prometheus grafana
```

**Cleanup Pattern (CRITICAL):**
```bash
# ALWAYS clean up orphaned containers before starting
docker-compose down --remove-orphans

# Remove manually created containers
ORPHANED=$(docker ps -a --format '{{.Names}}' | grep -E 'mlflow-|ray-|authentik-')
if [ ! -z "$ORPHANED" ]; then
    echo "$ORPHANED" | while read container; do
        docker rm -f "$container" 2>/dev/null || true
    done
fi
```

**Health Check Verification:**
```bash
# Wait for services to become healthy
for service in mlflow-server ray-head postgres; do
    while [ "$(docker inspect --format='{{.State.Health.Status}}' $service 2>/dev/null)" != "healthy" ]; do
        echo "Waiting for $service to be healthy..."
        sleep 5
    done
done
```

**Startup Success Criteria:**
- Infrastructure services: Healthy within 30 seconds
- Core services: Healthy within 90 seconds
- API services: Healthy within 120 seconds
- Total platform ready: < 3 minutes

**Common Mistakes:**
```bash
# ❌ WRONG - No cleanup, no phasing
docker-compose up -d

# ❌ WRONG - Manually creating containers
docker run -d --name mlflow-api ...  # Bypasses compose

# ❌ WRONG - Not removing orphans
docker-compose down  # Missing --remove-orphans

# ✅ CORRECT - Use safe startup script
./start_all_safe.sh
```

---

## 🎓 Development Workflow

### Before Making Changes

1. **Review existing code:**
   ```bash
   ls api/          # Check existing modules
   cat api/server_v2.py  # Review patterns
   ```

2. **Check configuration:**
   ```bash
   cat .env.example  # See available variables
   cat config/database_schema.sql  # Review schema
   ```

3. **Verify services running:**
   ```bash
   docker ps
   curl http://localhost:8000/health
   ```

### Making Changes

1. **Edit code:**
   ```bash
   vim api/server_v2.py
   # Follow existing patterns
   # Use type hints
   # Add docstrings
   ```

2. **Test locally (if not containerized):**
   ```python
   python -m pytest api/tests/
   ```

3. **Test in container:**
   ```bash
   docker build -t ray-compute-api:latest -f Dockerfile.api .
   docker-compose -f docker-compose.api.yml up -d
   docker logs ray-compute-api
   ```

### After Changes

1. **Update documentation:**
   - Update relevant `.md` files
   - Update API examples
   - Update `.github/copilot-instructions.md` if needed

2. **Verify git safety:**
   ```bash
   git status
   git diff
   # Ensure no secrets staged
   ```

3. **Commit with clear message:**
   ```bash
   git add api/server_v2.py
   git commit -m "feat: Add job cancellation endpoint"
   ```

---

## 📚 Quick Reference

### Essential Files

```bash
README.md                          # Project overview
INFRASTRUCTURE_STATUS.md           # Service status
IMPLEMENTATION_GUIDE_V2.md         # Build roadmap
.env.example                       # Config template
.env                               # Actual config (gitignored)
api/server_v2.py                   # Main API
config/database_schema.sql         # Database schema
```

### Essential Commands

```bash
# Services
docker ps
docker logs <container>
docker restart <container>

# Database
PGPASSWORD=<pass> psql -h localhost -U ray_compute -d ray_compute

# Monitoring
open http://localhost:9090  # Prometheus
open http://localhost:3001  # Grafana

# API
curl http://localhost:8000/health
open http://localhost:8000/docs
```

### Logs Locations

```bash
# Container logs
docker logs authentik-server
docker logs ray-compute-api
docker logs ray-prometheus

# File logs (if mounted)
./logs/api/app.log
./logs/authentik/server.log
/opt/ray/logs/*.log               # Ray cluster logs
```

---

## 🔄 Version Information

- **FastAPI:** 0.103.2 (compatible with Ray/pydantic <2)
- **Ray:** 2.8.1
- **Authentik:** 2024.8.6
- **PostgreSQL:** 16
- **Python:** 3.11
- **Docker Compose:** 3.8
- **Prometheus:** 2.48.0
- **Grafana:** 10.2.2
- **Loki:** 2.9.3

---

## 📞 Support & Resources

### Active Documentation (Current)
- **README.md** - Main project overview and quick start
- **LESSONS_LEARNED.md** - Debugging insights and best practices (OAuth, Tailwind, Docker)
- **docs/OAUTH_SETUP_GUIDE.md** - Complete OAuth setup with NextAuth.js and Authentik
- **CONTRIBUTING.md** - Development guidelines and workflow
- **INFRASTRUCTURE_STATUS.md** - Service architecture and status
- **REPOSITORY_STATUS.md** - Repository cleanup summary
- **config/database_schema.sql** - Database schema
- **config/notifications.conf** - Notification configuration
- **.github/copilot-instructions.md** - This file

### Archived Documentation
- **docs/archived/** - Older implementation guides and quickstart docs (kept for reference)

### Testing Documentation
- **web_ui/jest.config.js** - Jest configuration
- **web_ui/jest.setup.js** - Test mocks and setup
- **web_ui/__tests__/** - Test suite (unit + E2E)

### CI/CD
- **.github/workflows/ci.yml** - GitHub Actions pipeline

---

**Last Updated:** November 22, 2025  
**Update these instructions** when discovering new patterns, issues, or best practices!
