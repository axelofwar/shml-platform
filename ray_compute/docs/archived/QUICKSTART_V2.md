# Ray Compute V2 - Quick Start Guide

## 🚀 Setup (30 minutes)

### 1. Run Setup Script
```bash
cd /opt/shml-platform/ray_compute
chmod +x scripts/setup_enhanced.sh
./scripts/setup_enhanced.sh
```

**What it does:**
- Creates `.env` with random passwords
- Sets up PostgreSQL database
- Starts Authentik (OAuth)
- Starts Grafana stack (monitoring)
- Installs Python dependencies

### 2. Configure Authentik (Manual - 10 minutes)

1. Open: http://100.69.227.36:9000
2. Initial setup: `admin@raycompute.local` + password
3. Create OAuth provider:
   - Admin → Providers → Create → OAuth2/OpenID
   - Name: `Ray Compute API`
   - Client type: `Confidential`
   - Redirect: `http://100.69.227.36:8266/auth/callback`
4. Create application: `Ray Compute` linked to provider
5. Copy Client ID/Secret → Update `.env`

### 3. Setup Notifications (5 minutes)

**Install ntfy app on phone:** https://ntfy.sh/

**Subscribe to topics** (check your `.env` for topic names):
- Admin: `https://ntfy.sh/ray-compute-admin-<YOUR_ID>`
- Jobs: `https://ntfy.sh/ray-compute-jobs-<YOUR_ID>`
- System: `https://ntfy.sh/ray-compute-system-<YOUR_ID>`

**Test:**
```bash
source .env
curl -d "Test notification" ntfy.sh/$NTFY_ADMIN_TOPIC
```

### 4. Verify Setup
```bash
# Check all services running
docker ps

# Should see 12+ containers:
# - authentik-server, authentik-worker, authentik-postgres, authentik-redis
# - ray-prometheus, ray-loki, ray-promtail, ray-grafana
# - ray-node-exporter, ray-cadvisor, ray-gpu-exporter
# - ray-redis

# Test services
curl http://localhost:9000/-/health    # Authentik (204 No Content = OK)
curl http://localhost:3000/api/health  # Grafana (200 OK)
curl http://localhost:9090/-/healthy   # Prometheus (200 OK)

# Test database
source .env
export PGPASSWORD="$POSTGRES_PASSWORD"
psql -h localhost -U ray_compute -d ray_compute -c "SELECT username, role FROM users;"
# Should show admin user
```

---

## 📊 Access URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| **Authentik** | http://100.69.227.36:9000 | admin@raycompute.local + your password |
| **Grafana** | http://100.69.227.36:3000 | admin + password from .env |
| **Prometheus** | http://100.69.227.36:9090 | No auth |
| **Ray Dashboard** | http://100.69.227.36:8265 | No auth |
| **MLflow** | http://100.69.227.36:8080 | No auth |

---

## 🎯 What's Different in V2?

### Authentication
- ✅ **OAuth via Authentik** (not API keys)
- ✅ **3 user roles:** Admin, Premium, User
- ✅ **Per-user quotas** enforced in database
- ✅ **Token-based** API access

### Job Scheduling
- ✅ **Fractional GPU** (0.1 - 1.0, not just 0 or 1)
- ✅ **Weighted fair queue** (admins/premium get priority)
- ✅ **Backfill small jobs** (queue optimization)
- ✅ **VRAM-aware** scheduling

### Admin Features
- ✅ **Separate admin API** (`/admin/v1/*`)
- ✅ **No quotas for admins**
- ✅ **Can cancel any job, suspend users**
- ✅ **View all jobs, all users**
- ✅ **7-day job timeout** (vs 48h for users)

### Monitoring
- ✅ **Grafana dashboards** (GPU, jobs, storage)
- ✅ **Loki log aggregation** (searchable)
- ✅ **Prometheus metrics** (time-series)
- ✅ **Automatic alerts** (storage >90%, GPU temp >80°C)

### Notifications
- ✅ **Zero-cost** (ntfy.sh or Telegram)
- ✅ **Push to phone** on job complete/fail
- ✅ **Admin alerts** for system issues
- ✅ **Rate limited** (no spam)

### Storage
- ✅ **Artifact versioning** (every run)
- ✅ **Compression** (zstd, save 60-80%)
- ✅ **Smart cleanup** (90-day retention, priority-based)
- ✅ **7-day unclaimed** cleanup

---

## 🔧 What You Need to Build Next

The infrastructure is ready. Now you need to:

