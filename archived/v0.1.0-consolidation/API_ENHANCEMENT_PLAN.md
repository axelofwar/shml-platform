# PII-PRO MLflow API - Configuration & Implementation Plan

## ✅ Confirmed: Traefik Integration

The API is **properly configured** in docker-compose.yml with Traefik labels:
```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.services.mlflow-api-service.loadbalancer.server.port=8000"
  - "traefik.http.routers.mlflow-api-v1.rule=PathPrefix(`/api/v1`)"
  - "traefik.http.routers.mlflow-api-v1.priority=500"  # High priority
```

**Status**: API routes through Traefik gateway at `/api/v1/*`  
**Note**: Service needs to be built and started first

---

## 🔧 Required Updates

### 1. Schema Enforcement - Environment-Aware ✅

**Current Problem**: Hard blocks on missing required tags/metrics  
**New Behavior**:

#### Development Environment
- **NO enforcement** - all models accepted
- Warnings logged but never blocks
- Goal: Fast iteration

#### Staging Environment  
- **NO enforcement** - all models accepted
- Warnings for missing tags/metrics
- Alerts for low recall (<0.95) but allows upload
- Goal: Testing and validation

#### Production Environment
- **ALERT-ONLY** - never blocks uploads
- Strong warnings for:
  - Missing required tags
  - Recall < 0.95
  - False negative rate > 0.05
- Recommendations shown in UI
- Goal: Awareness without blocking

**Implementation**:
```python
ENVIRONMENT = os.getenv('MLFLOW_ENVIRONMENT', 'development')

def validate_run(experiment, tags, metrics, environment):
    warnings = []
    
    # Check required fields
    if missing_tags:
        if environment == 'production':
            warnings.append(f"[PRODUCTION ALERT] Missing: {missing_tags}")
        else:
            warnings.append(f"[{environment}] Missing: {missing_tags} (allowed)")
    
    # Check metrics - ALWAYS alert only, never block
    if metrics.get('recall', 1.0) < 0.95:
        warnings.append(
            f"[{environment} ALERT] Recall below 0.95. "
            f"Consider retraining before production."
        )
    
    # Always return True - never block
    return True, warnings
```

---

### 2. Authentication - Authentik OAuth + API Keys ✅

**Authentik is already deployed**:
- URL: http://localhost:9000
- Credentials: akadmin / AiSolutions2350!
- Client ID: `mlflow-api` (needs to be created in Authentik)

**Implementation Plan**:

#### Phase 1: API Keys (Immediate)
```python
API_KEYS = {
    'admin-key-xxx': {'user': 'admin', 'tier': 'admin'},
    'premium-key-yyy': {'user': 'user1', 'tier': 'premium'},
    'regular-key-zzz': {'user': 'user2', 'tier': 'regular'},
}

async def get_current_user(api_key: str = Header(None, alias="X-API-Key")):
    if not api_key or api_key not in API_KEYS:
        raise HTTPException(401, "Invalid API key")
    return API_KEYS[api_key]
```

#### Phase 2: Authentik OAuth (Migration)
```python
from authlib.integrations.starlette_client import OAuth

oauth = OAuth()
oauth.register(
    name='authentik',
    client_id='mlflow-api',
    client_secret=os.getenv('AUTHENTIK_CLIENT_SECRET'),
    server_metadata_url='http://authentik-server:9000/application/o/mlflow-api/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid profile email groups'}
)

@app.get("/api/v1/auth/login")
async def login(request: Request):
    redirect_uri = request.url_for('auth_callback')
    return await oauth.authentik.authorize_redirect(request, redirect_uri)
```

**Authentik Setup Steps**:
1. Create OAuth2/OpenID provider in Authentik
2. Create application: `mlflow-api`
3. Set redirect URI: `http://localhost/api/v1/auth/callback`
4. Create groups: `mlflow-admin`, `mlflow-premium`, `mlflow-users`
5. Map groups to tiers

---

