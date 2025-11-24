# MLflow Best Practices Implementation Guide

## Overview

This guide documents MLflow best practices from official documentation and implementation recommendations for our ML platform.

## Architecture Review

### Current Implementation ✅

1. **Backend Store**: PostgreSQL
   - ✅ Using database backend (recommended over file-based)
   - ✅ Connection via `--backend-store-uri`
   - ✅ Dedicated PostgreSQL 15 container

2. **Artifact Storage**: Filesystem
   - ✅ Centralized `/mlflow/artifacts` directory
   - ✅ Using `--artifacts-destination` for proxied access
   - ✅ Separate volume for persistence

3. **Tracking Server**: Gunicorn/Uvicorn
   - ✅ Running as service with proper configuration
   - ✅ Health checks implemented
   - ✅ Resource limits defined

4. **API Gateway**: Traefik
   - ✅ Reverse proxy setup
   - ✅ Path-based routing
   - ✅ Service discovery

### Recommended Improvements

## 1. Security Middleware (MLflow 3.5.0+)

### Current Status: NOT IMPLEMENTED

MLflow 3.5.0+ includes built-in security middleware for:
- DNS Rebinding Protection
- CORS Protection  
- Clickjacking Prevention

### Implementation

Update MLflow server startup command in `mlflow-server/docker/mlflow/Dockerfile` or entrypoint:

```bash
mlflow server \
  --host 0.0.0.0 \
  --port 5000 \
  --backend-store-uri ${MLFLOW_BACKEND_STORE_URI} \
  --artifacts-destination ${MLFLOW_ARTIFACT_ROOT} \
  --allowed-hosts "localhost,mlflow-server,mlflow-nginx,*.ml-platform" \
  --cors-allowed-origins "http://localhost,https://localhost" \
  --gunicorn-opts "--timeout=3600 --workers=${MLFLOW_WORKERS:-8}"
```

### Environment Variables to Add

```yaml
# docker-compose.yml - mlflow-server service
environment:
  # Existing...
  MLFLOW_ALLOWED_HOSTS: "localhost,mlflow-server,mlflow-nginx,*.ml-platform"
  MLFLOW_CORS_ALLOWED_ORIGINS: "http://localhost,https://localhost"
```

## 2. Timeout Configuration

### Current Status: PARTIALLY IMPLEMENTED

We have `--worker-timeout=3600` for large artifacts, but should add keep-alive timeout.

### Implementation

Add to MLflow server startup:

```bash
--uvicorn-opts "--timeout-keep-alive=120"
```

Or for gunicorn users:

```bash
--gunicorn-opts "--timeout=3600 --keep-alive=120 --workers=${MLFLOW_WORKERS:-8}"
```

## 3. Model Version Source Validation

### Current Status: NOT IMPLEMENTED

Security feature to ensure only approved artifact sources.

### Implementation

Add to docker-compose.yml environment:

```yaml
mlflow-server:
  environment:
    # Restrict model versions to MLflow artifacts only
    MLFLOW_CREATE_MODEL_VERSION_SOURCE_VALIDATION_REGEX: "^mlflow-artifacts:/.*$"
    
    # Or restrict to specific storage locations:
    # MLFLOW_CREATE_MODEL_VERSION_SOURCE_VALIDATION_REGEX: "^(mlflow-artifacts:/|s3://production-models)/.*$"
```

This prevents users from registering models from untrusted sources.

## 4. Artifact Proxy Optimization

### Current Status: PROXIED (GOOD)

We're using `--artifacts-destination` which proxies artifacts through the tracking server.

### Benefits ✅
- Centralized access control
- No need for clients to have direct storage credentials
- Audit trail of artifact access

### Consideration: Artifacts-Only Server

For **high-volume** deployments (not needed now), consider:

```yaml
# Separate artifact server
mlflow-artifacts-server:
  # ... same build as mlflow-server
  command: |
    mlflow server \
      --artifacts-only \
      --host 0.0.0.0 \
      --port 5001 \
      --artifacts-destination ${MLFLOW_ARTIFACT_ROOT}
  ports:
    - "5001:5001"

# Main tracking server (no artifacts)
mlflow-server:
  command: |
    mlflow server \
      --no-serve-artifacts \
      --host 0.0.0.0 \
      --port 5000 \
      --backend-store-uri ${MLFLOW_BACKEND_STORE_URI} \
      --default-artifact-root mlflow-artifacts://mlflow-artifacts-server:5001/mlartifacts
```