### 1. OAuth Middleware (`api/auth.py`)
**Time: 1 hour**
- Token validation
- Role extraction
- User lookup/creation

### 2. Enhanced API Server (`api/server_v2.py`)
**Time: 3 hours**
- Replace `server_remote.py`
- Add OAuth dependencies
- Integrate with database
- Dual namespaces: `/api/v1/*` (users), `/admin/v1/*` (admins)

### 3. GPU Scheduler (`api/scheduler.py`)
**Time: 2 hours**
- Fractional GPU allocation (0.1 - 1.0)
- VRAM estimation (model size → VRAM needs)
- Bin-packing algorithm
- GPU monitoring (actual usage vs. allocated)

### 4. Job Validator (`api/validators.py`)
**Time: 2 hours**
- AST parsing for unsafe code
- Dockerfile validation
- Resource estimation
- Blacklist checks

### 5. Notification System (`api/notifications.py`)
**Time: 1 hour**
- Apprise integration
- Template rendering
- Rate limiting
- Alert routing (user vs admin)

### 6. Admin API (`api/admin_api.py`)
**Time: 2 hours**
- Job monitoring (all users)
- User management (suspend, quotas)
- System health (GPU, storage)
- Resource analytics

### 7. CLI Tool (`cli/ray-compute`)
**Time: 2 hours**
- OAuth login flow
- All API operations
- Config file support
- Interactive mode (optional)

**Total: ~15 hours of coding**

---

## 📖 File Structure

```
ray_compute/
├── api/
│   ├── auth.py              ← Build this (OAuth)
│   ├── models.py            ← Build this (DB models)
│   ├── server_v2.py         ← Build this (main API)
│   ├── admin_api.py         ← Build this (admin endpoints)
│   ├── scheduler.py         ← Build this (GPU scheduler)
│   ├── validators.py        ← Build this (safety checks)
│   ├── notifications.py     ← Build this (Apprise)
│   ├── queue.py             ← Build this (priority queue)
│   └── metrics.py           ← Build this (Prometheus)
│
├── cli/
│   └── ray-compute          ← Build this (CLI tool)
│
├── config/                  ✅ DONE
│   ├── database_schema.sql
│   ├── prometheus.yml
│   ├── loki.yml
│   ├── grafana/
│   └── notifications.conf
│
├── docker-compose.auth.yml  ✅ DONE
├── docker-compose.observability.yml  ✅ DONE
├── .env.example             ✅ DONE
├── scripts/
│   └── setup_enhanced.sh    ✅ DONE
│
└── IMPLEMENTATION_GUIDE_V2.md  ✅ DONE
```

---

## 🐛 Troubleshooting

### Authentik won't start
```bash
docker-compose -f docker-compose.auth.yml logs authentik-server
# Common: DB not ready, check authentik-postgres logs
```

### Can't access Grafana
```bash
docker-compose -f docker-compose.observability.yml logs grafana
# Check password in .env, try: admin/admin (then reset)
```

### Database connection fails
```bash
# Check password in .env matches
psql -h localhost -U ray_compute -d ray_compute
# If fails: sudo -u postgres psql -c "\du"
```

### Notifications not working
```bash
# Test ntfy directly
curl -d "Test" ntfy.sh/ray-compute-admin-<YOUR_ID>
# Check phone app subscribed to correct topic
```

---

## 🎓 Learning Resources

### Authentik
- Docs: https://goauthentik.io/docs/
- OAuth2 flow: https://goauthentik.io/docs/providers/oauth2/

### Grafana Stack
- Prometheus: https://prometheus.io/docs/
- Loki: https://grafana.com/docs/loki/
- Grafana: https://grafana.com/docs/grafana/

### Apprise
- Docs: https://github.com/caronc/apprise
- Supported services: https://github.com/caronc/apprise/wiki

---

## ✅ Success Criteria

You're ready to build when:
- ✅ All containers running (`docker ps`)
- ✅ Authentik accessible (http://100.69.227.36:9000)
- ✅ Grafana accessible (http://100.69.227.36:3000)
- ✅ Database has admin user
- ✅ Notifications reach your phone

---

## 📞 Next Steps

1. **Follow IMPLEMENTATION_GUIDE_V2.md** for detailed walkthrough
2. **Start with `api/auth.py`** - OAuth middleware
3. **Test incrementally** - Don't build everything at once
4. **Ask questions** - I'll help debug issues

---

**Status:** Infrastructure Complete ✅  
**Next:** Build OAuth middleware  
**Time to MVP:** ~15 hours

Happy coding! 🚀
