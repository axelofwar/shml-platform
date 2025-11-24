# ML Platform
**MLflow Experiment Tracking + Ray Distributed Compute**

Production-ready ML platform with Traefik gateway, unified networking, GPU sharing.

---

## Quick Start

```bash
# Start all services
./start_all.sh

# Test all services
./test_all_services.sh          # Validates all services are running

# Access
http://localhost/mlflow/        # MLflow UI
http://localhost/ray/           # Ray Dashboard
http://localhost:8090           # Traefik Dashboard

# Credentials (all set to AiSolutions2350!)
# - MLflow Grafana: admin / AiSolutions2350!
# - Ray Grafana: admin / AiSolutions2350!
# - Authentik: akadmin / AiSolutions2350!

# Update passwords
./update_passwords.sh <new_password>

# Stop
./stop_all.sh
```

**Prerequisites:** Docker 24+, Docker Compose 2.20+

**Scripts:**
- `start_all.sh` - Start all services (MLflow + Ray + Traefik)
- `stop_all.sh` - Stop all services
- `restart_all.sh` - Restart all services
- `test_all_services.sh` - Comprehensive health check
- `update_passwords.sh` - Update all admin passwords

---

## 🏗️ Architecture

```
                    ┌─────────────────────┐
                    │  Traefik Gateway    │
                    │  (Port 80)          │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │   MLflow     │  │  Ray Compute │  │  Monitoring  │
    │   Stack      │  │   Stack      │  │   Stack      │
    │              │  │              │  │              │
    │ • Server     │  │ • Head Node  │  │ • Grafana    │
    │ • Nginx      │  │ • API Server │  │ • Prometheus │
    │ • PostgreSQL │  │ • PostgreSQL │  │              │
    └──────────────┘  └──────────────┘  └──────────────┘
              │                │                │
              └────────────────┼────────────────┘
                               ▼
                    ┌──────────────────┐
                    │ ml-platform      │
                    │ Docker Network   │
---

## Status

**MLflow:** ✅ Operational (8 containers)  
**Ray:** ⏸️ Infrastructure ready, app pending  
**Total:** 14 containers when fully deployed

---

## Documentation

**Core:**
- [ARCHITECTURE.md](ARCHITECTURE.md) - Tools, scaling, implementation
- [API_REFERENCE.md](API_REFERENCE.md) - OpenAPI specs
- [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) - MLflow+Ray integration
- [CURRENT_DEPLOYMENT.md](CURRENT_DEPLOYMENT.md) - What's running
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues
- [ACCESS_URLS.md](ACCESS_URLS.md) - Quick URL reference

**Stack-Specific:**
- [ml-platform/mlflow-server/README.md](ml-platform/mlflow-server/README.md) - MLflow guide
- [ml-platform/ray_compute/README.md](ml-platform/ray_compute/README.md) - Ray guide
- [ml-platform/mlflow-server/NEXT_STEPS.md](ml-platform/mlflow-server/NEXT_STEPS.md) - MLflow roadmap
- [ml-platform/ray_compute/NEXT_STEPS.md](ml-platform/ray_compute/NEXT_STEPS.md) - Ray roadmap

---

## Operations

```bash
# Unified
./start_all.sh
./stop_all.sh
./restart_all.sh

# MLflow only
cd mlflow-server
./start.sh
./stop.sh
./restart.sh

# Ray only (when deployed)
cd ray_compute
./start.sh
./stop.sh
./restart.sh

# Auto-start on boot
sudo cp ml-platform.service /etc/systemd/system/
sudo systemctl enable ml-platform.service
```

### Logs
```bash
docker logs -f mlflow-server         # MLflow logs
docker logs -f ray-compute-api       # Ray API logs
docker logs -f ml-platform-gateway   # Traefik logs
```

### Monitoring
```bash
open http://localhost:8090           # Traefik dashboard
open http://localhost/grafana        # Metrics
docker stats                         # Resource usage
```

---

## 🔧 Configuration

### Environment Variables
Edit `ml-platform/ray_compute/.env`:
```bash
# Database
POSTGRES_PASSWORD=your_secure_password

# API
API_SECRET_KEY=your_api_key
API_KEY_ENABLED=false  # Set true for production

# Network (use Docker service names!)
RAY_ADDRESS=http://ray-head:8265
MLFLOW_TRACKING_URI=http://mlflow-nginx:80
REDIS_HOST=ml-platform-redis
```

### Docker Compose Files
- `docker-compose.gateway.yml` - Traefik API Gateway
- `ml-platform/mlflow-server/docker-compose.unified.yml` - MLflow stack
- `ml-platform/ray_compute/docker-compose.unified.yml` - Ray stack

---

## 📊 Service Endpoints

| Service | Path | Description |
|---------|------|-------------|
| Traefik Dashboard | `http://localhost:8090` | Gateway status |
---

## License

MIT - See individual component licenses:
- MLflow: Apache 2.0
- Ray: Apache 2.0
- Traefik: MIT

**Updated:** 2025-11-22

**More:** See [`IMPLEMENTATION_CHECKLIST.md`](./IMPLEMENTATION_CHECKLIST.md) Troubleshooting section

---

## 📚 Documentation