**When to use**: When artifact operations are impacting metadata API performance.

## 5. Official MLflow Docker Image

### Current Status: CUSTOM IMAGE

We're using custom image with additional tools.

### Consideration

Official image available at: `ghcr.io/mlflow/mlflow:v2.9.2`

**Pros of official image**:
- Maintained by MLflow team
- Security updates
- Tested configurations

**Pros of our custom image**:
- Additional diagnostic tools
- Schema validation plugins
- Custom entrypoint scripts

**Recommendation**: Keep custom image but consider multi-stage build:

```dockerfile
# Use official as base
FROM ghcr.io/mlflow/mlflow:v2.9.2 as base

# Add our customizations
FROM base
# Install additional tools...
```

## 6. Database Performance Tuning

### Current Status: BASIC CONFIGURATION

### PostgreSQL Optimizations

Update PostgreSQL configuration in docker-compose.yml:

```yaml
mlflow-postgres:
  environment:
    # Existing...
    # Performance tuning
    POSTGRES_INITDB_ARGS: "-E UTF8 --locale=C"
    # Add shared memory
  shm_size: '256mb'
  command:
    - "postgres"
    - "-c"
    - "shared_buffers=256MB"
    - "-c"
    - "effective_cache_size=1GB"
    - "-c"
    - "maintenance_work_mem=128MB"
    - "-c"
    - "checkpoint_completion_target=0.9"
    - "-c"
    - "wal_buffers=16MB"
    - "-c"
    - "default_statistics_target=100"
    - "-c"
    - "random_page_cost=1.1"
    - "-c"
    - "effective_io_concurrency=200"
    - "-c"
    - "work_mem=16MB"
    - "-c"
    - "min_wal_size=1GB"
    - "-c"
    - "max_wal_size=4GB"
    - "-c"
    - "max_connections=200"
```

### Connection Pooling

Consider adding PgBouncer for connection pooling:

```yaml
mlflow-pgbouncer:
  image: pgbouncer/pgbouncer:latest
  environment:
    DATABASES: "mlflow_db=host=mlflow-postgres port=5432 dbname=mlflow_db"
    POOL_MODE: session
    MAX_CLIENT_CONN: 1000
    DEFAULT_POOL_SIZE: 20
  depends_on:
    - mlflow-postgres
```

## 7. Worker Configuration

### Current Status: FIXED WORKERS=8

### Dynamic Worker Scaling

Update entrypoint script to calculate workers based on CPU:

```bash
#!/bin/bash
# Calculate optimal worker count: (2 × CPU cores) + 1
WORKERS=${MLFLOW_WORKERS:-$(python -c "import os; print((os.cpu_count() * 2) + 1)")}

mlflow server \
  --host 0.0.0.0 \
  --port 5000 \
  --backend-store-uri ${MLFLOW_BACKEND_STORE_URI} \
  --artifacts-destination ${MLFLOW_ARTIFACT_ROOT} \
  --gunicorn-opts "--workers=${WORKERS} --timeout=3600"
```

## 8. Artifact Compression

### Current Status: CONFIGURED

Already implemented in docker-compose.yml:

```yaml
MLFLOW_AUTO_COMPRESS: "true"
MLFLOW_COMPRESSION_THRESHOLD_MB: 10
MLFLOW_COMPRESSION_FORMAT: zstd
```

✅ This is good! ZSTD provides excellent compression ratios with fast decompression.

## 9. Monitoring & Metrics

### Current Status: PROMETHEUS CONFIGURED

Already implemented:
- Prometheus scraping MLflow metrics
- Grafana dashboards

### Additional Metrics to Monitor

Add custom metrics in MLflow API wrapper:

```python
from prometheus_client import Counter, Histogram, Gauge

# Track artifact operations
artifact_operations = Counter(
    'mlflow_artifact_operations_total',
    'Total artifact operations',
    ['operation', 'status']
)

# Track API latency
api_latency = Histogram(
    'mlflow_api_latency_seconds',
    'API request latency',
    ['endpoint', 'method']
)

# Track active experiments
active_experiments = Gauge(
    'mlflow_active_experiments',
    'Number of active experiments'
)
```