### 3. Rate Limiting by User Tier ✅

**Limits**:
- Regular: 10 requests/min
- Premium: 50 requests/min
- Admin: Unlimited

**Endpoint-Specific Limits**:
- Model upload: Max 5GB per file
- Artifact storage: 100GB per regular user, 1TB per premium
- Concurrent uploads: 5 per regular user, 20 per premium

**Implementation**:
```python
from collections import defaultdict
import time

rate_limit_store: Dict[str, List[float]] = defaultdict(list)

async def check_rate_limit(user_id: str, tier: str, endpoint: str):
    limits = {
        'admin': None,  # Unlimited
        'premium': 50,
        'regular': 10
    }
    
    limit = limits.get(tier, 10)
    if limit is None:
        return  # Admin unlimited
    
    now = time.time()
    user_key = f"{user_id}:{endpoint}"
    
    # Remove old requests (>60s)
    rate_limit_store[user_key] = [
        t for t in rate_limit_store[user_key]
        if now - t < 60
    ]
    
    if len(rate_limit_store[user_key]) >= limit:
        raise HTTPException(
            429,
            f"Rate limit exceeded. Tier '{tier}' allows {limit} req/min."
        )
    
    rate_limit_store[user_key].append(now)

# Usage in endpoints
@app.post("/api/v1/runs/create")
async def create_run(request, user: User = Depends(get_current_user)):
    await check_rate_limit(user['user'], user['tier'], 'create_run')
    # ... rest of endpoint
```

---

### 4. Prometheus Metrics & Grafana Integration ✅

**Metrics to Expose**:
```python
from prometheus_client import Counter, Histogram, Gauge, generate_latest

# Request metrics
REQUEST_COUNT = Counter('mlflow_api_requests_total', 'Total requests', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Histogram('mlflow_api_request_duration_seconds', 'Latency', ['endpoint'])
ACTIVE_REQUESTS = Gauge('mlflow_api_active_requests', 'Active requests')

# Upload/download metrics
UPLOAD_SIZE = Histogram('mlflow_api_upload_bytes', 'Upload size')
DOWNLOAD_SIZE = Histogram('mlflow_api_download_bytes', 'Download size')

# Rate limiting
RATE_LIMIT_HITS = Counter('mlflow_api_rate_limit_hits', 'Rate limit hits', ['tier'])

# Authentication
AUTH_FAILURES = Counter('mlflow_api_auth_failures', 'Auth failures', ['method'])

@app.get("/api/v1/metrics")
async def metrics(user: User = Depends(get_current_user)):
    if user['tier'] != 'admin':
        raise HTTPException(403, "Admin only")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

**Grafana Dashboards**:

Admin Dashboard (full access):
- All users' activity
- System-wide metrics
- Storage usage by user
- Rate limit violations
- Authentication failures

User Dashboard (project-specific):
- Only their experiments/runs
- Their model performance
- Their storage usage
- Their API usage

**Prometheus Config**:
```yaml
scrape_configs:
  - job_name: 'mlflow-api'
    static_configs:
      - targets: ['mlflow-api:8000']
    metrics_path: '/api/v1/metrics'
