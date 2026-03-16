# Ray Compute V2 - Enhanced Implementation Guide

## 🎯 Overview

This guide outlines the complete implementation of Ray Compute V2 with:
- Authentik OAuth authentication
- Enhanced job scheduling with fractional GPU support
- Admin API with elevated privileges
- Grafana observability stack
- Zero-cost notifications
- Smart artifact management

## ⏱️ Time Estimate

**Total: 20-24 hours** (can be done incrementally)

- Phase 1: Authentication & Database (6 hours) ✅ **INFRASTRUCTURE READY**
- Phase 2: Core API Enhancement (8 hours)
- Phase 3: Scheduler & Queue (4 hours)
- Phase 4: Monitoring & CLI (4 hours)
- Phase 5: Documentation & Testing (2 hours)

## 📋 What's Already Done

✅ **Infrastructure Setup:**
- `docker-compose.auth.yml` - Authentik OAuth server
- `docker-compose.observability.yml` - Prometheus + Loki + Grafana
- `config/database_schema.sql` - Complete PostgreSQL schema
- `config/prometheus.yml` - Metrics collection
- `config/loki.yml` - Log aggregation
- `config/notifications.conf` - Notification templates
- `.env.example` - Environment template
- `scripts/setup_enhanced.sh` - Automated setup script

## 🚀 Phase 1: Initial Setup (DO THIS FIRST)

### 1.1 Run Setup Script

```bash
cd /opt/shml-platform/ray_compute
chmod +x scripts/setup_enhanced.sh
./scripts/setup_enhanced.sh
```

This will:
1. Create `.env` with generated passwords
2. Setup PostgreSQL database with schema
3. Start Authentik containers
4. Start observability stack
5. Install Python dependencies

### 1.2 Configure Authentik (Manual - 15 minutes)

1. **Open Authentik:** http://100.69.227.36:9000
2. **Initial Setup:**
   - Email: `admin@raycompute.local`
   - Password: (choose strong password)
   - Complete wizard

3. **Create OAuth Provider:**
   - Go to: Admin Interface → Applications → Providers
   - Click: Create → OAuth2/OpenID Provider
   - Settings:
     - Name: `Ray Compute API`
     - Authorization flow: `default-provider-authorization-implicit-consent`
     - Client type: `Confidential`
     - Redirect URIs: `http://100.69.227.36:8266/auth/callback`
     - Signing Key: `authentik Self-signed Certificate`
   - Click: Finish

4. **Create Application:**
   - Go to: Applications → Create
   - Settings:
     - Name: `Ray Compute`
     - Slug: `ray-compute`
     - Provider: Select the provider you just created
   - Click: Create

5. **Get Credentials:**
   - Click on your OAuth provider
   - Copy `Client ID` and `Client Secret`
   - Update `.env`:
     ```bash
     AUTHENTIK_CLIENT_ID=<paste-client-id>
     AUTHENTIK_CLIENT_SECRET=<paste-client-secret>
     ```

6. **Create User Roles:**
   - Go to: Directory → Groups
   - Create groups: `admins`, `premium`, `users`
   - Add your admin user to `admins` group

### 1.3 Setup Notifications (5 minutes)

**Option 1: ntfy.sh (Easiest)**
1. Install ntfy app on phone: https://ntfy.sh/
2. Check your `.env` for generated ntfy topics
3. Subscribe to topics in app:
   - Admin: `ray-compute-admin-<your-id>`
   - Jobs: `ray-compute-jobs-<your-id>`
   - System: `ray-compute-system-<your-id>`
4. Test: `curl -d "Test" ntfy.sh/ray-compute-admin-<your-id>`

**Option 2: Telegram**
1. Create bot: Chat with @BotFather on Telegram
2. Get bot token
3. Start chat with bot
4. Get chat ID: `curl https://api.telegram.org/bot<TOKEN>/getUpdates`
5. Update `.env`:
   ```bash
   NOTIFICATION_BACKEND=telegram
   TELEGRAM_BOT_TOKEN=<token>
   TELEGRAM_CHAT_ID=<chat-id>
   ```

### 1.4 Verify Infrastructure