## 10. Backup Strategy

### Current Status: AUTOMATED BACKUPS

Already implemented:
- Daily PostgreSQL backups
- Artifact backup service
- 90-day retention

### Enhancements

1. **Test restores regularly**:
   ```bash
   # Monthly restore test
   ./scripts/test_backup_restore.sh
   ```

2. **Off-site backups**:
   ```yaml
   mlflow-backup:
     environment:
       # Add S3 sync for off-site backup
       BACKUP_S3_BUCKET: "s3://mlflow-backups-offsite"
       AWS_ACCESS_KEY_ID: ${BACKUP_AWS_KEY}
       AWS_SECRET_ACCESS_KEY: ${BACKUP_AWS_SECRET}
   ```

3. **Point-in-time recovery** for PostgreSQL:
   ```yaml
   mlflow-postgres:
     command:
       - "postgres"
       - "-c"
       - "wal_level=replica"
       - "-c"
       - "archive_mode=on"
       - "-c"
       - "archive_command='test ! -f /backups/wal/%f && cp %p /backups/wal/%f'"
   ```

## 11. TLS/HTTPS Configuration

### Current Status: HTTP ONLY

### Implementation via Traefik

Already have Traefik configured, add TLS:

```yaml
traefik:
  command:
    # Existing commands...
    - "--entrypoints.websecure.address=:443"
    - "--certificatesresolvers.letsencrypt.acme.email=admin@example.com"
    - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
    - "--certificatesresolvers.letsencrypt.acme.tlschallenge=true"
  volumes:
    # Existing volumes...
    - ./traefik/letsencrypt:/letsencrypt
  labels:
    # Redirect HTTP to HTTPS
    - "traefik.http.middlewares.https-redirect.redirectscheme.scheme=https"
    - "traefik.http.middlewares.https-redirect.redirectscheme.permanent=true"
```

Update MLflow labels:

```yaml
mlflow-nginx:
  labels:
    - "traefik.http.routers.mlflow-ui.tls=true"
    - "traefik.http.routers.mlflow-ui.tls.certresolver=letsencrypt"
```

## 12. Access Control & Authentication

### Current Status: AUTHENTIK OAUTH (CONFIGURED)

Already implemented:
- Authentik OAuth provider
- Client credentials for MLflow
- OAuth integration in APIs

### Enhancements

1. **Role-Based Access Control (RBAC)**:
   - Configure Authentik groups (admin, user, viewer)
   - Map to MLflow permissions

2. **API Key Management**:
   - Generate service account keys
   - Rotate keys regularly
   - Audit key usage

## Implementation Priority

### Phase 1: Critical (Implement This Week)

1. ✅ Resource Manager - COMPLETED
2. ✅ Package Manager (uv) - COMPLETED  
3. 🔄 Security Middleware (--allowed-hosts, CORS)
4. 🔄 Timeout Configuration (keep-alive)
5. 🔄 Model Version Source Validation

### Phase 2: Important (Next 2 Weeks)

1. Database Performance Tuning
2. Dynamic Worker Scaling
3. Enhanced Monitoring Metrics
4. Backup Testing Procedures
5. TLS/HTTPS Configuration

### Phase 3: Optimization (Next Month)

1. Connection Pooling (PgBouncer)
2. Artifacts-Only Server (if needed)
3. Point-in-Time Recovery
4. Advanced RBAC
5. Off-Site Backups

## Configuration Files to Update

### 1. MLflow Server Entrypoint

File: `mlflow-server/docker/mlflow/entrypoint.sh`

```bash
#!/bin/bash
set -e

# Wait for PostgreSQL
echo "Waiting for PostgreSQL..."
while ! nc -z mlflow-postgres 5432; do
  sleep 1
done
echo "PostgreSQL ready!"

# Calculate workers
WORKERS=${MLFLOW_WORKERS:-$(python -c "import os; print(min((os.cpu_count() * 2) + 1, 16))")}

# Start MLflow server with all best practices
exec mlflow server \
  --host 0.0.0.0 \
  --port 5000 \
  --backend-store-uri "${MLFLOW_BACKEND_STORE_URI}" \
  --artifacts-destination "${MLFLOW_ARTIFACT_ROOT}" \
  --allowed-hosts "localhost,mlflow-server,mlflow-nginx,*.ml-platform" \
  --cors-allowed-origins "${MLFLOW_CORS_ALLOWED_ORIGINS:-http://localhost,https://localhost}" \
  --gunicorn-opts "--bind=0.0.0.0:5000 --workers=${WORKERS} --timeout=3600 --keep-alive=120 --worker-class=sync --worker-connections=1000" \
  --serve-artifacts
```

