# QUICK REFERENCE CARD - ML Platform Resource Management

## 🚨 CRITICAL ACTIONS (Do First)

### 1. Test Resource Manager (Safe - No Changes)
```bash
cd /home/axelofwar/Desktop/Projects/ml-platform
./test_resource_manager.sh
```

### 2. Apply Resource Manager (Interactive)
```bash
cd /home/axelofwar/Desktop/Projects/ml-platform
./start_all_safe.sh
# Review the allocation plan
# Type 'y' to confirm and apply
```

## 📊 System Health Checks

### Quick Status Check
```bash
# Service status
docker-compose ps

# Resource usage
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"

# System resources
free -h && echo "---" && df -h /
```

### Watch System (Real-time)
```bash
# Container stats (updates every 2 seconds)
watch -n 2 'docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"'

# System monitor
htop
```

## 🔧 Common Commands

### Start/Stop Services
```bash
# Safe start with resource checks
./start_all_safe.sh

# Normal start
docker-compose up -d

# Stop all services
docker-compose down

# Restart specific service
docker-compose restart mlflow-server
```

### View Logs
```bash
# All services
docker-compose logs -f --tail=50

# Specific service
docker-compose logs -f mlflow-server

# Last 100 lines
docker-compose logs --tail=100
```

### Check Service Health
```bash
# MLflow
curl -f http://localhost/mlflow/ || echo "MLflow FAIL"

# Ray
curl -f http://localhost/ray/ || echo "Ray FAIL"

# Traefik
curl -f http://localhost:8090/ping || echo "Traefik FAIL"
```

## 📈 Monitoring URLs

| Service | URL | Purpose |
|---------|-----|---------|
| MLflow UI | http://localhost/mlflow/ | Experiment tracking |
| Ray Dashboard | http://localhost/ray/ | Job monitoring |
| Traefik Dashboard | http://localhost:8090 | Gateway status |
| MLflow Grafana | http://localhost/mlflow-grafana | MLflow metrics |
| Ray Grafana | http://localhost/ray-grafana | Ray metrics |

## 🚑 Emergency Procedures

### Services Won't Start
```bash
# 1. Stop everything
docker-compose down

# 2. Check resources
free -h
df -h

# 3. Restart safely
./start_all_safe.sh
```

### System Unresponsive
```bash
# Emergency stop
docker stop $(docker ps -q)

# Clear unused resources (WARNING: removes data)
docker system prune -f

# Restart
./start_all_safe.sh
```

### High Memory Usage
```bash
# Check swap
free -h | grep Swap

# If swap > 10%, reduce services or add RAM
# Restart with resource manager to optimize
./start_all_safe.sh
```

## ⚠️ Warning Signs

| Issue | Threshold | Action |
|-------|-----------|--------|
| Swap usage | > 10% | Run resource manager |
| Memory usage | > 85% | Reduce services or add RAM |
| CPU usage | > 90% sustained | Check for runaway processes |
| Disk space | < 10GB | Clean up artifacts/logs |
| Health check timeouts | Any | Resource contention - run manager |

## 📝 What Changed

### ✅ Completed
1. **uv Package Manager** - 10-20x faster builds
2. **Resource Manager** - Dynamic allocation based on capacity
3. **Safe Startup Script** - Prevents over-allocation
4. **Documentation** - Comprehensive guides created

### 📂 New Files
- `scripts/resource_manager.py` - Resource allocation tool
- `start_all_safe.sh` - Safe startup script
- `test_resource_manager.sh` - Test script
- `RESOURCE_MANAGEMENT_GUIDE.md` - Comprehensive guide
- `MLFLOW_BEST_PRACTICES.md` - MLflow optimization guide
- `IMPLEMENTATION_SUMMARY.md` - Complete summary
- `QUICK_REFERENCE.md` - This card

## 🎯 Current System Stats

**Your System:**
- 24 CPU cores
- 16GB RAM
- ~1.4GB swap used (35% - needs attention)
- 19 running containers

**Problem Identified:**
- Previous allocation: 47.62 CPU cores (197% over-subscription)
- Health check timeouts due to resource contention
- No host system reserve

**Solution:**
- Resource manager allocates 80% of capacity (19.2 CPUs, 12.8GB RAM)
- Priority-based distribution
- 20% host reserve for stability

## 🔍 Troubleshooting Quick Links

### Services
```bash
# MLflow not accessible
docker-compose logs mlflow-server mlflow-nginx

# Ray not working
docker-compose logs ray-head ray-compute-api

# Database issues
docker-compose logs mlflow-postgres ray-postgres

# Network issues
docker-compose logs traefik
```

### Performance
```bash
# Container resource usage
docker stats --no-stream

# System load
uptime
htop

# Disk I/O
iostat -x 1

# Network
docker network inspect ml-platform
```

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| `IMPLEMENTATION_SUMMARY.md` | Complete overview of changes |
| `RESOURCE_MANAGEMENT_GUIDE.md` | Crash prevention & monitoring |
| `MLFLOW_BEST_PRACTICES.md` | MLflow optimization guide |
| `QUICK_REFERENCE.md` | This card |
| `README.md` | Platform overview |
| `ARCHITECTURE.md` | System architecture |
| `TROUBLESHOOTING.md` | Common issues |

## 💡 Pro Tips

### Prevent Issues
1. Run `./start_all_safe.sh` instead of `docker-compose up -d`
2. Check swap usage regularly: `free -h | grep Swap`
3. Monitor Grafana dashboards for trends
4. Keep disk space above 20GB for artifacts

### Optimize Performance
1. Limit concurrent Ray jobs to 2-3
2. Archive old MLflow experiments
3. Run `docker system prune` monthly (carefully)
4. Monitor database size growth

### Stay Informed
1. Check logs daily: `docker-compose logs --tail=50`
2. Review Grafana weekly for trends
3. Test backups monthly
4. Update documentation when changing config

## ❓ Questions to Answer

Before implementing MLflow best practices:

1. **External Access**: Domain name for --allowed-hosts?
2. **Model Sources**: Restrict to MLflow artifacts only?
3. **TLS/HTTPS**: Domain for Let's Encrypt or self-signed?
4. **Backups**: Off-site backup location (S3/NAS)?
5. **Auth**: Need API keys or additional permissions?

## 🎬 Next Steps

### Immediate (Today)
1. ✅ Run `./test_resource_manager.sh` to see allocation plan
2. ⏳ Run `./start_all_safe.sh` to apply changes
3. ⏳ Monitor for 1 hour to ensure stability

### This Week
1. Monitor system for 24 hours
2. Answer questions above for MLflow Phase 1
3. Review Grafana dashboards
4. Test backup/restore procedures

### Next Week
1. Implement MLflow security middleware
2. Configure database performance tuning
3. Set up alerting for resource thresholds

---

**Created**: November 23, 2025  
**Platform**: ML Platform v2.0  
**Resource Manager**: v1.0
