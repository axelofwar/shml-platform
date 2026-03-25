---
name: platform-services
description: "Query and inspect core platform services: MLflow experiments/runs, Prometheus metrics, Traefik routers/services, Ray cluster/jobs, and FusionAuth identity provider status. Use for routine operational read-only inspection of any of these services."
license: MIT
compatibility: All operations require the relevant service to be running. Safe to run during training unless noted. Extends platform-health (container/GPU checks) with service-level operations.
metadata:
  author: shml-platform
  version: "1.0"
allowed-tools: Bash(curl:*) Bash(python3:*)
---

# Platform Services Operations Skill

## When to use this skill
Use this skill when the user asks to:
- List MLflow experiments or look up run metrics / artifacts
- Query Prometheus for a metric or check alerting rules
- Inspect Traefik routing configuration (routers, services, middlewares)
- Check Ray cluster resources, job list, or job logs
- Verify FusionAuth / OAuth2-proxy health and identity provider status

> For **container health / GPU checks**, use the `platform-health` skill instead.
> For **Ray training job submission**, use the `ray-compute` skill instead.

## Service Map

| Service | Internal URL | External Path |
|---|---|---|
| MLflow tracking | `http://mlflow-server:5000` | `/mlflow` |
| MLflow API | `http://mlflow-api:8000` | `/mlflow/api` |
| Prometheus | `http://prometheus:9090` | `/prometheus` |
| Traefik dashboard | `http://traefik:8080` | `:8090/dashboard/` |
| Ray dashboard | `http://ray-head:8265` | `/ray` |
| Ray Compute API | `http://ray-compute-api:8000/api/v1` | `/api/ray` |
| FusionAuth | `http://fusionauth:9011` | `/auth` |
| OAuth2-Proxy | `http://oauth2-proxy:4180` | — |
| Grafana | `http://grafana:3000` | `/grafana` |

---

## MLflow Operations

### List experiments
```bash
curl -sf http://localhost/mlflow/api/2.0/mlflow/experiments/list | python3 -m json.tool
```

### Search runs (latest 10 from an experiment)
```bash
# Replace <experiment_id> with the numeric ID from experiments/list
curl -sf -X POST http://localhost/mlflow/api/2.0/mlflow/runs/search \
  -H "Content-Type: application/json" \
  -d '{
    "experiment_ids": ["<experiment_id>"],
    "max_results": 10,
    "order_by": ["start_time DESC"]
  }' | python3 -m json.tool
```

### Get a specific run's metrics
```bash
curl -sf "http://localhost/mlflow/api/2.0/mlflow/runs/get?run_id=<run_id>" | python3 -m json.tool
```

### List artifacts for a run
```bash
curl -sf "http://localhost/mlflow/api/2.0/mlflow/artifacts/list?run_id=<run_id>&path=" | python3 -m json.tool
```

### MLflow health
```bash
curl -sf http://localhost/mlflow/health && echo "OK"
```

### Safety
- ✅ All GET/list/search operations — safe during training
- ⚠️ POST to `/runs/log-metric` or `/runs/update` — avoid during active training (will corrupt run state)

---

## Prometheus Operations

### Instant query
```bash
# CPU utilisation
curl -sf 'http://localhost:9090/api/v1/query?query=100-(avg+by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m]))*100)' | python3 -m json.tool

# Container memory usage
curl -sf 'http://localhost:9090/api/v1/query?query=container_memory_usage_bytes{name!=""}' | python3 -c "
import json, sys
data = json.load(sys.stdin)
for r in data['data']['result'][:10]:
    name = r['metric'].get('name','?')
    mb = round(float(r['value'][1])/1024/1024, 1)
    print(f'{name}: {mb} MiB')
"

# GPU utilisation (DCGM exporter)
curl -sf 'http://localhost:9090/api/v1/query?query=DCGM_FI_DEV_GPU_UTIL' | python3 -m json.tool
```

### Check Prometheus health and targets
```bash
curl -sf http://localhost:9090/-/healthy && echo "Prometheus OK"
curl -sf http://localhost:9090/api/v1/targets | python3 -c "
import json, sys
data = json.load(sys.stdin)
for t in data['data']['activeTargets']:
    print(t['labels'].get('job','?'), t['health'], t['lastError'] or 'ok')
"
```

