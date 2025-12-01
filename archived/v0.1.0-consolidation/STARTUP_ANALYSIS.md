# ML Platform Startup Analysis & Resolution

**Date:** November 23, 2025
**Issue:** Services hanging on startup or failing to start due to resource allocation and dependency issues

## Root Causes Identified

### 1. **Ray Head Memory Allocation Issue** (CRITICAL)
```
ValueError: After taking into account object store and redis memory usage,
the amount of memory on this node available for tasks and actors (-2.42 GB)
is less than -112% of total.
```

**Problem:** Ray head configured with:
- `--num-cpus=8 --num-gpus=1 --object-store-memory=4000000000`
- Docker limit: 2GB memory (from resource manager)
- Trying to allocate 4GB object store + overhead in 2GB container

**Solution:** Reduce Ray object store memory to match container limits

### 2. **MLflow Backup Service Failing** (NON-CRITICAL)
```
cat: can't open '/run/secrets/db_password': No such file or directory
```

**Problem:** MLflow backup service expects Docker secrets but can't access them
**Impact:** Continuously restarting, not blocking critical services
**Solution:** Fix secrets mount or disable backup temporarily

### 3. **Dependency Chain Blocking Startup**
```
ERROR: for authentik-worker  Container "b882a9abb823" is unhealthy.
ERROR: for authentik-server  Container "b882a9abb823" is unhealthy.
ERROR: for mlflow-server  Container "1fd755304a03" is unhealthy.
ERROR: for ray-compute-api  Container "f38cc3c277f9" is unhealthy.
```

**Problem:** Services with `depends_on` + `condition: service_healthy` wait indefinitely
**Chain:**
- mlflow-nginx → mlflow-server (never starts, waits for healthy status)
- mlflow-api → mlflow-server (never starts)
- ray-compute-api → ray-head (unhealthy due to memory issue)
- authentik-server → authentik-postgres (healthy)
- authentik-worker → authentik-server (never starts)

### 4. **Resource Manager Not Being Used**
`start_all_safe.sh` checks for resource_manager.py but doesn't actually run it before `docker-compose up`.

## Service Startup Status

### ✅ Successfully Started:
- ml-platform-traefik (healthy)
- ml-platform-redis (healthy)
- mlflow-postgres (healthy)
- authentik-postgres (healthy)
- authentik-redis (healthy)
- ray-compute-db (healthy)
- mlflow-prometheus, mlflow-grafana, ray-prometheus, ray-grafana
- node-exporter, cadvisor
- mlflow-adminer

### ❌ Failed / Not Started:
- **ray-head** - Memory allocation error (CRITICAL - blocks ray-compute-api)
- **mlflow-server** - Never created (blocked by postgres being "unhealthy"? needs investigation)
- **mlflow-nginx** - Depends on mlflow-server
- **mlflow-api** - Depends on mlflow-server  
- **ray-compute-api** - Depends on ray-head
- **authentik-server** - Not started (needs investigation)
- **authentik-worker** - Depends on authentik-server

### 🔄 Restarting:
- **mlflow-backup** - Secrets configuration issue (non-critical)

## Hardware Configuration Summary

**CPU:** AMD Ryzen 9 3900X (12-Core, 24 threads)
**RAM:** 15GB total, ~8.8GB available
**GPU:** NVIDIA RTX 2070 (8GB VRAM)
**Motherboard:** ASUS ROG CROSSHAIR VIII HERO (WI-FI)
- Max RAM: 128GB (4 slots)
- Current: 1x 16GB DDR4-2400 in DIMM_A2
- Empty slots: DIMM_A1, DIMM_B1, DIMM_B2

## Fixes Required

### Fix 1: Reduce Ray Head Memory Allocation
```yaml
# docker-compose.yml - ray-head service
command: >
  ray start --head
  --port=6379
  --dashboard-host=0.0.0.0
  --dashboard-port=8265
  --num-cpus=4                      # Reduced from 8
  --num-gpus=1
  --object-store-memory=1000000000  # Reduced from 4GB to 1GB
  --block
```

### Fix 2: Increase Ray Head Container Memory
```yaml
deploy:
  resources:
    limits:
      cpus: '4.0'      # Increased from 2.0
      memory: 4G       # Increased from 2G
    reservations:
      cpus: '1.0'
      memory: 2G
```

### Fix 3: Fix/Disable MLflow Backup Temporarily
Option A: Fix secrets (if they exist)
Option B: Comment out mlflow-backup service until secrets are properly configured

### Fix 4: Improve start_all_safe.sh
- Actually run resource_manager.py in non-interactive mode
- Add health check polling with timeout
- Show progress of service startup
- Detect and report failures early

