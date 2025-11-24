# Lessons Learned: Platform Stability & Best Practices

**Created:** 2025-11-23  
**Status:** REFERENCE DOCUMENT - Critical Patterns & Pitfalls

This document consolidates critical lessons learned from debugging platform startup, performance, and routing issues. These patterns are now encoded in copilot instructions, inline comments, and troubleshooting guides.

---

## 🎯 Executive Summary

### What We Fixed
1. **Traefik Routing Priority Conflict**: MLflow API routes returning 404 due to internal API precedence
2. **Ray Head Memory Allocation**: Startup failures from object store exceeding container limits
3. **MLflow API Performance**: 97-second response times from expensive health check queries
4. **Service Startup Dependencies**: Cascading failures from simultaneous service starts
5. **Orphaned Container Cleanup**: Manual docker commands bypassing compose management

### Impact
- **Performance**: 97,147ms → 10ms API response time (9,700x improvement)
- **Reliability**: 100% successful startup (16/16 services healthy)
- **Startup Time**: ~90 seconds to full platform ready
- **Developer Experience**: Clean, predictable startup every time

---

## 🚦 Critical Pattern #1: Traefik Router Priority

### The Problem
```yaml
# ❌ WRONG - Will be intercepted by Traefik internal API
labels:
  - traefik.http.routers.my-api.rule=PathPrefix(`/api/v1`)
  - traefik.http.routers.my-api.priority=500  # Too low!
```

**Result:** `/api/v1/health` returns 404 from Traefik dashboard API instead of your application.

### Why This Happens
- Traefik internal API dashboard exposed at `/api` with priority **2147483646** (max int32 - 1)
- Traefik evaluates routes by priority (highest first)
- PathPrefix(`/api`) matches `/api/v1/*`, `/api/v2/*`, etc.
- Your API router with priority 500 never gets a chance to handle the request

### The Solution
```yaml
# ✅ CORRECT - Takes precedence over Traefik internal API
labels:
  - traefik.http.routers.mlflow-api-v1.rule=PathPrefix(`/api/v1`)
  - traefik.http.routers.mlflow-api-v1.priority=2147483647  # Max int32
  - traefik.http.routers.mlflow-api-v1.service=mlflow-api-service
```

### Verification
```bash
# Check router priorities
curl -s http://localhost:8090/api/http/routers | \
  jq '.[] | select(.name | contains("api")) | {name, rule, priority}'

# Expected output:
# mlflow-api-v1@docker: priority 2147483647 (your API wins!)
# api@internal: priority 2147483646 (Traefik dashboard)
```

### Where This Is Documented
- **docker-compose.yml**: Lines 318-325 (inline comments)
- **mlflow-server/.github/copilot-instructions.md**: "Traefik Routing & Priority Configuration" section
- **TROUBLESHOOTING.md**: "Traefik API Routes Return 404" section

---

## 🧠 Critical Pattern #2: Ray Head Memory Allocation

### The Problem
```yaml
# ❌ WRONG - Ray crashes with "memory available is less than -112%"
command: ray start --head --object-store-memory=4000000000  # 4GB
deploy:
  resources:
    limits:
      memory: 2G  # Only 2GB container!
```

**Result:** ValueError during Ray startup, container continuously restarts.

### Why This Happens
Ray allocates:
- Object store memory (`--object-store-memory`)
- Shared memory for plasma store (`shm_size`)
- Internal overhead (Redis, scheduling, monitoring)

**Calculation:**
```
Total Required = object_store + shm_size + overhead (~1GB)
Example: 4GB + 2GB + 1GB = 7GB needed, but container has 2GB = FAIL
```

### The Solution
```yaml
# ✅ CORRECT - Resources fit within container limits
command: >
  ray start --head
  --object-store-memory=1000000000  # 1GB
  --num-cpus=4  # Matches system capacity
  --num-gpus=1
  --block
shm_size: 2gb
deploy:
  resources:
    limits:
      cpus: '4.0'
      memory: 4G  # Accommodates 1GB + 2GB + 1GB overhead
```

### Allocation Guidelines

**For 16GB RAM System (our case):**
```
Total RAM:    16GB
Host OS:      4GB reserved
Ray Head:     4GB (1GB object + 2GB shm + 1GB overhead)
Ray Worker:   4GB
Other Apps:   4GB
```

**For Production (64GB RAM):**
```
Total RAM:    64GB
Host OS:      8GB reserved
Ray Head:     16GB (8GB object + 4GB shm + 4GB overhead)
Ray Workers:  32GB (4x 8GB)
Other Apps:   8GB
```

### Verification
```bash
# Ray should start without errors
docker logs ray-head | grep "Ray runtime started"

# Should NOT see:
docker logs ray-head | grep "ValueError.*memory.*less than"

# Check actual resource usage
docker stats ray-head --no-stream
```

