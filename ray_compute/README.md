# Ray Compute Platform

**Status:** ✅ Production Ready  
OAuth-enabled GPU platform with Ray 2.9.0-gpu, FastAPI, FusionAuth, Next.js Web UI

---

## Quick Start

### Access URLs

| Service | URL | Auth Required |
|---------|-----|---------------|
| Ray Compute UI | https://${PUBLIC_DOMAIN}/ray/ui | OAuth (developer+) |
| Ray Dashboard | https://${PUBLIC_DOMAIN}/ray/ | OAuth (developer+) |
| Ray API | https://${PUBLIC_DOMAIN}/api/ray | API Key or OAuth |
| Grafana | https://${PUBLIC_DOMAIN}/grafana | OAuth (developer+) |

### Prerequisites

```bash
# Docker 24.0+, Compose 2.20+
docker --version && docker compose version

# NVIDIA GPU drivers
nvidia-smi

# Platform network
docker network inspect shml-platform
```

### Start Services

```bash
cd ray_compute

# Start with safe startup (recommended)
../start_all_safe.sh start ray

# Check status
../check_platform_status.sh
```

---

## 🔐 Authentication

### API Keys (Recommended for Scripts)

API keys bypass OAuth and provide direct API access. Get keys from:

1. **Admin keys**: \`ray_compute/.env\` → \`CICD_ADMIN_KEY\`, \`CICD_DEVELOPER_KEY\`
2. **User keys**: Ray Compute UI → Settings → Generate API Key

```bash
# Set environment variable
export SHML_API_KEY='your-api-key-here'

# Or pass directly
python submit_face_detection_job.py --api-key 'your-key'
```

### OAuth (Browser Sessions)

OAuth is handled automatically when accessing UIs via browser. Requires:
- FusionAuth account with \`developer\` role or higher
- Active session cookie

### Checking Auth Status

```bash
# Via API
curl -H "X-API-Key: \$SHML_API_KEY" \\
  https://${PUBLIC_DOMAIN}/api/ray/users/me

# Response
{
  "user_id": "...",
  "username": "cicd-admin",
  "email": "cicd-admin@ray-compute.local",
  "role": "admin"
}
```

---

## 📡 Health Checks

### Quick Health Check

```bash
# All-in-one platform health
curl https://${PUBLIC_DOMAIN}/api/ray/health

# Expected response
{
  "status": "ok",
  "database": "healthy",
  "mlflow": "healthy",
  "ray": "healthy",
  "timestamp": "2025-12-11T..."
}
```

### Service-Specific Health

```bash
# Ray Compute API
curl https://${PUBLIC_DOMAIN}/api/ray/health

# MLflow
curl https://${PUBLIC_DOMAIN}/mlflow/health

# Direct container health (local only)
curl http://172.30.0.25:8000/health   # Ray API
curl http://172.30.0.23:8265/api/version  # Ray Head
```

---

## 🚀 Job Submission

### Using the SDK (Recommended)

```bash
cd ray_compute/jobs

# Dry run (validate without submitting)
python submit_face_detection_job.py --dry-run --api-key \$SHML_API_KEY

# Submit training job (works remotely via Tailscale)
python submit_face_detection_job.py \\
  --api-key \$SHML_API_KEY \\
  --epochs 100 \\
  --batch-size 8 \\
  --curriculum \\
  --sapo \\
  --hard-mining

# Submit from local server (faster, direct container access)
python submit_face_detection_job.py --local --api-key \$SHML_API_KEY

# Resume from checkpoint
python submit_face_detection_job.py --resume-phase1 --api-key \$SHML_API_KEY
```

### Using curl (Direct API)

```bash
# Submit a simple job
curl -X POST https://${PUBLIC_DOMAIN}/api/ray/jobs \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: \$SHML_API_KEY" \\
  -d '{
    "name": "my-training-job",
    "job_type": "training",
    "code": "print(\"Hello from Ray!\")",
    "resources": {"num_cpus": 4, "num_gpus": 1, "memory_gb": 16}
  }'