```bash
# Check all services
docker ps

# Expected containers:
# - authentik-server
# - authentik-worker
# - authentik-postgres
# - authentik-redis
# - ray-prometheus
# - ray-loki
# - ray-promtail
# - ray-grafana
# - ray-node-exporter
# - ray-cadvisor
# - ray-gpu-exporter
# - ray-redis

# Test services
curl http://localhost:9000/-/health  # Authentik (should return 204)
curl http://localhost:3000/api/health  # Grafana
curl http://localhost:9090/-/healthy  # Prometheus

# Test database
export PGPASSWORD="<password-from-env>"
psql -h localhost -U ray_compute -d ray_compute -c "SELECT COUNT(*) FROM users;"
# Should show at least 1 (admin user)
```

## 🔧 Phase 2: Core API Development

### 2.1 Create OAuth Middleware

Create `api/auth.py`:

```python
"""
OAuth2 Authentication Middleware
Integrates with Authentik for token validation
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2AuthorizationCodeBearer
from jose import JWTError, jwt
from typing import Optional
import httpx
import os

# OAuth2 configuration
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=f"{os.getenv('AUTHENTIK_URL')}/application/o/authorize/",
    tokenUrl=f"{os.getenv('AUTHENTIK_URL')}/application/o/token/"
)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Validate OAuth token and return user info"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # Decode JWT (Authentik uses RS256)
        payload = jwt.decode(
            token,
            key=os.getenv('AUTHENTIK_CLIENT_SECRET'),  # In production, use JWKS
            algorithms=["HS256", "RS256"],
            audience=os.getenv('AUTHENTIK_CLIENT_ID')
        )

        username: str = payload.get("preferred_username")
        user_id: str = payload.get("sub")
        email: str = payload.get("email")
        groups: list = payload.get("groups", [])

        if username is None:
            raise credentials_exception

        # Determine role from groups
        role = "user"
        if "admins" in groups:
            role = "admin"
        elif "premium" in groups:
            role = "premium"

        return {
            "user_id": user_id,
            "username": username,
            "email": email,
            "role": role,
            "groups": groups
        }
    except JWTError:
        raise credentials_exception

async def get_current_admin(current_user: dict = Depends(get_current_user)):
    """Require admin role"""
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user

# Role checkers
def require_role(required_role: str):
    """Dependency factory for role-based access"""
    async def role_checker(current_user: dict = Depends(get_current_user)):
        if current_user["role"] not in ["admin"] and current_user["role"] != required_role:
            if required_role == "premium" and current_user["role"] == "user":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"'{required_role}' role or higher required"
                )
        return current_user
    return role_checker
```

### 2.2 Create Database Models

Create `api/models.py`:

