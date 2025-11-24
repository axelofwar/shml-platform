# GitHub Copilot Instructions for MLflow Server

**Last Updated:** 2025-11-22  
**Part of:** Unified ML Platform (MLflow + Ray)

---

## Repository Context

**Project:** ML Platform v0.1.0 - Production-ready MLflow + Ray distributed computing  
**Stack:** MLflow (8 containers) + Ray (10 containers) + Traefik gateway  
**License:** MIT  
**Status:** ✅ Fully operational, all services healthy

**Key Principles:**
- All secrets in `secrets/` (git-ignored)
- Configuration via docker-compose.yml
- Documentation <20 files (currently 17)
- Professional GitHub-ready project structure

---

## ⚠️ DOCUMENTATION POLICY - READ FIRST

### Documentation Structure (v0.1.0)

**Project maintains <20 total documentation files. Current: 17 files.**

### Core Documentation (11 files)

**Root Level:**
1. **README.md** - Project overview, quick start, status
2. **ARCHITECTURE.md** - System design, infrastructure, monitoring
3. **API_REFERENCE.md** - All API documentation (MLflow, Ray, Traefik)
4. **INTEGRATION_GUIDE.md** - Service integration, OAuth, job submission, best practices
5. **TROUBLESHOOTING.md** - Issues and solutions (800+ lines)
6. **LESSONS_LEARNED.md** - Critical patterns (Traefik priority, Ray memory, startup)
7. **REMOTE_QUICK_REFERENCE.md** - Remote access guide (public)
8. **NEW_GPU_SETUP.md** - GPU configuration (exportable to remote machines)

**Subproject:**
9. **mlflow-server/README.md** - MLflow-specific operations
10. **ray_compute/README.md** - Ray-specific operations

**AI Context:**
11. **Copilot instructions** (this file + ray_compute/.github/copilot-instructions.md)

**Project Files (6 files):**
- CHANGELOG.md, CONTRIBUTING.md, LICENSE, CODE_OF_CONDUCT.md, .gitignore
- REMOTE_ACCESS_COMPLETE.sh (git-ignored, contains credentials)

### Rules for Documentation Changes

1. **ALWAYS update existing docs** - Never create new files without approval
   
2. **Check these files first:**
   - Setup/Status → README.md
   - System design → ARCHITECTURE.md  
   - APIs → API_REFERENCE.md
   - Integration/Usage → INTEGRATION_GUIDE.md
   - Problems → TROUBLESHOOTING.md
   - Patterns → LESSONS_LEARNED.md
   - Remote → REMOTE_QUICK_REFERENCE.md

3. **If new file absolutely needed:**
   - Explain why existing docs can't accommodate
   - Show it won't exceed 20 file limit
   - Get explicit approval before creating

4. **Never create:**
   - Duplicate guides (we consolidated 74 → 17 files)
   - Status files (use README.md)
   - Setup guides (use README.md or subproject README)
   - API docs (use API_REFERENCE.md)

5. **Update CHANGELOG.md** for all documentation changes

### Example Dialogue

```
User: "Document the new backup feature"
❌ Bad: Create BACKUP_GUIDE.md (creates 18th file)
✅ Good: "Adding Backup section to mlflow-server/README.md under Operations"

User: "Add OAuth troubleshooting"  
❌ Bad: Create OAUTH_TROUBLESHOOTING.md
✅ Good: "Adding OAuth section to TROUBLESHOOTING.md line 450"
```

---

## Structure