```

---

### 5. Auto-Archival System ✅

**Rules**:
- Runs older than 12 months → Archive
- Runs never promoted to Production for 6 months → Archive
- Always retrievable from archive

**Implementation**:

#### Archive Endpoint
```python
@app.get("/api/v1/runs/archived")
async def list_archived_runs(
    experiment_id: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """List archived runs"""
    # Query runs with lifecycle_stage='deleted' or custom 'archived' tag
    archived = client.search_runs(
        experiment_ids=[experiment_id] if experiment_id else None,
        filter_string="tags.archived='true'"
    )
    return {"archived_runs": archived}

@app.post("/api/v1/runs/{run_id}/archive")
async def archive_run(run_id: str, user: User = Depends(get_current_user)):
    """Manually archive a run"""
    client.set_tag(run_id, "archived", "true")
    client.set_tag(run_id, "archived_at", datetime.utcnow().isoformat())
    client.set_tag(run_id, "archived_by", user['user'])
    return {"run_id": run_id, "status": "archived"}

@app.post("/api/v1/runs/{run_id}/unarchive")
async def unarchive_run(run_id: str, user: User = Depends(get_current_user)):
    """Restore run from archive"""
    client.delete_tag(run_id, "archived")
    return {"run_id": run_id, "status": "active"}
```

#### Automated Archival (Background Task)
```python
from apscheduler.schedulers.background import BackgroundScheduler

def auto_archive_old_runs():
    """Run daily to archive old runs"""
    now = datetime.utcnow()
    twelve_months_ago = now - timedelta(days=365)
    six_months_ago = now - timedelta(days=180)
    
    # Find old runs
    experiments = client.search_experiments()
    for exp in experiments:
        runs = client.search_runs([exp.experiment_id])
        
        for run in runs:
            start_time = datetime.fromtimestamp(run.info.start_time / 1000)
            
            # Archive if older than 12 months
            if start_time < twelve_months_ago:
                client.set_tag(run.info.run_id, "archived", "true")
                client.set_tag(run.info.run_id, "archive_reason", "age_12_months")
                continue
            
            # Archive if not promoted for 6 months
            if start_time < six_months_ago:
                # Check if model was registered
                model_uri = f"runs:/{run.info.run_id}/model"
                try:
                    # Check Model Registry
                    versions = client.search_model_versions(f"run_id='{run.info.run_id}'")
                    if not versions:  # Never registered
                        client.set_tag(run.info.run_id, "archived", "true")
                        client.set_tag(run.info.run_id, "archive_reason", "not_promoted_6_months")
                except:
                    pass

scheduler = BackgroundScheduler()
scheduler.add_job(auto_archive_old_runs, 'cron', hour=2, minute=0)  # Daily at 2 AM
scheduler.start()
```

---

### 6. Async Operations & Optimization ✅

**Features**:
- Async upload/download
- Server-side compression
- Streaming responses
- Background tasks

**Implementation**:

#### Async Upload
```python
import aiofiles
import gzip

@app.post("/api/v1/runs/{run_id}/artifacts/async")
async def upload_artifact_async(
    run_id: str,
    file: UploadFile,
    compress: bool = Form(default=True),
    background_tasks: BackgroundTasks = None
):
    """Async upload with server-side compression"""
    
    # Read file asynchronously
    content = await file.read()
    original_size = len(content)
    
    # Server-side compression
    if compress and not file.filename.endswith(('.gz', '.zip')):
        content = gzip.compress(content, compresslevel=6)
        filename = f"{file.filename}.gz"
    else:
        filename = file.filename
    
    # Save temp file
    async with aiofiles.open(f"/tmp/{filename}", 'wb') as f:
        await f.write(content)
    
    # Upload in background
    def upload_task():
        client.log_artifact(run_id, f"/tmp/{filename}")
        os.unlink(f"/tmp/{filename}")
    
    background_tasks.add_task(upload_task)
    
    return {
        "status": "uploading",
        "original_size": original_size,
        "compressed_size": len(content),
        "compression_ratio": f"{(1-len(content)/original_size)*100:.1f}%"
    }
```

#### Streaming Download
```python
@app.get("/api/v1/runs/{run_id}/artifacts/{path:path}/stream")
async def download_artifact_stream(run_id: str, path: str):
    """Stream large artifacts"""
    local_path = client.download_artifacts(run_id, path)
    
    async def file_iterator():
        async with aiofiles.open(local_path, 'rb') as f:
            while chunk := await f.read(8192):  # 8KB chunks
                yield chunk
    
    return StreamingResponse(
        file_iterator(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={os.path.basename(path)}"}
    )
```

---

## 📦 Updated Dependencies

Add to `requirements.txt`:
```txt
# Existing
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
mlflow==2.9.2
pyyaml==6.0.1
python-multipart==0.0.6

# New
authlib==1.2.1              # OAuth
itsdangerous==2.1.2         # Session management
aiofiles==23.2.1            # Async file I/O
prometheus-client==0.19.0   # Metrics
apscheduler==3.10.4         # Background jobs
redis==5.0.1                # Rate limiting (optional, better than in-memory)
```

---

## 🚀 Deployment Steps

### 1. Update Environment Variables

Add to `docker-compose.yml` for `mlflow-api`:
```yaml
environment:
  MLFLOW_TRACKING_URI: http://mlflow-server:5000
  MLFLOW_ENVIRONMENT: ${MLFLOW_ENVIRONMENT:-development}  # development|staging|production
  
  # Authentik OAuth
  AUTHENTIK_URL: http://authentik-server:9000
  AUTHENTIK_CLIENT_ID: mlflow-api
  AUTHENTIK_CLIENT_SECRET: ${AUTHENTIK_CLIENT_SECRET}
  SESSION_SECRET_KEY: ${SESSION_SECRET_KEY}
  
  # API Keys (temporary)
  ADMIN_API_KEY: ${ADMIN_API_KEY}
  PREMIUM_API_KEY: ${PREMIUM_API_KEY}
  
  # Rate limiting
  REDIS_URL: redis://ml-platform-redis:6379/2  # DB 2 for API
```

### 2. Configure Authentik

```bash
# Access Authentik
open http://localhost:9000

# Login as akadmin / AiSolutions2350!

# Create Provider:
#   Type: OAuth2/OpenID
#   Name: mlflow-api
#   Client ID: mlflow-api
#   Redirect URIs: http://localhost/api/v1/auth/callback
#   Scopes: openid, profile, email, groups

# Create Application:
#   Name: MLflow API
#   Slug: mlflow-api
#   Provider: mlflow-api

# Create Groups:
#   mlflow-admin
#   mlflow-premium
#   mlflow-users

# Assign users to groups
```

### 3. Update Prometheus

Add to `mlflow-server/docker/prometheus/prometheus.yml`:
```yaml
scrape_configs:
  - job_name: 'mlflow-api'
    static_configs:
      - targets: ['mlflow-api:8000']
    metrics_path: '/api/v1/metrics'
    scrape_interval: 15s
```

### 4. Build and Deploy

```bash
cd /home/axelofwar/Desktop/Projects
./stop_all.sh
./start_all.sh
```

---

## ❓ Questions - ANSWERED

### 1. Schema Enforcement
**Q**: Block models below threshold?  
**A**: ✅ NO - Alert-only in all environments. Never blocks uploads/downloads.

### 2. Authentication
**Q**: Use Authentik OAuth?  
**A**: ✅ YES - Authentik already deployed. Phase 1: API keys, Phase 2: OAuth migration.

### 3. Rate Limiting
**Q**: Limits per tier?  
**A**: ✅ YES - Regular: 10/min, Premium: 50/min, Admin: unlimited. Storage limits enforced.

### 4. Prometheus/Grafana
**Q**: Integrate metrics?  
**A**: ✅ YES - `/api/v1/metrics` endpoint. Admin sees all, users see only their projects.

### 5. Auto-Archival
**Q**: Archive old runs?  
**A**: ✅ YES - 12-month age limit, 6-month non-production limit. Separate `/archived` endpoint. Always retrievable.

### 6. Async Operations
**Q**: Optimize downloads/uploads?  
**A**: ✅ YES - Async upload/download, server-side compression, streaming, background tasks.

---

## 📝 Next Steps

1. **Update main.py** with all enhancements
2. **Update Dockerfile** with new dependencies
3. **Configure Authentik** OAuth provider
4. **Update docker-compose.yml** with environment variables
5. **Create Grafana dashboards** (admin + user)
6. **Test deployment** with all features
7. **Document API** with new endpoints

Ready to implement? Let me know which component to start with!
