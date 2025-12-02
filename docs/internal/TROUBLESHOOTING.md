# Troubleshooting Guide

**Last Updated:** 2025-11-22

---

## Quick Diagnostics

```bash
# Check all services
docker ps

# Check network
docker network inspect ml-platform

# Check logs
docker logs <container> --tail 50

# Health checks
curl http://localhost/mlflow/ | grep MLflow
curl http://localhost:8090/ping  # Traefik
```

---

## MLflow Issues

### Container Won't Start

**Symptoms:**
- `docker compose up -d` fails
- Containers exit immediately
- Port conflict errors

**Fix:**
```bash
# Check ports
sudo netstat -tulpn | grep -E ':(80|5000|5432)'

# Stop conflicts
sudo systemctl stop nginx apache2 postgresql

# Clean restart
cd mlflow-server
docker compose down
docker compose up -d
```

### Database Connection Failed

**Symptoms:**
- "connection refused"
- "authentication failed"
- UI shows database error

**Fix:**
```bash
# Check PostgreSQL
docker exec mlflow-postgres pg_isready

# Verify password
cat ml-platform/mlflow-server/secrets/db_password.txt

# Check logs
docker logs mlflow-postgres --tail 50

# Test connection
PGPASSWORD=$(cat ml-platform/mlflow-server/secrets/db_password.txt) \
  psql -h localhost -U mlflow -d mlflow_db -c '\dt'

# Restart if needed
docker restart mlflow-postgres mlflow-server
```

### Can't Access UI

**Symptoms:**
- Browser: "connection refused"
- Timeout errors
- 502/504 errors

**Fix:**
```bash
# Check Traefik
docker logs traefik --tail 50
curl http://localhost:8090/ping

# Check MLflow containers
docker ps --filter "name=mlflow"

# Check routing
curl -v http://localhost/mlflow/

# Check firewall
sudo ufw status | grep 80

# Restart chain
docker restart traefik mlflow-nginx mlflow-server
```

### Large Upload Fails

**Symptoms:**
- 413 Request Entity Too Large
- 504 Gateway Timeout
- Upload hangs

**Fix:**
```bash
# Check Nginx config
docker exec mlflow-nginx grep client_max_body_size /etc/nginx/conf.d/mlflow.conf

# Increase limits (ml-platform/mlflow-server/docker-compose.yml):
# nginx:
#   environment:
#     CLIENT_MAX_BODY_SIZE: 5G
#     PROXY_TIMEOUT: 3600

# Rebuild
cd mlflow-server
docker compose up -d --build nginx
```

### Experiments Not Showing

**Symptoms:**
- Empty UI
- 0 experiments listed
- Old data missing

**Fix:**
```bash
# Check database
docker exec mlflow-postgres psql -U mlflow -d mlflow_db \
  -c "SELECT COUNT(*) FROM experiments;"

# Check MLflow connection
docker logs mlflow-server --tail 50 | grep -i error

# Clear browser cache
# Ctrl+Shift+R in browser

# Restart
docker restart mlflow-server
```

---

## Ray Compute Issues

### Ray Services Not Starting

**Symptoms:**
- Containers exit
- "no such network" error
- Ray dashboard unreachable

**Fix:**
```bash
# Check network exists
docker network inspect ml-platform

# Create if missing
docker network create ml-platform \
  --driver bridge \
  --subnet 172.30.0.0/16

# Start Ray
cd ray_compute
docker compose -f docker-compose.ray.yml up -d

# Check logs
docker logs ray-head --tail 50
```

### GPU Not Available

**Symptoms:**
- "no GPU found"
- CUDA errors
- nvidia-smi fails in container

**Fix:**
```bash
# Check host GPU
nvidia-smi

# Check nvidia-container-toolkit
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi

# Install if missing
sudo apt install -y nvidia-container-toolkit
sudo systemctl restart docker

# Check Ray config (docker-compose.ray.yml):
# ray-head:
#   deploy:
#     resources:
#       reservations:
#         devices:
#           - driver: nvidia
#             count: all
#             capabilities: [gpu]
```

### OAuth Login Failed

**Symptoms:**
- Redirect loop
- "invalid client" error
- Token exchange fails

**Fix:**
```bash
# Check FusionAuth logs
docker logs fusionauth --tail 50

# Verify OAuth application in FusionAuth admin
# URL: http://localhost:9011/admin/ or https://sfml-platform.tail38b60a.ts.net/auth/admin/
# Navigate to Applications > Ray Compute > OAuth tab

# Check environment (.env):
# FUSIONAUTH_RAY_CLIENT_ID=<client-id>
# FUSIONAUTH_RAY_CLIENT_SECRET=<secret>
# NEXTAUTH_URL=http://${TAILSCALE_IP}:3002

# Restart
docker restart fusionauth ray-compute-ui
```