```
mlflow-server/
├── README.md              # MLflow-specific guide
├── NEXT_STEPS.md          # Roadmap
├── docker-compose.yml     # 8 services
├── secrets/               # Git-ignored passwords
│   ├── db_password.txt
│   ├── grafana_password.txt
│   └── README.md
├── scripts/               # Management scripts
│   └── README.md
├── data/                  # Persistent volumes
└── docs/
    └── README.md          # Placeholder
├── .env.example                 # Configuration template (safe to commit)
├── .env                         # Actual config (gitignored)
├── docker-compose.yml           # Service definitions
│
├── docs/                        # All documentation (safe to commit)
│   ├── README.md               # Documentation index
│   ├── QUICK_START.md          # Complete setup guide
│   ├── API_USAGE_GUIDE.md      # Python examples with placeholders
│   ├── DEPLOYMENT_SUMMARY.md   # Architecture details
│   ├── SECURITY.md             # Security best practices
│   ├── TROUBLESHOOTING.md      # Common issues & solutions
│   └── [other guides...]
│
├── scripts/                     # Management tools (safe to commit)
│   ├── README.md               # Scripts documentation
│   ├── deploy.sh               # Main deployment
│   ├── check_status.sh         # Health checks
│   ├── mlflow-admin.sh         # Interactive admin (15 operations)
│   ├── access_info.sh          # Display URLs (dynamic IPs)
│   ├── ensure_tailscale.sh     # Verify VPN
│   └── [20+ utilities...]
│
├── docker/                      # Docker configurations
│   ├── mlflow/
│   │   ├── Dockerfile
│   │   └── entrypoint.sh       # Creates experiments on startup
│   ├── nginx/                  # Reverse proxy configs
│   ├── postgres/               # DB initialization
│   └── [other services...]
│
├── config/                      # Configuration templates
├── secrets/                     # GITIGNORED - passwords, keys
│   └── db_password.txt         # PostgreSQL password
├── data/                        # GITIGNORED - persistent data
├── backups/                     # GITIGNORED - backup files
└── logs/                        # GITIGNORED - log files
```

### Quick Navigation Commands

```bash
# View current live status (with secrets)
cat CURRENT_DEPLOYMENT.md

# View safe public documentation
cat README.md

# Show all access URLs dynamically
./scripts/access_info.sh

# Interactive admin menu
./scripts/mlflow-admin.sh

# Check service health
./scripts/check_status.sh
```

---

## 🔒 Security & Secrets Management

### Critical Rules

1. **NEVER hardcode secrets in code or documentation**
2. **NEVER commit files with real IPs or passwords**
3. **ALWAYS use placeholders in committed files**
4. **ALWAYS check .gitignore before creating new files with secrets**

### Where Secrets Live

```bash
# Database password
secrets/db_password.txt              # Auto-generated by deploy.sh

# Environment configuration
.env                                 # Actual config (gitignored)
.env.example                         # Template only (safe to commit)

# Runtime deployment status
CURRENT_DEPLOYMENT.md                # Local only (gitignored)
```

### How to Reference Secrets in Code

**❌ WRONG:**
```python
mlflow.set_tracking_uri("http://${TAILSCALE_IP}:8080")
password = "gNz8APgrUF8Q3hMe2sQXQK8DPGHs3CGcVhoPLbcqvi4="
```

**✅ CORRECT:**
```python
# In documentation
mlflow.set_tracking_uri("http://MLFLOW_SERVER_IP:8080")

# In scripts - use dynamic detection
TAILSCALE_IP=$(tailscale ip -4)
mlflow.set_tracking_uri("http://$TAILSCALE_IP:8080")

# In docker-compose.yml - use secrets
DB_PASSWORD=$(cat /run/secrets/db_password)
```

### Safe Placeholders for Documentation

- IPs: `MLFLOW_SERVER_IP`, `YOUR_SERVER_IP`, `100.XX.XXX.XXX`
- Passwords: `<GENERATED_BY_DEPLOY_SCRIPT>`, `<from-secrets>`, `YOUR_PASSWORD`
- Paths: Use relative paths or environment variables

---

## 🌐 Traefik Routing & Priority Configuration (CRITICAL)

### Router Priority Rules

**Problem:** Traefik internal API uses PathPrefix(`/api`) with ultra-high priority (2147483646), intercepting all `/api/*` requests including custom APIs.

**Solution:** Application routers that use `/api/*` paths MUST have priority ≥ 2147483647 (max int32) to take precedence.

**Configuration Pattern:**
```yaml
# docker-compose.yml
labels:
  - traefik.enable=true
  - traefik.http.routers.mlflow-api-v1.rule=PathPrefix(`/api/v1`)
  - traefik.http.routers.mlflow-api-v1.priority=2147483647  # CRITICAL: Must be max int32
  - traefik.http.services.mlflow-api-service.loadbalancer.server.port=8000
```

