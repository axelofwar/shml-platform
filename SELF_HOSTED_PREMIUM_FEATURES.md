# Self-Hosted Premium Features (Supabase-Like)

**Last Updated:** November 24, 2025  
**Purpose:** Implement Supabase premium features while maintaining complete self-hosting and privacy  
**Related:** [MONETIZATION_STRATEGY.md](../pii-pro/docs/MONETIZATION_STRATEGY.md)

---

## 🎯 Overview

This guide shows how to add Supabase-like premium features to SFML Platform using **self-hosted open-source alternatives**. All features maintain our privacy-first commitment.

---

## 🏗️ Feature Comparison Matrix

| Supabase Feature     | Self-Hosted Alternative              | Implementation               | Privacy Level |
| -------------------- | ------------------------------------ | ---------------------------- | ------------- |
| **Authentication**   | Authentik (✅ deployed)              | OAuth 2.0, OIDC, SAML        | 100% private  |
| **Database**         | PostgreSQL (✅ deployed)             | Direct access, pgAdmin       | 100% private  |
| **Real-time**        | PostgREST + pg_notify                | WebSocket + triggers         | 100% private  |
| **Storage**          | MinIO                                | S3-compatible object storage | 100% private  |
| **Edge Functions**   | OpenFaaS / Fission                   | Serverless on your hardware  | 100% private  |
| **Auto APIs**        | PostgREST                            | REST API from PostgreSQL     | 100% private  |
| **Vector Search**    | pgvector                             | PostgreSQL extension         | 100% private  |
| **Full-Text Search** | PostgreSQL FTS + Meilisearch         | Native + fast search engine  | 100% private  |
| **Analytics**        | Grafana + Prometheus (✅ deployed)   | Metrics, dashboards          | 100% private  |
| **CDN**              | Caddy + CloudFlare Tunnel (optional) | Caching, HTTPS               | Controllable  |

**Key Advantage**: No vendor lock-in, no data leaves your infrastructure

---

## 1️⃣ Real-Time Updates (PostgREST + pg_notify)

### What We're Replicating

Supabase Real-time: Subscribe to database changes via WebSocket

### Self-Hosted Solution: PostgREST + PostgreSQL Triggers

#### Architecture

```
PostgreSQL (database changes)
    ↓ triggers
pg_notify (pub/sub)
    ↓ listen
PostgREST (websocket server)
    ↓ push
Client (browser/app)
```

#### Implementation

**1. Install PostgREST**

```bash
# Add to sfml-platform docker-compose.yml
services:
  postgrest:
    image: postgrest/postgrest:latest
    environment:
      PGRST_DB_URI: postgres://mlflow:${DB_PASSWORD}@postgres:5432/mlflow
      PGRST_DB_SCHEMA: public
      PGRST_DB_ANON_ROLE: web_anon
      PGRST_JWT_SECRET: ${JWT_SECRET}
      PGRST_DB_CHANNEL_ENABLED: true
    ports:
      - "3000:3000"
    networks:
      - ml-platform
    labels:
      - traefik.enable=true
      - traefik.http.routers.postgrest.rule=PathPrefix(`/api/db`)
      - traefik.http.routers.postgrest.priority=2147483647
```

**2. Create PostgreSQL Trigger for Real-Time**

```sql
-- Enable pg_notify
CREATE OR REPLACE FUNCTION notify_job_changes()
RETURNS TRIGGER AS $$
BEGIN
  PERFORM pg_notify(
    'job_updates',
    json_build_object(
      'table', TG_TABLE_NAME,
      'action', TG_OP,
      'data', row_to_json(NEW)
    )::text
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger on ray_jobs table
CREATE TRIGGER job_updates_trigger
AFTER INSERT OR UPDATE OR DELETE ON ray_jobs
FOR EACH ROW EXECUTE FUNCTION notify_job_changes();
```

**3. Client-Side Subscription (JavaScript)**