### Fix 5: Add Service Startup Phases
Start services in order:
1. Phase 1: Infrastructure (traefik, redis, postgres services)
2. Phase 2: Core services (mlflow-server, ray-head, authentik-server)
3. Phase 3: API services (mlflow-api, ray-compute-api, authentik-worker)
4. Phase 4: Monitoring & extras (grafana, prometheus, backup)

## Hardware Upgrade Recommendations

### RAM Upgrade (HIGHEST PRIORITY)
**Current:** 16GB DDR4-2400 (1x16GB in single-channel)
**Recommended:** 64GB DDR4-3200/3600 (2x32GB or 4x16GB)

**Why:**
- Running 15+ containers + Ray compute + MLflow
- Single-channel RAM = 50% memory bandwidth loss
- Ray needs 4GB+ object store for ML workloads
- Current allocation leaves no headroom

**Compatible RAM:**
- G.SKILL Trident Z Neo (optimized for AMD Ryzen)
- Corsair Vengeance LPX DDR4-3600
- Must be DDR4, tested with Ryzen 3000 series
- Use matching pairs for dual-channel (2x32GB recommended)

**Cost:** ~$120-180 for 64GB kit

### CPU Upgrade (MEDIUM PRIORITY)
**Current:** Ryzen 9 3900X (12C/24T, Zen 2, 2019)
**Recommended:** Ryzen 9 5900X or 5950X (if staying AM4)

**Why:**
- 19% IPC improvement (Zen 3)
- Better single-thread performance for Ray scheduling
- Same TDP, drop-in replacement (BIOS update needed)

**Alternatives:**
- Keep 3900X (still excellent for this workload)
- Future: Upgrade to AM5 platform (Ryzen 7000/9000) - requires new motherboard + DDR5

**Cost:** $300-400 (5900X used) or $1500+ (new AM5 platform)

### GPU Addition (LOW PRIORITY - NOT RECOMMENDED)
**Current:** 1x RTX 2070 (8GB VRAM)
**Consideration:** Add 2nd GPU

**Compatibility Issues:**
- Motherboard has PCIe slots BUT:
  - Primary GPU: x16 slot (full speed)
  - Second GPU: x8 or x4 slot (reduced bandwidth)
  - Ryzen 3900X: 24 PCIe 4.0 lanes total (16 GPU + 4 chipset + 4 M.2)

**Problems:**
- Ray doesn't efficiently use multi-GPU without distributed setup
- Single 8GB GPU sufficient for most ML inference workloads
- Power supply may need upgrade (2x GPUs = 300-400W)
- Heat/cooling concerns in single chassis

**Better Alternative:**
- Upgrade to single RTX 4070 Ti (12GB VRAM, more efficient)
- Or wait for next-gen cards
- Or: Keep RTX 2070, spend budget on RAM

### Power Supply Check
- Verify current PSU wattage (need 650W+ for 2x GPUs)
- Check 8-pin PCIe power connectors available

## Recommended Action Plan

### Immediate (Today):
1. Fix Ray head memory configuration
2. Disable mlflow-backup temporarily  
3. Update start_all_safe.sh to be truly safe
4. Test full startup sequence

### Short-term (This Week):
1. Order RAM upgrade: 2x32GB DDR4-3600 CL16 kit (~$150)
2. Install RAM in DIMM_A2 + DIMM_B2 for dual-channel
3. Test with 64GB total
4. Re-run resource_manager.py to allocate more resources

### Medium-term (This Month):
1. Fix mlflow-backup secrets properly
2. Optimize container resource allocations
3. Add container auto-restart policies
4. Implement health check monitoring dashboard

### Long-term (Next Quarter):
1. Consider CPU upgrade to 5900X if workload increases
2. Monitor GPU utilization - upgrade if consistently >80%
3. Plan migration to dedicated servers if platform scales beyond single host

## Testing Protocol

After fixes:
```bash
# 1. Stop everything
cd /home/axelofwar/Desktop/Projects/ml-platform
docker-compose down --remove-orphans

# 2. Apply fixes to docker-compose.yml

# 3. Start with safe script
./start_all_safe.sh

# 4. Monitor startup
watch -n 2 'docker-compose ps'

# 5. Test routing
curl http://localhost/api/v1/health
curl http://localhost/mlflow/
curl http://localhost/ray/
```

## Success Criteria

All services should reach "Up (healthy)" status within:
- Infrastructure services: 30 seconds
- Database services: 60 seconds  
- Core services: 90 seconds
- API services: 120 seconds
- Total platform ready: < 3 minutes

## Notes

- Docker Compose v1.29.2 doesn't support `reservations.cpus` (warnings are normal)
- Traefik routing already configured correctly
- MLflow API performance fix already applied (97s → 8ms)
- Tailscale VPN working: axelofwar-dev-terminal-1.tail38b60a.ts.net