**Why This Matters:**
- Traefik evaluates routes by priority (highest first)
- Internal API router (`api@internal`) has priority 2147483646
- Without higher priority, your API routes return 404
- Use max int32 (2147483647) to guarantee precedence

**Access Points:**
- **Application APIs:** http://localhost/api/v1/* (priority 2147483647)
- **Traefik Dashboard API:** http://localhost:8090/api/* (internal, port 8090)
- **Traefik Dashboard UI:** http://localhost:8090/ (internal)

**Verification:**
```bash
# Check router priorities
curl -s http://localhost:8090/api/http/routers | jq '.[] | select(.name | contains("api")) | {name, rule, priority}'

# Should show:
# mlflow-api-v1@docker: priority 2147483647 (highest)
# api@internal: priority 2147483646 (internal API)
```

**Never Do:**
```yaml
# ❌ WRONG - Will be intercepted by Traefik internal API
- traefik.http.routers.my-api.rule=PathPrefix(`/api/v1`)
- traefik.http.routers.my-api.priority=500  # Too low!
```

---

## 🐳 Docker & Service Management

### Docker Permissions - Permanent Fix Applied

**Issue Resolved:** User added to docker group, socket permissions fixed.

**Current Setup:**
```bash
# User is in docker group (permanent)
sudo usermod -aG docker $USER

# Socket permissions fixed
sudo chmod 666 /var/run/docker.sock
```

**After Reboot (if needed):**
```bash
sudo chmod 666 /var/run/docker.sock
```

### Service Management Patterns

**Starting/Stopping Services:**
```bash
# Always use docker compose (not docker-compose)
docker compose up -d
docker compose down
docker compose restart mlflow

# Check status
docker compose ps

# View logs
docker compose logs -f mlflow
```

**Health Checks:**
```bash
# Use existing scripts (don't create new ones)
./scripts/check_status.sh         # Comprehensive status
curl http://localhost:8080/health  # Quick health check
```

### Background Process Management

**When to Use Background Terminals:**
- Long-running processes (servers, watch modes)
- Commands that need to continue while you work
- Monitoring logs in real-time

**Pattern:**
```bash
# Start in background terminal
docker compose up -d

# Monitor in separate terminal
docker compose logs -f mlflow

# Don't block main terminal
```

---

## 🌐 Tailscale VPN Configuration

### Current Setup (Working)