```python
"""
SQLAlchemy models for Ray Compute
"""

from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, DateTime, ARRAY, Text, BigInteger, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import uuid
import os

DATABASE_URL = f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST')}/{os.getenv('POSTGRES_DB')}"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class User(Base):
    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    role = Column(String(50), nullable=False, default="user")
    oauth_sub = Column(String(255), unique=True)
    api_key_hash = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime)
    is_active = Column(Boolean, default=True)
    is_suspended = Column(Boolean, default=False)

class UserQuota(Base):
    __tablename__ = "user_quotas"

    user_id = Column(UUID(as_uuid=True), primary_key=True)
    max_concurrent_jobs = Column(Integer, nullable=False, default=3)
    max_gpu_hours_per_day = Column(Float, nullable=False, default=24.0)
    max_cpu_hours_per_day = Column(Float, nullable=False, default=100.0)
    max_storage_gb = Column(Integer, nullable=False, default=50)
    max_artifact_size_gb = Column(Integer, nullable=False, default=50)
    max_job_timeout_hours = Column(Integer, nullable=False, default=48)
    priority_weight = Column(Integer, nullable=False, default=1)
    can_use_custom_docker = Column(Boolean, default=False)
    can_skip_validation = Column(Boolean, default=False)

class Job(Base):
    __tablename__ = "jobs"

    job_id = Column(String(255), primary_key=True)
    ray_job_id = Column(String(255), unique=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    job_type = Column(String(50), nullable=False)
    language = Column(String(50), nullable=False, default="python")
    status = Column(String(50), nullable=False, default="PENDING")
    priority = Column(String(50), nullable=False, default="normal")

    # Resources
    cpu_requested = Column(Integer, nullable=False)
    memory_gb_requested = Column(Integer, nullable=False)
    gpu_requested = Column(Float, nullable=False, default=0.0)
    timeout_hours = Column(Integer, nullable=False)

    # Usage
    cpu_used_hours = Column(Float)
    gpu_used_hours = Column(Float)
    memory_peak_gb = Column(Float)
    disk_used_gb = Column(Float)

    # Docker
    base_image = Column(String(255))
    dockerfile_hash = Column(String(64))
    custom_dockerfile = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    queued_at = Column(DateTime)
    started_at = Column(DateTime)
    ended_at = Column(DateTime)

    # Output
    output_mode = Column(String(50), default="artifacts")
    artifact_path = Column(Text)
    artifact_size_bytes = Column(BigInteger)
    artifact_retention_days = Column(Integer, default=90)
    artifact_downloaded_at = Column(DateTime)
    mlflow_experiment = Column(String(255))
    mlflow_run_id = Column(String(255))

    # Metadata
    tags = Column(ARRAY(String))
    cost_center = Column(String(255))
    depends_on = Column(ARRAY(String))

    # Error
    error_message = Column(Text)
    error_traceback = Column(Text)
    exit_code = Column(Integer)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)

    # Audit
    cancelled_by = Column(UUID(as_uuid=True))
    cancelled_at = Column(DateTime)
    cancellation_reason = Column(Text)

# Add other models (JobQueue, ArtifactVersion, etc.) as needed
```

### 2.3 File Structure

The complete implementation requires creating these files:

```
ray_compute/
├── api/
│   ├── auth.py                 # OAuth middleware (CREATE THIS)
│   ├── models.py               # Database models (CREATE THIS)
│   ├── database.py             # DB helpers
│   ├── schemas.py              # Pydantic schemas
│   ├── notifications.py        # Apprise integration
│   ├── validators.py           # Job validation (Dockerfile, code safety)
│   ├── scheduler.py            # Fractional GPU scheduler
│   ├── queue.py                # Priority queue manager
│   ├── server_v2.py            # Main API server (enhanced)
│   ├── admin_api.py            # Admin-only endpoints
│   └── metrics.py              # Prometheus metrics
├── cli/
│   ├── ray-compute             # CLI tool
│   └── interactive.py          # Interactive TUI
├── config/
│   ├── database_schema.sql     # ✅ Done
│   ├── prometheus.yml          # ✅ Done
│   ├── loki.yml                # ✅ Done
│   ├── notifications.conf      # ✅ Done
│   └── job_templates/          # YOLO, PyTorch templates
├── docker-compose.auth.yml     # ✅ Done
├── docker-compose.observability.yml  # ✅ Done
├── .env.example                # ✅ Done
└── scripts/
    └── setup_enhanced.sh       # ✅ Done
```

## 📊 Phase 3: Implementation Priority

### HIGH PRIORITY (Do Next):
1. **Create `api/auth.py`** - OAuth middleware
2. **Create `api/models.py`** - Database models
3. **Create `api/server_v2.py`** - Enhanced API server
4. **Create `api/scheduler.py`** - GPU scheduler
5. **Create `api/notifications.py`** - Notification system

### MEDIUM PRIORITY:
6. **Create `api/admin_api.py`** - Admin endpoints
7. **Create `api/validators.py`** - Safety checks
8. **Create `api/queue.py`** - Job queue
9. **Create `cli/ray-compute`** - CLI tool

### LOW PRIORITY:
10. **Documentation** - User/admin guides
11. **Templates** - Job templates
12. **Tests** - Integration tests

## 🎓 Development Workflow

### Step-by-Step Implementation:

1. **Complete Phase 1 Setup** (2 hours)
   - Run `setup_enhanced.sh`
   - Configure Authentik
   - Test infrastructure

2. **Build Core API** (4 hours)
   - Create auth.py
   - Create models.py
   - Test OAuth flow