### 2. Docker Compose Environment

File: `docker-compose.yml` (mlflow-server section)

```yaml
mlflow-server:
  environment:
    # Existing...
    
    # Security (Phase 1)
    MLFLOW_ALLOWED_HOSTS: "localhost,mlflow-server,mlflow-nginx,*.ml-platform"
    MLFLOW_CORS_ALLOWED_ORIGINS: "http://localhost,https://localhost"
    
    # Model version validation (Phase 1)
    MLFLOW_CREATE_MODEL_VERSION_SOURCE_VALIDATION_REGEX: "^mlflow-artifacts:/.*$"
    
    # Worker configuration (Phase 2)
    MLFLOW_WORKERS: "8"  # Will be overridden by dynamic calculation
    
    # Performance tuning (Phase 2)
    MLFLOW_ENABLE_PROXY_ARTIFACT_ACCESS: "true"
```

### 3. PostgreSQL Configuration

File: `docker-compose.yml` (mlflow-postgres section)

```yaml
mlflow-postgres:
  image: postgres:15-alpine
  shm_size: '256mb'
  environment:
    POSTGRES_DB: mlflow_db
    POSTGRES_USER: mlflow
    POSTGRES_PASSWORD_FILE: /run/secrets/mlflow_db_password
    POSTGRES_INITDB_ARGS: "-E UTF8 --locale=C"
  command:
    - "postgres"
    - "-c"
    - "shared_buffers=256MB"
    - "-c"
    - "effective_cache_size=1GB"
    - "-c"
    - "max_connections=200"
    - "-c"
    - "work_mem=16MB"
```

## Testing Checklist

After implementing changes:

```bash
# 1. Test server startup
docker-compose up -d mlflow-server
docker-compose logs -f mlflow-server

# 2. Test API endpoints
curl http://localhost:5000/health
curl http://localhost:5000/version

# 3. Test artifact operations
python -c "
import mlflow
mlflow.set_tracking_uri('http://localhost:5000')
with mlflow.start_run():
    mlflow.log_param('test', 1)
    mlflow.log_artifact('test.txt')
"

# 4. Test security headers
curl -I http://localhost:5000/

# 5. Check worker count
docker exec mlflow-server ps aux | grep mlflow

# 6. Monitor performance
docker stats mlflow-server --no-stream
```

## Documentation Updates Needed

1. Update `README.md` with new security features
2. Update `API_REFERENCE.md` with validation rules
3. Update `TROUBLESHOOTING.md` with new configurations
4. Create `SECURITY.md` with security best practices

## Questions for User

Before implementing Phase 1 changes:

1. **External Access**: Will MLflow be accessed from outside the host machine?
   - If yes, what domain name? (for --allowed-hosts)
   - Need to configure firewall/DNS?

2. **Model Source Validation**: Should we restrict model sources?
   - Only MLflow artifacts?
   - Allow specific S3 buckets?
   - No restrictions?

3. **HTTPS/TLS**: Do you have a domain name for Let's Encrypt?
   - Or should we use self-signed certificates?
   - Or HTTP-only for internal use?

4. **Backup Strategy**: Where should off-site backups go?
   - S3-compatible storage?
   - Network mount?
   - No off-site backups?

5. **Authentication**: Current OAuth setup sufficient?
   - Need API keys for programmatic access?
   - Need different permission levels?

## Next Steps

1. Review this guide
2. Answer questions above
3. Approve Phase 1 implementations
4. Test changes in development
5. Roll out to production

## References

- MLflow Tracking Server Docs: https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/
- MLflow Docker Docs: https://mlflow.org/docs/latest/ml/docker/
- MLflow Security: https://mlflow.org/docs/latest/self-hosting/security/network/
- PostgreSQL Performance Tuning: https://pgtune.leopard.in.ua/