```javascript
// Subscribe to real-time job updates
const ws = new WebSocket(
  "ws://localhost:3000/rpc/pg_notify?channel=job_updates"
);

ws.onmessage = (event) => {
  const update = JSON.parse(event.data);
  console.log("Job updated:", update.data);
  // Update UI
  updateJobStatus(update.data);
};

ws.onerror = (error) => {
  console.error("WebSocket error:", error);
};
```

**4. Python Client Example**

```python
import asyncio
import websockets
import json

async def subscribe_job_updates():
    uri = "ws://localhost:3000/rpc/pg_notify?channel=job_updates"
    async with websockets.connect(uri) as websocket:
        async for message in websocket:
            update = json.loads(message)
            print(f"Job update: {update['data']}")
            # Handle update
            handle_job_status_change(update['data'])

# Run subscription
asyncio.run(subscribe_job_updates())
```

**Privacy**: All data stays on your server, WebSocket traffic encrypted with TLS

---

## 2️⃣ Object Storage (MinIO)

### What We're Replicating

Supabase Storage: S3-compatible file storage with authentication

### Self-Hosted Solution: MinIO

#### Implementation

**1. Add MinIO to docker-compose.yml**

```yaml
services:
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    volumes:
      - minio_data:/data
    ports:
      - "9000:9000" # API
      - "9001:9001" # Console
    networks:
      - ml-platform
    labels:
      - traefik.enable=true
      - traefik.http.routers.minio-api.rule=PathPrefix(`/storage`)
      - traefik.http.routers.minio-console.rule=PathPrefix(`/storage-console`)

volumes:
  minio_data:
```

**2. Create Buckets & Policies**

```python
from minio import Minio
from minio.error import S3Error

client = Minio(
    "localhost:9000",
    access_key="admin",
    secret_key="password123",
    secure=False
)

# Create buckets
buckets = ['models', 'datasets', 'training-logs', 'user-uploads']
for bucket in buckets:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        print(f"Created bucket: {bucket}")

# Set public policy for models (read-only)
policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"AWS": "*"},
            "Action": ["s3:GetObject"],
            "Resource": ["arn:aws:s3:::models/*"]
        }
    ]
}
client.set_bucket_policy('models', json.dumps(policy))
```

**3. Upload Models from Training**

```python
from minio import Minio
import os

def upload_model_to_storage(model_path: str, model_name: str):
    """Upload trained model to MinIO."""
    client = Minio(
        os.getenv('MINIO_ENDPOINT', 'localhost:9000'),
        access_key=os.getenv('MINIO_ACCESS_KEY'),
        secret_key=os.getenv('MINIO_SECRET_KEY'),
        secure=False
    )

    # Upload model
    client.fput_object(
        bucket_name='models',
        object_name=f'{model_name}/best.pt',
        file_path=model_path,
        metadata={'model_name': model_name, 'framework': 'yolo'}
    )

    # Generate presigned URL (expires in 7 days)
    url = client.presigned_get_object('models', f'{model_name}/best.pt', expires=7*86400)
    return url

# Usage in training script
model_url = upload_model_to_storage('runs/train/v5/weights/best.pt', 'face_detector_v5')
print(f"Model available at: {model_url}")
```

**4. Integration with MLflow**

```python
import mlflow

# Log model artifact to MinIO
with mlflow.start_run():
    mlflow.log_artifact('best.pt', 'model')

    # Add MinIO URL as tag
    mlflow.set_tag('storage_url', model_url)
```

**Privacy**: All files stored on your hardware, no external CDN

---

## 3️⃣ Auto-Generated REST APIs (PostgREST)

### What We're Replicating

Supabase Auto APIs: Instant REST API from database schema

### Self-Hosted Solution: PostgREST (already added in Real-Time section)

#### Usage Examples

**1. CRUD Operations (No Code!)**

```bash
# Get all jobs
curl http://localhost:3000/ray_jobs

# Get specific job
curl http://localhost:3000/ray_jobs?job_id=eq.job-123

# Create job
curl -X POST http://localhost:3000/ray_jobs \
  -H "Content-Type: application/json" \
  -d '{"job_id": "job-456", "status": "PENDING", "user_id": "user1"}'

# Update job
curl -X PATCH http://localhost:3000/ray_jobs?job_id=eq.job-123 \
  -H "Content-Type: application/json" \
  -d '{"status": "RUNNING"}'

# Delete job
curl -X DELETE http://localhost:3000/ray_jobs?job_id=eq.job-123
```