3. **Enhance Job Management** (4 hours)
   - Create scheduler.py (fractional GPU)
   - Create validators.py (safety)
   - Update job submission

4. **Add Admin Features** (2 hours)
   - Create admin_api.py
   - Add monitoring endpoints
   - Test admin privileges

5. **Implement Notifications** (2 hours)
   - Create notifications.py
   - Test Apprise integration
   - Configure alerts

6. **Build CLI Tool** (2 hours)
   - Create cli/ray-compute
   - Test all operations
   - Add interactive mode

7. **Testing & Documentation** (2 hours)
   - Write user guide
   - Write admin guide
   - Integration tests

## 🧪 Testing Checklist

After each phase, test:

### Authentication:
- [ ] OAuth login works
- [ ] Token validation works
- [ ] Role-based access enforced
- [ ] Admin can access admin APIs
- [ ] Users cannot access admin APIs

### Job Submission:
- [ ] Users can submit jobs
- [ ] Quota enforcement works
- [ ] Job validation rejects unsafe code
- [ ] Fractional GPU allocation works
- [ ] Queue priority correct

### Admin Features:
- [ ] Admin can view all jobs
- [ ] Admin can cancel any job
- [ ] Admin can suspend users
- [ ] Resource monitoring works
- [ ] No timeout limits for admin

### Monitoring:
- [ ] Grafana dashboards show metrics
- [ ] Loki shows logs
- [ ] Prometheus collects GPU metrics
- [ ] Alerts trigger correctly

### Notifications:
- [ ] Job completion notifies user
- [ ] Job failure notifies user
- [ ] System alerts notify admin
- [ ] Rate limiting works

## 📚 Documentation Files to Create

1. **AUTH_SETUP.md** - Authentik configuration guide
2. **ADMIN_GUIDE.md** - Admin operations manual
3. **USER_GUIDE.md** - End-user documentation
4. **API_REFERENCE.md** - Complete API docs
5. **SCHEDULER_GUIDE.md** - GPU scheduling explained
6. **TROUBLESHOOTING_V2.md** - Common issues

## 🚨 Important Notes

### Security:
- Never commit `.env` file
- Rotate Authentik secret key regularly
- Use HTTPS in production (add reverse proxy)
- Enable Authentik MFA for admins

### Performance:
- Database connection pooling (10 connections)
- Redis for queue (not in-memory)
- Artifact compression (zstd level 3)
- Log rotation (7 days retention)

### Monitoring:
- Check Grafana daily for anomalies
- Review audit logs weekly
- Monitor GPU temperature continuously
- Alert on storage >90%

## 🆘 Getting Help

If you encounter issues:

1. **Check logs:**
   ```bash
   docker-compose -f docker-compose.auth.yml logs authentik-server
   docker-compose -f docker-compose.observability.yml logs grafana
   tail -f logs/api_v2.log
   ```

2. **Database issues:**
   ```bash
   psql -h localhost -U ray_compute -d ray_compute
   \dt  # List tables
   \d users  # Describe users table
   ```

3. **Service health:**
   ```bash
   curl http://localhost:9000/-/health
   curl http://localhost:3000/api/health
   ```

## ✅ Success Criteria

You'll know it's working when:

- ✅ Can login via OAuth and get token
- ✅ Can submit job with token authentication
- ✅ Admin can see all jobs, users can see only theirs
- ✅ GPU jobs scheduled with fractional allocation
- ✅ Notifications arrive on phone/Telegram
- ✅ Grafana shows real-time metrics
- ✅ Artifacts auto-compressed and versioned
- ✅ Storage cleanup triggers at 90%

## 🎉 Next Phase

After completing this implementation:

1. **Add Web Dashboard** (React + WebSockets)
2. **Implement Payment System** (Stripe integration)
3. **Multi-Node Support** (Ray cluster expansion)
4. **Advanced Features** (DAG workflows, model serving)

---

**Current Status:** Infrastructure Ready ✅  
**Next Step:** Run `./scripts/setup_enhanced.sh`  
**Estimated Completion:** 20-24 hours from start

Good luck! 🚀