### List alerting rules
```bash
curl -sf http://localhost:9090/api/v1/rules | python3 -c "
import json, sys
data = json.load(sys.stdin)
for g in data['data']['groups']:
    for r in g['rules']:
        if r['type'] == 'alerting':
            print(r['state'].upper().ljust(8), r['name'])
"
```

### Safety: All Prometheus operations are read-only and safe at any time.

---

## Traefik Operations

### List all routers
```bash
curl -sf http://localhost:8090/api/http/routers | python3 -c "
import json, sys
routers = json.load(sys.stdin)
for name, r in sorted(routers.items()):
    print(f\"{r['status'].ljust(7)} {r.get('priority',0):>12}  {name}  →  {r.get('rule','')[:60]}\")
"
```

### List services
```bash
curl -sf http://localhost:8090/api/http/services | python3 -c "
import json, sys
svcs = json.load(sys.stdin)
for name, s in sorted(svcs.items()):
    lb = s.get('loadBalancer', {})
    servers = lb.get('servers', [])
    urls = [srv.get('url','?') for srv in servers]
    print(f\"{name}: {urls}\")
"
```

### Inspect a single router (e.g. agent-service)
```bash
curl -sf http://localhost:8090/api/http/routers/agent-service@docker | python3 -m json.tool
```

### List middlewares
```bash
curl -sf http://localhost:8090/api/http/middlewares | python3 -c "
import json, sys
mw = json.load(sys.stdin)
for name in sorted(mw): print(name)
"
```

### Traefik health
```bash
curl -sf http://localhost:8090/ping && echo "Traefik OK"
```

### Safety: All Traefik API calls are read-only and safe at any time.

---

## Ray Cluster Operations

### Cluster resources
```bash
curl -sf http://localhost/api/ray/resources | python3 -m json.tool
# Or direct:
curl -sf http://localhost:8265/api/cluster_status | python3 -m json.tool
```

### List jobs (current + recent)
```bash
curl -sf http://localhost/api/ray/jobs | python3 -c "
import json, sys
jobs = json.load(sys.stdin)
for j in jobs:
    print(j.get('status','?').ljust(10), j.get('job_id','?'), j.get('entrypoint','')[:50])
"
```

### Get job logs
```bash
curl -sf "http://localhost/api/ray/jobs/<job_id>/logs"
```

### Ray health
```bash
curl -sf http://localhost/api/ray/health && echo "Ray OK"
```

### Safety
- ✅ GET /resources, /jobs, /jobs/{id}/logs — safe at any time
- ❌ DELETE /jobs/{id} — requires user confirmation (cancels running training)

---

## FusionAuth / Auth Operations

### Health and status
```bash
curl -sf http://localhost/auth/api/status | python3 -m json.tool
```

### List identity providers (OAuth integrations)
```bash
# Requires FusionAuth API key (FUSIONAUTH_API_KEY env var)
curl -sf http://localhost/auth/api/identity-provider \
  -H "Authorization: ${FUSIONAUTH_API_KEY}" | python3 -m json.tool
```

### OAuth2-Proxy health
```bash
curl -sf http://localhost/ping && echo "OAuth2-Proxy OK"
```

### FusionAuth JWT key rotation status
```bash
curl -sf http://localhost/auth/api/jwt/public_key | python3 -m json.tool
```

### Safety
- ✅ Health and public-key endpoints — safe and unauthenticated
- ⚠️ Identity provider list — requires API key
- ❌ POST /user / DELETE /user — requires explicit user confirmation

---

## Grafana Operations

### Health
```bash
curl -sf http://localhost/grafana/api/health | python3 -m json.tool
```

### List dashboards
```bash
curl -sf "http://localhost/grafana/api/search?type=dash-db" | python3 -c "
import json, sys
for d in json.load(sys.stdin):
    print(d.get('uid','?').ljust(20), d.get('title','?'))
"
```

### Safety: All Grafana read operations are safe at any time.

---

## Common Diagnostic Pattern

When a user asks "is the platform healthy?" and needs service-level (not just container) detail:

```bash
echo "=== MLflow ===" && curl -sf http://localhost/mlflow/health && echo OK
echo "=== Prometheus ===" && curl -sf http://localhost:9090/-/healthy && echo OK
echo "=== Traefik ===" && curl -sf http://localhost:8090/ping && echo OK
echo "=== Ray ===" && curl -sf http://localhost/api/ray/health && echo OK
echo "=== OAuth2-Proxy ===" && curl -sf http://localhost/ping && echo OK
```