### Where This Is Documented
- **docker-compose.yml**: Lines 488-523 (inline comments with calculations)
- **ray_compute/.github/copilot-instructions.md**: "Ray Head Resource Allocation" section
- **STARTUP_ANALYSIS.md**: Hardware compatibility analysis

---

## ⚡ Critical Pattern #3: Health Check Performance

### The Problem
```python
# ❌ WRONG - Expensive database query on EVERY health check
@app.get("/health")
async def health_check():
    experiments = client.search_experiments(max_results=1)  # 97 seconds!
    return {"status": "healthy"}
```

**Result:** Health checks timeout, Traefik marks service unhealthy, cascade failures.

### Why This Happens
- Health checks called every 10 seconds by Docker and Traefik
- Each check makes round-trip to MLflow tracking server
- MLflow queries PostgreSQL database
- Network latency + database query time = 97+ seconds
- Health check timeout (30s) exceeded → service marked unhealthy

### The Solution
```python
# ✅ CORRECT - Static response, no external dependencies
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "mlflow-api",
        "version": "1.0.0"
    }
```

**Result:** Response time 97,147ms → 10ms (9,700x faster).

### Health Check Best Practices

**DO:**
- ✅ Return static JSON with service info
- ✅ Check critical internal state (e.g., config loaded)
- ✅ Use separate `/ready` endpoint for expensive checks
- ✅ Keep response time < 100ms

**DON'T:**
- ❌ Query databases
- ❌ Call external APIs
- ❌ Perform expensive computations
- ❌ Test end-to-end functionality

### Readiness vs Liveness
```python
# Liveness: Is the service alive? (called every 10s)
@app.get("/health")
async def liveness():
    return {"status": "healthy"}

# Readiness: Can it handle requests? (called at startup)
@app.get("/ready")
async def readiness():
    try:
        experiments = client.search_experiments(max_results=1)
        return {"status": "ready", "experiments": len(experiments)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
```

### Where This Is Documented
- **mlflow-server/api/main.py**: Lines 261-273 (optimized health check)
- **STARTUP_SUCCESS.md**: Performance analysis section

---

## 🚀 Critical Pattern #4: Phased Service Startup

### The Problem
```bash
# ❌ WRONG - All services start simultaneously
docker-compose up -d
```

**Result:**
- APIs start before databases are ready → connection failures
- Services restart repeatedly → resource contention
- Health checks fail → Traefik marks all services unhealthy
- Startup takes 5+ minutes with unpredictable success rate

### Why This Happens
Docker Compose `depends_on: service_healthy` only ensures containers START in order, not that they're READY. Dependencies can fail if:
1. Database container is "healthy" but not accepting connections yet
2. Multiple services competing for CPU/memory during startup
3. Network routes not fully established
4. Volume mounts not synchronized

### The Solution
```bash
# ✅ CORRECT - Phased startup with verification
#!/bin/bash

# Phase 1: Infrastructure (databases, caches, gateway)
echo "Starting infrastructure..."
docker-compose up -d traefik redis postgres
sleep 10

# Wait for critical services
for svc in postgres redis traefik; do
    while [ "$(docker inspect --format='{{.State.Health.Status}}' $svc 2>/dev/null)" != "healthy" ]; do
        echo "Waiting for $svc..."
        sleep 5
    done
    echo "✓ $svc ready"
done

# Phase 2: Core services (MLflow, Ray)
echo "Starting core services..."
docker-compose up -d mlflow-server ray-head
sleep 30

# Phase 3: API services
echo "Starting API services..."
docker-compose up -d mlflow-api ray-compute-api
sleep 20

# Phase 4: Monitoring & extras
echo "Starting monitoring..."
docker-compose up -d prometheus grafana
```

**Result:** Consistent startup in ~90 seconds, 100% success rate.

### Startup Dependencies Map
```
Infrastructure Layer (0-10s):
  ├─ traefik (gateway)
  ├─ postgres (data)
  └─ redis (cache)

Core Services Layer (10-40s):
  ├─ mlflow-server (depends: postgres, redis)
  ├─ ray-head (depends: none, but heavy startup)
  └─ authentik-server (depends: postgres, redis)

API Layer (40-60s):
  ├─ mlflow-api (depends: mlflow-server)
  ├─ ray-compute-api (depends: ray-head)
  └─ authentik-worker (depends: authentik-server)

Monitoring Layer (60-90s):
  ├─ prometheus (depends: all services)
  └─ grafana (depends: prometheus)
```

### Where This Is Documented
- **start_all_safe.sh**: Production-grade startup script with phasing
- **ray_compute/.github/copilot-instructions.md**: "Service Startup Best Practices" section