**2. Advanced Queries**

```bash
# Filter by status
curl "http://localhost:3000/ray_jobs?status=eq.RUNNING"

# Order by created_at
curl "http://localhost:3000/ray_jobs?order=created_at.desc"

# Limit & offset (pagination)
curl "http://localhost:3000/ray_jobs?limit=10&offset=20"

# Join with users table
curl "http://localhost:3000/ray_jobs?select=*,users(username,email)"
```

**3. Row-Level Security (RLS)**

```sql
-- Users can only see their own jobs
CREATE POLICY user_jobs ON ray_jobs
  FOR SELECT
  USING (user_id = current_setting('request.jwt.claim.user_id'));

-- Users can only update their own jobs
CREATE POLICY user_update_jobs ON ray_jobs
  FOR UPDATE
  USING (user_id = current_setting('request.jwt.claim.user_id'));
```

**Privacy**: Full control over access policies, no data exposure

---

## 4️⃣ Vector Search (pgvector)

### What We're Replicating

Supabase Vector: Store and search embeddings

### Self-Hosted Solution: pgvector Extension

#### Implementation

**1. Enable pgvector**

```bash
# Install extension in PostgreSQL container
docker exec -it mlflow-postgres psql -U mlflow -d mlflow -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

**2. Create Vector Tables**

```sql
-- Store model embeddings
CREATE TABLE model_embeddings (
  id SERIAL PRIMARY KEY,
  model_name TEXT NOT NULL,
  version TEXT NOT NULL,
  embedding VECTOR(512),  -- 512-dimensional embeddings
  metadata JSONB,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Create index for fast similarity search
CREATE INDEX ON model_embeddings USING ivfflat (embedding vector_cosine_ops);
```

**3. Store Embeddings**

```python
import psycopg2
import numpy as np
from sentence_transformers import SentenceTransformer

# Generate embedding
model = SentenceTransformer('all-MiniLM-L6-v2')
description = "Face detection model trained on WIDER FACE dataset"
embedding = model.encode(description)

# Insert into database
conn = psycopg2.connect("postgresql://mlflow:password@localhost/mlflow")
cur = conn.cursor()
cur.execute(
    "INSERT INTO model_embeddings (model_name, version, embedding, metadata) VALUES (%s, %s, %s, %s)",
    ('face_detector', 'v5', embedding.tolist(), {'dataset': 'wider_face'})
)
conn.commit()
```

**4. Semantic Search**

```python
def search_similar_models(query: str, top_k: int = 5):
    """Find similar models using vector search."""
    # Generate query embedding
    query_embedding = model.encode(query)

    # Search database
    cur.execute("""
        SELECT model_name, version, metadata,
               1 - (embedding <=> %s) AS similarity
        FROM model_embeddings
        ORDER BY embedding <=> %s
        LIMIT %s
    """, (query_embedding.tolist(), query_embedding.tolist(), top_k))

    return cur.fetchall()

# Usage
results = search_similar_models("license plate detection for autonomous vehicles")
for model_name, version, metadata, similarity in results:
    print(f"{model_name} v{version}: {similarity:.2f}")
```

**Use Cases**:

- Model discovery (semantic search)
- Duplicate detection (similar models)
- Recommendation engine (suggest related models)

---

## 5️⃣ Edge Functions (OpenFaaS)

### What We're Replicating

Supabase Edge Functions: Serverless functions at the edge

### Self-Hosted Solution: OpenFaaS

#### Implementation

**1. Deploy OpenFaaS**

```bash
# Install OpenFaaS using arkade
arkade install openfaas

# Or use Helm
helm repo add openfaas https://openfaas.github.io/faas-netes/
helm upgrade openfaas --install openfaas/openfaas \
    --namespace openfaas \
    --set functionNamespace=openfaas-fn \
    --set generateBasicAuth=true
```

**2. Create Function (Python)**

```python
# handler.py
import json
import requests

def handle(req):
    """
    Serverless function: Check if model is production-ready
    """
    data = json.loads(req)
    model_id = data.get('model_id')

    # Fetch model metrics from MLflow
    mlflow_uri = "http://mlflow-server:8080"
    response = requests.get(f"{mlflow_uri}/api/2.0/mlflow/runs/get?run_id={model_id}")
    metrics = response.json()['run']['data']['metrics']

    # Production criteria
    is_ready = (
        metrics.get('precision', 0) > 0.85 and
        metrics.get('recall', 0) > 0.80 and
        metrics.get('map50', 0) > 0.85
    )

    return json.dumps({
        'model_id': model_id,
        'production_ready': is_ready,
        'metrics': metrics
    })
```

**3. Deploy Function**

```bash
# Create stack.yml
faas-cli new check-model-readiness --lang python3
faas-cli build -f check-model-readiness.yml
faas-cli deploy -f check-model-readiness.yml
```

**4. Invoke Function**

```bash
# HTTP request
curl -X POST http://localhost:8080/function/check-model-readiness \
  -H "Content-Type: application/json" \
  -d '{"model_id": "run-123"}'

# Response
{
  "model_id": "run-123",
  "production_ready": true,
  "metrics": {"precision": 0.87, "recall": 0.83, "map50": 0.89}
}
```

**Use Cases**:

- Model validation hooks
- Automated quality checks
- Custom webhooks (e.g., Slack notifications)
- Data preprocessing pipelines

---

## 6️⃣ Full-Text Search (Meilisearch)

### What We're Replicating

Supabase Full-Text Search: Fast, typo-tolerant search

### Self-Hosted Solution: Meilisearch

#### Implementation

**1. Deploy Meilisearch**

```yaml
# Add to docker-compose.yml
services:
  meilisearch:
    image: getmeili/meilisearch:latest
    environment:
      MEILI_MASTER_KEY: ${MEILI_MASTER_KEY}
      MEILI_ENV: production
    volumes:
      - meilisearch_data:/meili_data
    ports:
      - "7700:7700"
    networks:
      - ml-platform
    labels:
      - traefik.enable=true
      - traefik.http.routers.meilisearch.rule=PathPrefix(`/search`)

volumes:
  meilisearch_data:
```

**2. Index Models & Datasets**

```python
import meilisearch

client = meilisearch.Client('http://localhost:7700', 'masterKey')

# Create index
models_index = client.index('models')

# Add documents
models = [
    {
        'id': 1,
        'name': 'face_detector_v5',
        'description': 'High-resolution face detection for autonomous vehicles',
        'tags': ['face', 'detection', 'automotive'],
        'precision': 0.87,
        'recall': 0.83,
        'created_at': '2025-11-20'
    },
    {
        'id': 2,
        'name': 'license_plate_detector',
        'description': 'ALPR for US and EU license plates',
        'tags': ['alpr', 'license-plate', 'automotive'],
        'precision': 0.92,
        'recall': 0.88,
        'created_at': '2025-11-15'
    }
]
models_index.add_documents(models)

# Configure searchable attributes
models_index.update_searchable_attributes(['name', 'description', 'tags'])

# Configure filterable attributes
models_index.update_filterable_attributes(['tags', 'precision', 'recall'])
```

**3. Search API**

```python
# Simple search
results = models_index.search('face detection')

# Advanced search with filters
results = models_index.search(
    'automotive',
    filter='precision > 0.85 AND tags = "detection"',
    limit=10
)

# Typo-tolerant search
results = models_index.search('licanse plat detectr')  # Finds "license plate detector"
```

**4. Integration with Ray Compute UI**

```javascript
// Real-time search in Next.js UI
import { useState, useEffect } from "react";
import { MeiliSearch } from "meilisearch";

const client = new MeiliSearch({ host: "http://localhost:7700" });

export default function ModelSearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);

  useEffect(() => {
    if (query.length > 2) {
      client.index("models").search(query).then(setResults);
    }
  }, [query]);

  return (
    <div>
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search models..."
      />
      <ul>
        {results.hits.map((model) => (
          <li key={model.id}>
            {model.name} - {model.description}
          </li>
        ))}
      </ul>
    </div>
  );
}
```

**Privacy**: All search indices stored locally, no external dependencies

---

## 7️⃣ CDN & Edge Caching (Caddy)

### What We're Replicating

Supabase CDN: Fast content delivery, caching

### Self-Hosted Solution: Caddy Server

#### Implementation

**1. Deploy Caddy**

```yaml
# Add to docker-compose.yml
services:
  caddy:
    image: caddy:latest
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
      - caddy_config:/config
    networks:
      - ml-platform