### Start Here
1. 📘 **[Architecture Analysis](./ARCHITECTURE_ANALYSIS.md)** - Understand the design
2. 📋 **[Implementation Checklist](./IMPLEMENTATION_CHECKLIST.md)** - Deploy step-by-step
3. 📙 **[Quick Reference](./ML_PLATFORM_QUICK_REFERENCE.md)** - Daily operations

### Deep Dive
4. 📗 **[Deployment Guide](./ML_PLATFORM_DEPLOYMENT.md)** - Complete reference
5. 📝 **[Implementation Summary](./IMPLEMENTATION_SUMMARY.md)** - What changed

### Service-Specific
- [`ml-platform/mlflow-server/docs/`](./ml-platform/mlflow-server/docs/) - MLflow documentation
- [`ml-platform/ray_compute/README.md`](./ml-platform/ray_compute/README.md) - Ray Compute guide

---

## 🔐 Security

### Development (Current)
- ✅ Internal network isolation
- ✅ Docker secrets
- ⚠️ HTTP only
- ⚠️ API auth disabled

### Production Hardening
```bash
# Enable authentication
# In ml-platform/ray_compute/.env
API_KEY_ENABLED=true

# Add SSL certificates
# Edit docker-compose.gateway.yml

# Restrict dashboard
# Set api.insecure=false in Traefik config
```

---

## 📈 Performance

### Resource Usage
- **CPU:** 8+ cores recommended
- **RAM:** 16GB minimum, 32GB+ recommended
- **Storage:** 100GB+ for artifacts
- **GPU:** Optional, NVIDIA with CUDA 11.8+

### Scaling
```bash
# Add Ray workers (future)
docker compose -f ml-platform/ray_compute/docker-compose.unified.yml \
  up -d --scale ray-worker=3

# Add MLflow replicas (requires load balancer config)
```

---

## 🎓 Key Concepts

### Why Unified Network?
- Services find each other by name (DNS)
- No IP management needed
- Secure internal communication
- Easy to add new services

### Why Traefik?
- Single entry point
- Automatic service discovery
- Path-based routing
- Built-in load balancing

### Why GPU Sharing?
- Multiple services use GPU simultaneously
- Ray training + MLflow inference
- Better resource utilization
- No code changes needed

---

## 🤝 Contributing

This is a personal ML infrastructure project, but feedback welcome!

### Report Issues
1. Check [troubleshooting](#-troubleshooting) first
2. Review logs: `docker logs <container>`
3. Create detailed issue report

### Suggest Improvements
- Architecture enhancements
- Security hardening
- Performance optimizations
- Documentation improvements

---

## 📅 Version History

### v2.0 (November 22, 2025) - Current
- ✅ Unified network architecture
- ✅ Traefik API Gateway
- ✅ Shared Redis (single instance)
- ✅ GPU sharing (NVIDIA MPS)
- ✅ Service discovery via DNS
- ✅ Zero port conflicts
- ✅ Comprehensive documentation

### v1.0 (November 21, 2025)
- Initial separate deployments
- Isolated networks (communication failed)
- Multiple Redis instances (port conflicts)
- Direct port exposure
- Manual service discovery

**Migration:** Follow [`IMPLEMENTATION_CHECKLIST.md`](./IMPLEMENTATION_CHECKLIST.md)

---

## 📄 License

This project structure and documentation: MIT License  
Underlying services (MLflow, Ray, etc.): See respective licenses

---

## 🙏 Acknowledgments

**Technologies Used:**
- [Docker](https://www.docker.com/) - Containerization
- [Traefik](https://traefik.io/) - API Gateway
- [MLflow](https://mlflow.org/) - ML lifecycle management
- [Ray](https://www.ray.io/) - Distributed computing
- [Prometheus](https://prometheus.io/) - Monitoring
- [Grafana](https://grafana.com/) - Visualization

**Best Practices:**
- [12-Factor App](https://12factor.net/)
- [Microservices Patterns](https://microservices.io/)
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)

---

## 🚀 What's Next?

### This Week
- [ ] Deploy v2.0 architecture
- [ ] Test inter-service communication
- [ ] Verify GPU sharing
- [ ] Train team on new URLs

### This Month
- [ ] Enable API authentication
- [ ] Setup SSL certificates
- [ ] Configure monitoring alerts
- [ ] Performance testing

### This Quarter
- [ ] High availability setup
- [ ] Multi-node Ray cluster
- [ ] Auto-scaling workers
- [ ] Disaster recovery plan

---

## 📞 Support

**Documentation:** See [`docs/`](./docs/) directory  
**Quick Help:** [`ML_PLATFORM_QUICK_REFERENCE.md`](./ML_PLATFORM_QUICK_REFERENCE.md)  
**Issues:** Check container logs first

---

## ⭐ Features

- 🎯 **Single URL Access** - One entry point for all services
- 🌐 **Service Mesh** - Microservices communication
- 🔄 **GPU Sharing** - Multi-service GPU access
- 📊 **Full Observability** - Metrics, logs, traces
- 🚀 **Easy Deployment** - One command setup
- 🔒 **Secure by Default** - Internal network isolation
- 📈 **Production Ready** - HA capable, scalable
- 📚 **Well Documented** - Comprehensive guides

---

**Ready to deploy?** Run: `bash scripts/quick-deploy.sh` 🎉

**Questions?** Start with: [`IMPLEMENTATION_SUMMARY.md`](./IMPLEMENTATION_SUMMARY.md)