---

## 🧹 Critical Pattern #5: Orphaned Container Cleanup

### The Problem
```bash
# Manual Docker commands create orphans
docker run -d --name mlflow-api ...

# Later...
docker-compose up -d
# Error: container name "mlflow-api" already in use
```

**Result:** Docker Compose fails to start, requires manual cleanup.

### Why This Happens
- `docker run` creates containers outside compose management
- `docker-compose` doesn't know about manually created containers
- Container names conflict with compose service names
- `docker-compose down` doesn't remove orphaned containers

### The Solution
```bash
# ✅ Add cleanup to startup script
#!/bin/bash

echo "Cleaning up orphaned containers..."
docker-compose down --remove-orphans

# Find manually created containers matching service names
ORPHANED=$(docker ps -a --format '{{.Names}}' | grep -E 'mlflow-|ray-|authentik-')

if [ ! -z "$ORPHANED" ]; then
    echo "Found orphaned containers:"
    echo "$ORPHANED"
    
    echo "$ORPHANED" | while read container; do
        echo "Removing $container..."
        docker rm -f "$container" 2>/dev/null || true
    done
fi

# Now safe to start
docker-compose up -d
```

### Prevention
```bash
# ❌ NEVER do this for services managed by compose:
docker run -d --name mlflow-api ...

# ✅ ALWAYS use compose:
docker-compose up -d mlflow-api

# ✅ For debugging, use non-conflicting names:
docker run -d --name debug-mlflow-api ...
```

### Where This Is Documented
- **start_all_safe.sh**: Lines 1-30 (cleanup logic)
- **ray_compute/.github/copilot-instructions.md**: "Service Startup Best Practices" section

---

## 📋 Quick Reference Checklist

### Before Adding New API Routes
- [ ] Is the route under `/api/*`? → Set priority to 2147483647
- [ ] Added inline comment in docker-compose.yml explaining priority
- [ ] Tested route works: `curl http://localhost/api/<your-path>`
- [ ] Verified priority: `curl http://localhost:8090/api/http/routers | jq`

### Before Adding Ray Services
- [ ] Calculated memory needs: object_store + shm + overhead
- [ ] Container memory limit exceeds total allocation by 1GB
- [ ] `--num-cpus` matches available system threads (use 1/3 to 1/2 of total)
- [ ] Added inline comments explaining calculations
- [ ] Tested startup: `docker logs ray-head | grep "Ray runtime started"`

### Before Adding Health Checks
- [ ] Health endpoint has NO database queries
- [ ] Health endpoint has NO external API calls
- [ ] Response time < 100ms
- [ ] Created separate `/ready` endpoint for expensive checks
- [ ] Tested performance: `curl -w "%{time_total}\n" http://localhost/health`

### Before Service Deployment
- [ ] Using `start_all_safe.sh` (not `docker-compose up -d`)
- [ ] Startup script has orphan cleanup
- [ ] Startup script has phased deployment
- [ ] Startup script verifies health checks
- [ ] Tested full cold start (all containers stopped)

---

## 🔗 Related Documentation

### Implementation Details
- **STARTUP_ANALYSIS.md**: Root cause analysis of all issues
- **STARTUP_SUCCESS.md**: Resolution verification and testing results
- **TROUBLESHOOTING.md**: "Traefik API Routes Return 404" section

### Best Practices
- **mlflow-server/.github/copilot-instructions.md**: 
  - "Traefik Routing & Priority Configuration"
  - Docker & Service Management patterns
  
- **ray_compute/.github/copilot-instructions.md**:
  - "Ray Head Resource Allocation"
  - "Service Startup Best Practices"

### Configuration
- **docker-compose.yml**: Lines 318-325 (Traefik priority), Lines 488-523 (Ray resources)
- **start_all_safe.sh**: Production startup script with all patterns

---

## 💡 Key Takeaways

1. **Traefik Priority Matters**: Always use max int32 (2147483647) for `/api/*` routes
2. **Memory Math Is Critical**: Container limits must exceed all allocated resources
3. **Health Checks Must Be Fast**: No database queries, aim for < 100ms
4. **Startup Order Matters**: Infrastructure → Core → APIs → Monitoring
5. **Clean Up Orphans**: Always use `--remove-orphans` and check for manual containers
6. **Document In-Line**: Future you (or teammates) will thank you
7. **Test Cold Starts**: Stop everything and start fresh to catch issues

---

**Next Steps:**
- Review copilot instructions before making infrastructure changes
- Use `start_all_safe.sh` for all deployments
- Add inline comments when modifying docker-compose.yml
- Test with cold starts after configuration changes
- Update this document when discovering new patterns

**Questions?** See TROUBLESHOOTING.md or copilot instructions for detailed guidance.