volumes:
  caddy_data:
  caddy_config:
```

**2. Configure Caching**

```caddyfile
# Caddyfile
ml-platform.local {
    # Cache static assets
    @static {
        path *.js *.css *.png *.jpg *.woff2 *.pt *.onnx
    }
    header @static Cache-Control "public, max-age=31536000"

    # Cache models for 1 hour
    @models {
        path /storage/models/*
    }
    header @models Cache-Control "public, max-age=3600"

    # No cache for APIs
    @api {
        path /api/*
    }
    header @api Cache-Control "no-cache"

    # Reverse proxy to Traefik
    reverse_proxy traefik:80

    # Enable compression
    encode gzip

    # HTTPS auto-provisioning
    tls internal
}
```

**3. CloudFlare Tunnel (Optional for Remote Access)**

```bash
# Install cloudflared
brew install cloudflared

# Authenticate
cloudflared tunnel login

# Create tunnel
cloudflared tunnel create ml-platform

# Configure tunnel
cat > ~/.cloudflared/config.yml <<EOF
tunnel: ml-platform
credentials-file: ~/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: ml-platform.yourdomain.com
    service: http://localhost:80
  - service: http_status:404
EOF

# Run tunnel
cloudflared tunnel run ml-platform
```

**Privacy**: Caddy cache on your server, CloudFlare tunnel optional (can be disabled)

---

## 8️⃣ Analytics Dashboard (Grafana + Prometheus)

### What We're Replicating

Supabase Analytics: Usage metrics, performance dashboards

### Self-Hosted Solution: Grafana + Prometheus (Already Deployed)

#### Enhancements

**1. Add Custom Metrics**

```python
from prometheus_client import Counter, Histogram, Gauge

# Track model inference
inference_counter = Counter('model_inference_total', 'Total model inferences', ['model_name'])
inference_latency = Histogram('model_inference_latency_seconds', 'Inference latency', ['model_name'])
gpu_utilization = Gauge('gpu_utilization_percent', 'GPU utilization', ['gpu_id'])

# In your inference code
with inference_latency.labels(model_name='face_detector_v5').time():
    result = model.predict(image)
inference_counter.labels(model_name='face_detector_v5').inc()
```

**2. Create Grafana Dashboard**

```json
{
  "dashboard": {
    "title": "ML Platform Analytics",
    "panels": [
      {
        "title": "Model Inference Rate",
        "targets": [
          {
            "expr": "rate(model_inference_total[5m])"
          }
        ]
      },
      {
        "title": "Average Latency",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, model_inference_latency_seconds)"
          }
        ]
      },
      {
        "title": "GPU Utilization",
        "targets": [
          {
            "expr": "gpu_utilization_percent"
          }
        ]
      }
    ]
  }
}
```

**3. Usage Analytics (PostgreSQL)**

```sql
-- Track API usage
CREATE TABLE api_usage (
  id SERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  method TEXT NOT NULL,
  status_code INT NOT NULL,
  latency_ms INT NOT NULL,
  timestamp TIMESTAMP DEFAULT NOW()
);

-- Daily usage summary
CREATE VIEW daily_usage AS
SELECT
  user_id,
  DATE(timestamp) as date,
  COUNT(*) as requests,
  AVG(latency_ms) as avg_latency,
  COUNT(CASE WHEN status_code >= 400 THEN 1 END) as errors
FROM api_usage
GROUP BY user_id, DATE(timestamp);
```

---

## 🎯 Premium Tier Feature Matrix

| Feature                 | Free Tier | Starter ($49/mo)   | Pro ($199/mo)       | Enterprise (Custom) |
| ----------------------- | --------- | ------------------ | ------------------- | ------------------- |
| **Real-Time Updates**   | ❌        | ✅ (5 channels)    | ✅ (Unlimited)      | ✅ (Unlimited)      |
| **Object Storage**      | 1 GB      | 25 GB              | 100 GB              | Unlimited           |
| **Edge Functions**      | ❌        | 10k invocations/mo | 100k invocations/mo | Unlimited           |
| **Vector Search**       | ❌        | ✅ (1M vectors)    | ✅ (10M vectors)    | ✅ (Unlimited)      |
| **Full-Text Search**    | ❌        | ✅ (10k docs)      | ✅ (100k docs)      | ✅ (Unlimited)      |
| **CDN Bandwidth**       | 5 GB      | 100 GB             | 500 GB              | Unlimited           |
| **Analytics Retention** | 7 days    | 30 days            | 90 days             | Custom              |

---

## 📊 Implementation Roadmap

### Phase 1: Core Features (Months 1-2)

- ✅ PostgREST (Auto APIs)
- ✅ MinIO (Object Storage)
- ✅ Prometheus + Grafana (Analytics)

### Phase 2: Real-Time & Search (Months 3-4)

- ✅ pg_notify + WebSockets (Real-Time)
- ✅ Meilisearch (Full-Text Search)
- ✅ pgvector (Vector Search)

### Phase 3: Advanced Features (Months 5-6)

- ✅ OpenFaaS (Edge Functions)
- ✅ Caddy (CDN & Caching)
- ✅ CloudFlare Tunnel (Optional Remote Access)

### Phase 4: Productization (Months 7-12)

- ✅ Billing integration (Stripe)
- ✅ Usage metering & quotas
- ✅ Admin dashboard
- ✅ Customer onboarding flow

---

## 🔐 Privacy & Security Guarantees

### Self-Hosted Advantages

1. ✅ **No vendor lock-in** - All data on your infrastructure
2. ✅ **No data exfiltration** - Never leaves your network
3. ✅ **Full audit trail** - All logs under your control
4. ✅ **Compliance-ready** - GDPR, HIPAA, SOC 2 (your responsibility)
5. ✅ **Cost predictability** - No surprise cloud bills

### Security Best Practices

- ✅ TLS everywhere (Traefik + Let's Encrypt)
- ✅ Row-level security (PostgreSQL RLS)
- ✅ API authentication (Authentik OAuth)
- ✅ Network isolation (Docker networks)
- ✅ Regular backups (automated scripts)
- ✅ Secrets management (.env files, git-ignored)

---

## 💰 Cost Comparison

### Supabase Pricing (SaaS)

- **Free**: $0/mo (limited, throttled)
- **Pro**: $25/mo + usage ($0.02/GB storage, $0.09/GB bandwidth)
- **Team**: $599/mo + usage
- **Enterprise**: Custom (typically $5k+/mo)

### Self-Hosted Costs

- **Hardware**: One-time ($2k-10k for server)
- **Electricity**: ~$50-150/mo (24/7 operation)
- **Maintenance**: Your time (or hire devops)
- **Total**: ~$100-300/mo ongoing (after hardware)

**Break-even**: Self-hosted pays off after 6-12 months if you'd be on Supabase Pro/Team

---

## 🚀 Next Steps

1. **Enable PostgREST** - Add to docker-compose.yml
2. **Deploy MinIO** - Set up object storage buckets
3. **Install Meilisearch** - Create search indices
4. **Add pgvector** - Enable vector search
5. **Configure Caddy** - Set up caching layer
6. **Test OpenFaaS** - Deploy first edge function
7. **Update Ray Compute UI** - Integrate new features
8. **Document APIs** - Add to API_REFERENCE.md

---

**Related Documentation**:

- [MONETIZATION_STRATEGY.md](../pii-pro/docs/MONETIZATION_STRATEGY.md) - Revenue models
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) - Service integration

**Questions? Issues?**  
See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) or open a GitHub issue.

---

_All features maintain 100% privacy-first principles. No data ever leaves your infrastructure._