### API 500 Errors

**Symptoms:**
- Internal server error
- API returns 500
- Logs show Python exceptions

**Fix:**
```bash
# Check API logs
docker logs ray-compute-api --tail 100

# Check database connection
docker exec ray-compute-api python -c "
from sqlalchemy import create_engine
engine = create_engine('postgresql://ray_compute:password@ray-compute-db:5432/ray_compute')
with engine.connect() as conn:
    print('Connected')
"

# Check Ray connection
docker exec ray-compute-api curl http://ray-head:8265/api/version

# Restart
docker restart ray-compute-api
```

---

## Network Issues

### Traefik API Routes Return 404 (CRITICAL)

**Symptoms:**
- Custom API routes like `/api/v1/health` return 404
- Traefik dashboard API responds instead of application
- Direct container access works: `curl http://<container-ip>:8000/health` succeeds
- Traefik proxy fails: `curl http://localhost/api/v1/health` returns 404

**Root Cause:**
Traefik's internal API dashboard uses `PathPrefix(/api)` with ultra-high priority (2147483646), intercepting all `/api/*` requests unless application routers have higher priority.

**Diagnosis:**
```bash
# Check router priorities
curl -s http://localhost:8090/api/http/routers | jq '.[] | select(.name | contains("api")) | {name, rule, priority}'

# Should show:
# {
#   "name": "api@internal",
#   "rule": "PathPrefix(`/api`)",
#   "priority": 2147483646        # Traefik internal API
# }
# {
#   "name": "mlflow-api-v1@docker",
#   "rule": "PathPrefix(`/api/v1`)",
#   "priority": 2147483647        # YOUR API (must be higher!)
# }

# Test direct container access
CONTAINER_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' mlflow-api)
curl http://$CONTAINER_IP:8000/health  # Should work

# Test through Traefik
curl http://localhost/api/v1/health    # 404 = priority issue
```

**Fix:**
Edit `docker-compose.yml` and set router priority to max int32 (2147483647):
```yaml
labels:
  - traefik.http.routers.mlflow-api-v1.rule=PathPrefix(`/api/v1`)
  - traefik.http.routers.mlflow-api-v1.priority=2147483647  # Max int32 - MUST exceed 2147483646
  - traefik.http.routers.mlflow-api-v1.service=mlflow-api-service
```

Apply changes:
```bash
docker-compose up -d --force-recreate mlflow-api
# Wait 10 seconds for router registration
curl http://localhost/api/v1/health  # Should now work
```

**Why Priority Matters:**
- Traefik evaluates routes by priority (highest first)
- Internal API (`api@internal`): priority 2147483646
- If your API has lower priority (e.g., 500), Traefik internal API wins
- Use max int32 (2147483647) to guarantee precedence

**Access Points After Fix:**
- Application API: http://localhost/api/v1/* (priority 2147483647)
- Traefik Dashboard API: http://localhost:8090/api/* (internal access only)
- Traefik Dashboard UI: http://localhost:8090/ (internal access only)

**Reference:** See copilot instructions for comprehensive Traefik routing best practices.

---

### Services Can't Communicate

**Symptoms:**
- "connection refused" between containers
- DNS resolution fails
- Ray can't reach MLflow

**Fix:**
```bash
# Check network
docker network inspect ml-platform | grep -A 5 "Containers"

# Test DNS
docker exec ray-compute-api nslookup mlflow-nginx
docker exec mlflow-server nslookup ray-head

# Test connectivity
docker exec ray-compute-api ping -c 2 mlflow-nginx
docker exec ray-compute-api curl http://mlflow-nginx:80/health

# Reconnect containers
docker network disconnect ml-platform ray-compute-api
docker network connect ml-platform ray-compute-api

# Or restart all
docker compose down
docker compose up -d
```

### External Access Blocked

**Symptoms:**
- Can't access from LAN
- Tailscale doesn't work
- Firewall blocking

**Fix:**
```bash
# Check firewall
sudo ufw status

# Open ports
sudo ufw allow 80/tcp comment "Traefik Gateway"
sudo ufw allow 8090/tcp comment "Traefik Dashboard"

# Check Tailscale
tailscale status
tailscale ip -4

# Test local first
curl http://localhost/mlflow/

# Test LAN
curl http://localhost/mlflow/

# Test VPN
curl http://${TAILSCALE_IP}/mlflow/

# Check Traefik logs
docker logs traefik --tail 50 | grep -i error
```