- **Service:** `tailscaled` (systemd)
- **Auto-start:** Enabled on boot
- **IP Allocation:** Stable/permanent (doesn't change)
- **Verification:** `./scripts/ensure_tailscale.sh`

### Tailscale Best Practices

```bash
# Check status
tailscale status

# Get IP (for scripts)
TAILSCALE_IP=$(tailscale ip -4)

# Show connection info
./scripts/access_info.sh

# Verify on startup (can add to cron)
./scripts/ensure_tailscale.sh
```

### IP Address Handling

**Never hardcode Tailscale IPs in scripts!** Always detect dynamically:

```bash
# ✅ CORRECT
LOCAL_IP=$(hostname -I | awk '{print $1}')
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "Not connected")

# ❌ WRONG
LOCAL_IP="${SERVER_IP}"
TAILSCALE_IP="${TAILSCALE_IP}"
```

---

## 📝 Documentation Standards

### File Purposes

| File | Purpose | Contains Secrets | Committed |
|------|---------|------------------|-----------|
| `README.md` | Public overview | No | ✅ Yes |
| `CURRENT_DEPLOYMENT.md` | Live status | Yes | ❌ No (gitignored) |
| `docs/*.md` | Detailed guides | No | ✅ Yes |
| `QUICK_REFERENCE.md` | Daily operations | No | ✅ Yes |
| `.env.example` | Config template | No | ✅ Yes |
| `.env` | Actual config | Yes | ❌ No (gitignored) |

### When Creating New Documentation

1. **Determine if it contains secrets:**
   - YES → Add to `.gitignore` or use `CURRENT_DEPLOYMENT.md`
   - NO → Place in `docs/` directory

2. **Use appropriate placeholders:**
   - IPs: `MLFLOW_SERVER_IP`, `YOUR_TAILSCALE_IP`
   - Passwords: `<from-secrets>`, `<GENERATED>`
   - Paths: Relative or variables

3. **Cross-reference existing docs:**
   - Link to related guides
   - Update `docs/README.md` if needed
   - Don't duplicate information

---

## 🔧 Script Development Practices

### Reuse Before Creating

**Before writing a new script, check:**

```bash
# All management scripts
ls scripts/*.sh

# Interactive admin has 15 operations
./scripts/mlflow-admin.sh

# Existing utilities
./scripts/check_status.sh         # Health checks
./scripts/access_info.sh          # Connection info
./scripts/ensure_tailscale.sh     # VPN verification
./scripts/test_persistence.sh     # Data persistence
./scripts/show_credentials.sh     # Database access
./scripts/deploy.sh               # Full deployment
```

### Script Patterns to Follow

**1. Docker Permission Handling (no longer needed but kept for reference):**
```bash
# Old pattern (still in some scripts)
if ! groups | grep -q docker; then
    exec sg docker "$0 $@"
fi
```

**2. Dynamic IP Detection:**
```bash
LOCAL_IP=$(hostname -I | awk '{print $1}')
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "Not connected")
```

**3. Secrets Loading:**
```bash
# Never hardcode passwords
DB_PASSWORD=$(cat secrets/db_password.txt)
export POSTGRES_PASSWORD="$DB_PASSWORD"
```

**4. Error Handling:**
```bash
set -e  # Exit on error

if [ ! -f "secrets/db_password.txt" ]; then
    echo "❌ Error: Password file not found"
    exit 1
fi
```

### Script Organization

- **New scripts** → `scripts/` directory
- **Update** `scripts/README.md` when adding scripts
- **Test** scripts before committing
- **Document** parameters and usage

---

## 🚀 MLflow Server Startup & Configuration

### Automatic Startup on Container Launch

**Location:** `docker/mlflow/entrypoint.sh`

**What it does:**
1. Waits for PostgreSQL to be ready
2. Starts MLflow server in background (`mlflow server` command)
3. Waits for MLflow health check
4. Creates custom experiments (idempotent)
5. Keeps container running with `wait`

**Experiments Created (IDs 0-5):**
```python
experiments = {
    "production-models": {"env": "production", "requires_approval": "true"},
    "staging-models": {"env": "staging", "requires_testing": "true"},
    "development-models": {"env": "development", "requires_validation": "true"},
    "dataset-registry": {"env": "production", "requires_schema": "true"},
    "model-registry-experiments": {"env": "production"}
}
```

### Configuration Files

**Docker Compose:**
- File: `docker-compose.yml`
- No `version:` field (removed for modern Docker Compose)
- Uses secrets for passwords
- Health checks for all critical services

**Environment Variables:**
```bash
# Template
.env.example → Copy to .env on first deployment

# Critical variables
MLFLOW_WORKERS=8                  # Gunicorn workers
MLFLOW_WORKER_TIMEOUT=3600        # Long timeout for large uploads
POSTGRES_MAX_CONNECTIONS=100      # DB connection pool
BACKUP_RETENTION_DAYS=90          # Backup retention
```

---

## 📊 Monitoring & Health Checks

### Services to Monitor

```bash
# All services
docker compose ps

# Individual health
curl http://localhost:8080/health     # MLflow
docker compose exec postgres pg_isready  # PostgreSQL
tailscale status                      # VPN
```

### Existing Monitoring Tools

```bash
# Comprehensive status
./scripts/check_status.sh

# Interactive admin console
./scripts/mlflow-admin.sh
# Options include:
# - View logs
# - Check health
# - Restart services
# - Database shell
# - View backups
# - System diagnostics
```

---

## 🔄 Backup & Data Persistence

### Current Backup Setup

**Automated:**
- Schedule: Daily at 2 AM
- Service: `mlflow-backup` container
- Script: `docker/backup/backup.sh`
- Retention: 90 days (configurable in `.env`)

**Manual Backup:**
```bash
docker compose exec backup /backup.sh
```

### Data Persistence Locations

```bash
./data/
├── postgres/        # Database files (survives restarts)
├── mlflow/
│   └── artifacts/   # Model artifacts, datasets
├── redis/           # Cache
├── prometheus/      # Metrics history
└── grafana/         # Dashboard configs

./backups/
├── postgres/        # Database dumps
└── artifacts/       # Artifact snapshots
```

### Testing Persistence

```bash
# Use existing script (don't create new one)
./scripts/test_persistence.sh
```

---

## 🧪 Experiments & Schema Validation

### Pre-configured Experiments

All experiments are created automatically on container startup. **Don't manually create them.**

| ID | Name | Schema Enforcement |
|----|------|--------------------|
| 0 | Default | None |
| 1 | production-models | requires_approval |
| 2 | staging-models | requires_testing |
| 3 | development-models | requires_validation |
| 4 | dataset-registry | requires_schema |
| 5 | model-registry-experiments | None |

### Schema Validation

**Plugin Location:** `docker/mlflow/plugins/schema_validator.py`

**How it works:**
- Validates tags on run end
- Enforces required metadata
- Checks experiment-specific requirements

**Required tags per experiment documented in:**
- `docs/API_USAGE_GUIDE.md`
- `CURRENT_DEPLOYMENT.md` (local only)

---

## 🛠️ Troubleshooting Patterns

### When Something Breaks

1. **Check existing troubleshooting guide:**
   ```bash
   cat docs/TROUBLESHOOTING.md
   ```

2. **Use diagnostic scripts:**
   ```bash
   ./scripts/check_status.sh
   ./scripts/mlflow-admin.sh  # Option 8: Diagnostics
   ```

3. **Check logs:**
   ```bash
   docker compose logs mlflow
   docker compose logs postgres
   docker compose logs nginx
   ```

4. **Common fixes documented in:**
   - `docs/TROUBLESHOOTING.md` - 10+ common issues
   - `scripts/mlflow-admin.sh` - Interactive fixes

### Don't Reinvent Solutions

**Before creating a new fix:**
1. Check `docs/TROUBLESHOOTING.md`
2. Review existing scripts in `scripts/`
3. Look at `mlflow-admin.sh` menu options
4. Search documentation for similar issues

---

## 📚 Documentation Maintenance

### Keeping Instructions Updated

**When you fix something or add a feature:**

1. **Update relevant documentation:**
   - `docs/TROUBLESHOOTING.md` - If it was a bug/issue
   - `docs/API_USAGE_GUIDE.md` - If it's a usage pattern
   - `QUICK_REFERENCE.md` - If it's a common operation
   - `scripts/README.md` - If you added a script

2. **Update these Copilot instructions:**
   - Location: `.github/copilot-instructions.md`
   - Add new patterns, practices, or gotchas
   - Document configuration changes

3. **Update CURRENT_DEPLOYMENT.md (local only):**
   - Live status changes
   - New services or endpoints
   - Updated credentials or IPs

### Documentation Update Checklist

- [ ] Does the fix solve a common issue? → `docs/TROUBLESHOOTING.md`
- [ ] Is it a new feature or capability? → Update main `README.md`
- [ ] Does it change configuration? → Update `.env.example`
- [ ] Is it a new script? → Document in `scripts/README.md`
- [ ] Does it affect security? → Update `docs/SECURITY.md`
- [ ] Is it a best practice? → Update `.github/copilot-instructions.md`

---

## 🎯 Common Tasks Reference

### Deployment

```bash
# First time
./scripts/deploy.sh

# Restart after config change
docker compose down
docker compose up -d

# Rebuild containers
./scripts/rebuild_and_start.sh
```

### Accessing Services

```bash
# Show all URLs
./scripts/access_info.sh

# Database credentials
./scripts/show_credentials.sh

# Web interfaces
open http://localhost:8080    # MLflow
open http://localhost:3000    # Grafana
open http://localhost:8081    # Adminer
```

### Making Changes

```bash
# Configuration
vim .env                      # Edit config
docker compose restart        # Apply changes

# Update experiments
vim docker/mlflow/entrypoint.sh
./scripts/rebuild_and_start.sh

# Add new documentation
vim docs/NEW_GUIDE.md
# Add link to docs/README.md
```

---

## 🚦 Development Workflow

### Before Making Changes

1. **Check current state:**
   ```bash
   ./scripts/check_status.sh
   cat CURRENT_DEPLOYMENT.md
   ```

2. **Review existing code/docs:**
   - Check if functionality exists
   - Review related documentation
   - Look for similar patterns

3. **Plan changes:**
   - Will it affect security? Review `docs/SECURITY.md`
   - Does it need new config? Update `.env.example`
   - Will it need documentation? Plan updates

### After Making Changes

1. **Test thoroughly:**
   ```bash
   docker compose down
   docker compose up -d
   ./scripts/check_status.sh
   ./scripts/test_persistence.sh
   ```

2. **Update documentation:**
   - Relevant guides in `docs/`
   - Update `CURRENT_DEPLOYMENT.md` if needed
   - Update these instructions if it's a pattern

3. **Verify git safety:**
   ```bash
   git status
   # Check no secrets staged
   grep -r "SECRET_VALUE" .
   ```

---

## ⚠️ Critical Warnings

### Never Do This

❌ **Hardcode secrets:**
```bash
# WRONG
PASSWORD="gNz8APgrUF8Q..."
```

❌ **Commit secrets:**
```bash
# WRONG
git add .env
git add CURRENT_DEPLOYMENT.md
git add secrets/
```

❌ **Skip permission checks:**
```bash
# WRONG - use dynamic detection
TAILSCALE_IP="${TAILSCALE_IP}"
```

❌ **Create duplicate scripts:**
```bash
# WRONG - reuse existing
./new-status-check.sh  # when check_status.sh exists
```

### Always Do This

✅ **Use placeholders in docs:**
```bash
mlflow.set_tracking_uri("http://MLFLOW_SERVER_IP:8080")
```

✅ **Load secrets from files:**
```bash
DB_PASSWORD=$(cat secrets/db_password.txt)
```

✅ **Detect IPs dynamically:**
```bash
TAILSCALE_IP=$(tailscale ip -4)
```

✅ **Reuse existing scripts:**
```bash
./scripts/check_status.sh  # Use existing
```

---

## 📖 Quick Reference

### Essential Files

```bash
README.md                      # Start here
CURRENT_DEPLOYMENT.md          # Live status (local only)
QUICK_REFERENCE.md             # Daily operations
docs/QUICK_START.md            # Setup guide
docs/API_USAGE_GUIDE.md        # Usage examples
docs/TROUBLESHOOTING.md        # Common issues
```

### Essential Scripts

```bash
./scripts/deploy.sh            # Full deployment
./scripts/check_status.sh      # Health check
./scripts/mlflow-admin.sh      # Interactive admin
./scripts/access_info.sh       # Connection URLs
./scripts/ensure_tailscale.sh  # VPN check
```

### Essential Commands

```bash
docker compose ps              # Service status
docker compose logs -f mlflow  # View logs
tailscale status               # VPN status
curl http://localhost:8080/health  # Health
```

---

## 🎓 Learning the Codebase

### New to this repo? Start here:

1. **Read main documentation:**
   ```bash
   cat README.md
   cat QUICK_REFERENCE.md
   cat docs/QUICK_START.md
   ```

2. **Explore structure:**
   ```bash
   tree -L 2 -I 'data|backups|logs|__pycache__|.git'
   ```

3. **Check current deployment:**
   ```bash
   cat CURRENT_DEPLOYMENT.md
   ./scripts/access_info.sh
   ```

4. **Run health checks:**
   ```bash
   ./scripts/check_status.sh
   ```

5. **Review these instructions:**
   ```bash
   cat .github/copilot-instructions.md
   ```

---

## 🔄 Version Information

- **MLflow:** 2.17.2
- **PostgreSQL:** 15
- **Python:** 3.10+
- **Docker Compose:** 3.8+ (no version field in yml)
- **Tailscale:** 1.90.8+

---

## 📞 Support Resources

- **Documentation:** `docs/README.md`
- **Troubleshooting:** `docs/TROUBLESHOOTING.md`
- **Scripts Guide:** `scripts/README.md`
- **Security:** `docs/SECURITY.md`
- **These Instructions:** `.github/copilot-instructions.md`

---

**Last Updated:** November 21, 2025  
**Update these instructions** when you discover new patterns or practices!
