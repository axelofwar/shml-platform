# Docker Compose ContainerConfig Bug Fix

## Problem
Docker Compose 1.29.2 has a known bug that causes `KeyError: 'ContainerConfig'` when trying to recreate containers with existing volumes/networks.

## Symptoms
```
KeyError: 'ContainerConfig'
  File "/usr/lib/python3/dist-packages/compose/service.py", line 1579
```

## Root Cause
Docker Compose 1.29.2 fails to properly parse container metadata when containers have been stopped/removed but their volumes/networks remain.

## Solutions

### Option 1: Complete Stack Restart (Recommended)
```bash
cd mlflow-server
docker-compose down --remove-orphans
docker-compose up -d
```

This cleanly removes all containers and networks, then recreates everything fresh.

### Option 2: Clean Orphaned Containers
```bash
# Remove stopped/orphaned containers
docker ps -a | grep -E "Exited|Created" | awk '{print $1}' | xargs -r docker rm

# Then try docker-compose
docker-compose up -d
```

### Option 3: Manual Container Management
```bash
# Stop and remove specific container
docker stop mlflow-server
docker rm mlflow-server

# Recreate with docker-compose
docker-compose up -d mlflow
```

### Option 4: Nuclear Option (Last Resort)
```bash
# WARNING: This removes ALL containers, not just MLflow
docker stop $(docker ps -aq)
docker rm $(docker ps -aq)

cd mlflow-server
docker-compose up -d
```

## Prevention

1. **Always use `docker-compose down`** before making infrastructure changes
2. **Don't manually remove containers** while docker-compose is managing them
3. **Upgrade Docker Compose** to v2.x (recommended)
   ```bash
   # Install Docker Compose v2
   sudo apt-get update
   sudo apt-get install docker-compose-plugin
   
   # Use with: docker compose (not docker-compose)
   ```

## When to Use Each Approach

- **After code changes**: `docker-compose build && docker-compose up -d`
- **After config changes**: `docker-compose down && docker-compose up -d`
- **Service is unhealthy**: `docker-compose restart <service>`
- **Hitting ContainerConfig bug**: Use Option 1 (complete restart)
- **Need to preserve data**: Backup first, then Option 1

## Quick Reference

### Safe Restart (Preserves Data)
```bash
cd /home/axelofwar/Desktop/Projects/mlflow-server
docker-compose down --remove-orphans
docker-compose up -d
```

### Check Status
```bash
docker-compose ps
docker-compose logs -f mlflow
```

### View All MLflow Containers
```bash
docker ps -a | grep mlflow
```