### Traefik 404 Errors

**Symptoms:**
- 404 Not Found
- "Backend not found"
- Routes not working

**Fix:**
```bash
# Check routers
curl http://localhost:8090/api/http/routers | jq

# Check services
curl http://localhost:8090/api/http/services | jq

# Verify labels (docker inspect)
docker inspect mlflow-nginx | grep -A 20 Labels

# Expected labels:
# traefik.http.routers.mlflow.rule=PathPrefix(`/mlflow`)
# traefik.http.routers.mlflow.priority=100

# Restart Traefik
docker restart traefik
```

---

## Performance Issues

### Slow Response Times

**Symptoms:**
- Long page load
- API timeouts
- High CPU/memory

**Fix:**
```bash
# Check resources
docker stats

# Check logs for errors
docker logs mlflow-server --tail 100 | grep -i error
docker logs ray-head --tail 100 | grep -i error

# Check database size
docker exec mlflow-postgres psql -U mlflow -d mlflow_db \
  -c "SELECT pg_size_pretty(pg_database_size('mlflow_db'));"

# Check disk space
df -h

# Cleanup old data
docker exec mlflow-postgres psql -U mlflow -d mlflow_db \
  -c "DELETE FROM runs WHERE start_time < NOW() - INTERVAL '90 days';"

# Restart services
docker restart mlflow-server mlflow-postgres
```

### High Memory Usage

**Symptoms:**
- Out of memory errors
- OOMKilled containers
- System freezes

**Fix:**
```bash
# Check memory
free -h
docker stats --no-stream

# Add memory limits (docker-compose.yml):
# mlflow-server:
#   deploy:
#     resources:
#       limits:
#         memory: 2G
#       reservations:
#         memory: 1G

# Restart with limits
docker compose up -d
```

### Disk Space Full

**Symptoms:**
- "no space left on device"
- Backup failures
- Artifact upload fails

**Fix:**
```bash
# Check usage
df -h
du -sh ml-platform/mlflow-server/data/*
du -sh ml-platform/ray_compute/data/*

# Clean Docker
docker system prune -a --volumes -f

# Remove old backups
find ml-platform/mlflow-server/backups -mtime +90 -delete

# Move artifacts to larger disk
mv ml-platform/mlflow-server/data /mnt/storage/mlflow-data
ln -s /mnt/storage/mlflow-data ml-platform/mlflow-server/data
```

---

## Tailscale VPN Issues

### Connection Refused

**Symptoms:**
- Can't reach Tailscale IP
- Timeout errors
- VPN disconnected

**Fix:**
```bash
# Check Tailscale status
tailscale status

# Check IP
tailscale ip -4

# Restart Tailscale
sudo systemctl restart tailscaled

# Reconnect
sudo tailscale up

# Enable on boot
sudo systemctl enable tailscaled

# Test connectivity
ping -c 4 $(tailscale ip -4)
curl http://$(tailscale ip -4)/mlflow/
```

### IP Changed

**Symptoms:**
- Old IP doesn't work
- Clients can't connect
- Documentation shows old IP

**Fix:**
```bash
# Get current IP
tailscale ip -4

# Update .env files
cd mlflow-server
sed -i 's/100\.78\.129\.124/<NEW_IP>/g' docker-compose.yml

cd ../ray_compute
sed -i 's/100\.78\.129\.124/<NEW_IP>/g' .env docker-compose.*.yml

# Restart services
docker compose down
docker compose up -d
```

---

## Data Issues

### Lost Data After Restart

**Symptoms:**
- Experiments gone
- Models missing
- Database empty

**Fix:**
```bash
# Check volumes
docker volume ls | grep mlflow

# Check data directory
ls -lh ml-platform/mlflow-server/data/

# Restore from backup
docker compose down
cp -r ml-platform/mlflow-server/data.backup.* ml-platform/mlflow-server/data
docker compose up -d

# Or restore database only
cd ml-platform/mlflow-server/backups/postgres
gunzip -c mlflow_backup_20251122.sql.gz | \
  docker exec -i mlflow-postgres psql -U mlflow -d mlflow_db
```

### Backup Failed

**Symptoms:**
- Cron job errors
- Empty backup files
- Disk full