```

### Using Python SDK Directly

```python
from shml.client import Client

client = Client(api_key="your-api-key")

# Submit a job
response = client.submit(
    name="my-job",
    code="print('Hello!')",
    gpu=1.0,
    cpu=4,
    memory_gb=16,
)
print(f"Job ID: {response.job_id}")

# Check status
job = client.status(response.job_id)
print(f"Status: {job.status}")
```

---

## 📋 Job Management

### Check Job Status

```bash
# Via SDK script
python submit_face_detection_job.py --status job-abc123 --api-key \$SHML_API_KEY

# Via curl
curl -H "X-API-Key: \$SHML_API_KEY" \\
  https://${PUBLIC_DOMAIN}/api/ray/jobs/job-abc123

# Via Ray CLI (local only)
docker exec ray-head ray job status job-abc123
```

### Get Job Logs

```bash
# Via SDK script
python submit_face_detection_job.py --logs job-abc123 --api-key \$SHML_API_KEY

# Via curl
curl -H "X-API-Key: \$SHML_API_KEY" \\
  https://${PUBLIC_DOMAIN}/api/ray/jobs/job-abc123/logs

# Via Ray CLI (local only, real-time)
docker exec ray-head ray job logs job-abc123 --follow

# Direct log file (local only)
docker exec ray-head tail -f /tmp/ray/session_latest/logs/job-driver-job-abc123.log
```

### List Recent Jobs

```bash
# Via SDK script
python submit_face_detection_job.py --list --api-key \$SHML_API_KEY

# Via curl
curl -H "X-API-Key: \$SHML_API_KEY" \\
  https://${PUBLIC_DOMAIN}/api/ray/jobs

# Via Ray CLI (local only)
docker exec ray-head ray job list
```

### Cancel a Job

```bash
# Via curl
curl -X DELETE -H "X-API-Key: \$SHML_API_KEY" \\
  https://${PUBLIC_DOMAIN}/api/ray/jobs/job-abc123

# Via Ray CLI (local only)
docker exec ray-head ray job stop job-abc123
```

---

## 📊 Monitoring

### Grafana Dashboards

- **Face Detection Training**: https://${PUBLIC_DOMAIN}/grafana/d/face-detection-training
- **Ray Cluster**: https://${PUBLIC_DOMAIN}/grafana/d/ray-cluster

### Container Logs

```bash
# Ray Compute API
docker logs ray-compute-api -f --tail 100

# Ray Head Node
docker logs ray-head -f --tail 100

# Ray Compute UI
docker logs ray-compute-ui -f --tail 100
```

### GPU Monitoring

```bash
# Check GPU utilization
nvidia-smi

# Watch GPU usage
watch -n 1 nvidia-smi

# GPU inside Ray container
docker exec ray-head nvidia-smi
```

---

## ��️ Troubleshooting

### Ray UI 404 After Login

1. Clear browser cookies
2. Try incognito window
3. Check Traefik logs: \`docker logs shml-traefik 2>&1 | grep ray/ui\`

### Job Stuck in PENDING

```bash
# Check Ray cluster status
docker exec ray-head ray status

# Check available resources
docker exec ray-head ray resources
```

### Authentication Failures

```bash
# Test API key
curl -H "X-API-Key: \$SHML_API_KEY" \\
  https://${PUBLIC_DOMAIN}/api/ray/users/me

# Check OAuth2-proxy logs
docker logs oauth2-proxy 2>&1 | tail -50
```

---

## 📚 Documentation

- **[ARCHITECTURE.md](../ARCHITECTURE.md)** - System design
- **[API_REFERENCE.md](../API_REFERENCE.md)** - Full API documentation  
- **[INTEGRATION_GUIDE.md](../INTEGRATION_GUIDE.md)** - MLflow + Ray integration
- **[TROUBLESHOOTING.md](../TROUBLESHOOTING.md)** - Common issues & solutions

---

**Last Updated:** 2025-12-11