**Fix:**
```bash
# Check backup logs
docker logs mlflow-backup --tail 50

# Check backup directory
ls -lh ml-platform/mlflow-server/backups/postgres/

# Manual backup
docker exec mlflow-postgres pg_dump -U mlflow mlflow_db | \
  gzip > ml-platform/mlflow-server/backups/postgres/manual_$(date +%Y%m%d).sql.gz

# Check cron (if using)
docker exec mlflow-backup crontab -l

# Fix permissions
sudo chown -R $USER:$USER ml-platform/mlflow-server/backups/
```

---

## After Reboot

### Services Don't Auto-Start

**Symptoms:**
- Nothing running after boot
- Have to manually start
- systemd not configured

**Fix:**
```bash
# Option 1: Docker restart policy (already set)
# Check compose files have:
# restart: unless-stopped

# Option 2: Systemd service
sudo nano /etc/systemd/system/ml-platform.service
# Paste contents (see SYSTEMD_SERVICE.md)

sudo systemctl daemon-reload
sudo systemctl enable ml-platform.service
sudo systemctl start ml-platform.service

# Check status
sudo systemctl status ml-platform.service
```

### Volumes Not Mounting

**Symptoms:**
- Data missing
- Permission errors
- Empty directories

**Fix:**
```bash
# Check permissions
ls -ld ml-platform/mlflow-server/data ml-platform/ray_compute/data

# Fix ownership
sudo chown -R $USER:$USER ml-platform/mlflow-server/data
sudo chown -R $USER:$USER ml-platform/ray_compute/data

# Restart
docker compose down
docker compose up -d
```

---

## Monitoring Issues

### Grafana Login Failed

**Symptoms:**
- Wrong password
- Can't access dashboards
- Reset needed

**Fix:**
```bash
# MLflow Grafana
docker exec mlflow-grafana grafana-cli admin reset-admin-password admin

# Ray Grafana
docker exec ray-grafana grafana-cli admin reset-admin-password admin

# Or check secrets
cat ml-platform/mlflow-server/secrets/grafana_password.txt
grep GRAFANA_ADMIN_PASSWORD ml-platform/ray_compute/.env
```

### Prometheus Not Scraping

**Symptoms:**
- No metrics
- Empty graphs
- Targets down

**Fix:**
```bash
# Check targets
curl http://localhost:9090/api/v1/targets | jq

# Check Prometheus config
docker exec mlflow-prometheus cat /etc/prometheus/prometheus.yml

# Check services exposing metrics
curl http://mlflow-server:5000/metrics
curl http://ray-head:8265/metrics

# Restart
docker restart mlflow-prometheus
```

---

## Emergency Procedures

### Complete System Reset

```bash
# DANGER: This deletes all data!

# Stop all
cd /home/axelofwar/Desktop/Projects
./stop_all.sh

# Remove data (BACKUP FIRST!)
rm -rf ml-platform/mlflow-server/data/*
rm -rf ml-platform/ray_compute/data/*

# Remove secrets (will regenerate)
rm ml-platform/mlflow-server/secrets/*
rm ml-platform/ray_compute/.env

# Recreate network
docker network rm ml-platform
docker network create ml-platform --driver bridge --subnet 172.30.0.0/16

# Start fresh
./start_all.sh
```

### Recover from Backup

```bash
# Stop services
docker compose down

# Restore MLflow data
cd mlflow-server
cp -r data.backup.20251122/* data/

# Restore database
gunzip -c backups/postgres/latest.sql.gz | \
  docker exec -i mlflow-postgres psql -U mlflow -d mlflow_db

# Start
docker compose up -d
```

---

## Getting Help

### Collect Debug Info

```bash
# Create debug report
cat > debug_report.txt << 'EOF'
=== SYSTEM INFO ===
$(uname -a)
$(docker --version)
$(docker compose version)

=== CONTAINERS ===
$(docker ps -a)

=== NETWORKS ===
$(docker network inspect ml-platform)

=== LOGS (last 50 lines each) ===
=== MLflow ===
$(docker logs mlflow-server --tail 50)

=== Traefik ===
$(docker logs traefik --tail 50)

=== Ray ===
$(docker logs ray-head --tail 50 2>/dev/null || echo "Not running")

=== DISK ===
$(df -h)

=== MEMORY ===
$(free -h)
EOF

# Share debug_report.txt for support
```

### Check Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [API_REFERENCE.md](API_REFERENCE.md) - API details
- [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) - Service communication
- [CURRENT_DEPLOYMENT.md](CURRENT_DEPLOYMENT.md) - What's running
- ml-platform/mlflow-server/README.md - MLflow specifics
- ml-platform/ray_compute/README.md - Ray specifics

---

**Last Resort:** See archived/IMPLEMENTATION_CHECKLIST.md for full rebuild

**Updated:** 2025-11-22
