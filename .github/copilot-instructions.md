````instructions
# GitHub Copilot Instructions - ML Platform (Root)

**Last Updated:** 2025-11-23
**Version:** 0.1.0
**License:** MIT
**Project:** Unified ML Platform (MLflow + Ray Compute + Traefik)

---

## ⚠️ CRITICAL: DOCUMENTATION POLICY - ENFORCE ALWAYS

### Documentation Structure (v0.1.0)

**THIS PROJECT MAINTAINS <20 TOTAL DOCUMENTATION FILES. CURRENT: 17 FILES.**

**ANY ATTEMPT TO CREATE NEW DOCUMENTATION FILES MUST BE REJECTED.**

### Current Documentation Files (17 TOTAL - DO NOT EXCEED)

**Root Level (13 core docs):**
1. `README.md` - Project overview, quick start, all services status
2. `ARCHITECTURE.md` - System design, infrastructure, service topology
3. `API_REFERENCE.md` - All API documentation (MLflow, Ray, Traefik)
4. `INTEGRATION_GUIDE.md` - Service integration, OAuth, Ray jobs, best practices
5. `TROUBLESHOOTING.md` - Issues and solutions (800+ lines, comprehensive)
6. `LESSONS_LEARNED.md` - Critical patterns (Traefik priority, Ray memory, Docker networking, startup)
7. `REMOTE_QUICK_REFERENCE.md` - Remote access guide (public, no credentials)
8. `NEW_GPU_SETUP.md` - GPU configuration (exportable to remote machines)
9. `MONETIZATION_STRATEGY.md` - Revenue streams, pricing models, B2B/B2C strategies (SHARED with pii-pro)
10. `SELF_HOSTED_PREMIUM_FEATURES.md` - Supabase-like features (PostgREST, MinIO, Meilisearch, etc.)
11. `mlflow-server/README.md` - MLflow-specific operations
12. `ray_compute/README.md` - Ray-specific operations
13. **Copilot instructions:** This file + subproject copilot-instructions.md

**Project Files (6 files):**
- `LICENSE` - MIT License
- `CONTRIBUTING.md` - Contribution guidelines (includes documentation policy)
- `CODE_OF_CONDUCT.md` - Contributor Covenant v2.0
- `CHANGELOG.md` - Version history and release notes
- `.gitignore` - Git ignore rules (350+ lines)
- `REMOTE_ACCESS_COMPLETE.sh` - Credentials script (git-ignored)

**TOTAL: 19 files (1 file below 20-file limit)**

---

## 🚨 ENFORCEMENT RULES - READ BEFORE ANY DOCUMENTATION CHANGE

### Rule 1: NEVER Create New Documentation Files

**If user requests documentation, you MUST:**

1. **Identify which existing file should contain the content:**
   - Setup/Status → `README.md`
   - Architecture/Design → `ARCHITECTURE.md`
   - API documentation → `API_REFERENCE.md`
   - Integration/Usage → `INTEGRATION_GUIDE.md`
   - Problems/Errors → `TROUBLESHOOTING.md`
   - Patterns/Gotchas → `LESSONS_LEARNED.md`
   - Remote access → `REMOTE_QUICK_REFERENCE.md`
   - GPU setup → `NEW_GPU_SETUP.md`
   - MLflow operations → `mlflow-server/README.md`
   - Ray operations → `ray_compute/README.md`

2. **ALWAYS respond with:**
   ```
   "I'll add [topic] to [existing-file.md] in the [section] section instead of creating a new file.
   This keeps us under the 20-file documentation limit (currently 17 files)."
   ```

3. **Update the existing file:**
   - Add new section if needed
   - Use proper Markdown hierarchy
   - Include examples and code blocks
   - Cross-reference related sections

4. **Update CHANGELOG.md** to document the change

### Rule 2: Reject File Creation Requests

**Example Dialogues:**

```
User: "Create a DEPLOYMENT_GUIDE.md"
❌ Bad: Create the file
✅ Good: "I'll add deployment information to README.md under 'Deployment' section.
          This prevents exceeding our 20-file limit (currently 17 files)."

User: "Document the backup process in a new file"
❌ Bad: Create BACKUP_GUIDE.md
✅ Good: "I'll add backup documentation to ARCHITECTURE.md under 'Data Persistence' section.
          This keeps our documentation consolidated (17/20 files used)."

User: "Create an OAuth troubleshooting guide"
❌ Bad: Create OAUTH_TROUBLESHOOTING.md
✅ Good: "I'll add OAuth troubleshooting to TROUBLESHOOTING.md under 'Authentication' section.
          This file already has 800+ lines for comprehensive troubleshooting."

User: "Make a QUICK_START.md"
❌ Bad: Create the file
✅ Good: "The quick start is already in README.md under 'Quick Start' section.
          I'll enhance that section instead of creating a duplicate."
```

### Rule 3: If New File Truly Necessary

**Before creating ANY documentation file, you MUST:**

1. **Explain why ALL 11 existing docs cannot accommodate the content**
2. **Show proof that consolidation is impossible**
3. **Demonstrate it won't exceed 20-file limit**
4. **Get EXPLICIT user approval** with exact filename
5. **Archive an existing file to stay under 20 files** if at limit

**This should happen <1% of the time.**

### Rule 4: Update CHANGELOG.md

**For ANY documentation change:**
- Add entry to CHANGELOG.md under [Unreleased] section
- Document what was added/changed
- Note which file was modified

---

## 📁 Project Structure

```
ml-platform/
├── README.md                      # 1. Main overview
├── ARCHITECTURE.md                # 2. System design
├── API_REFERENCE.md               # 3. All APIs
├── INTEGRATION_GUIDE.md           # 4. Integration patterns
├── TROUBLESHOOTING.md             # 5. Problem solutions
├── LESSONS_LEARNED.md             # 6. Critical patterns
├── REMOTE_QUICK_REFERENCE.md      # 7. Remote access
├── NEW_GPU_SETUP.md               # 8. GPU configuration
├── LICENSE                        # MIT License
├── CONTRIBUTING.md                # Contribution guidelines
├── CODE_OF_CONDUCT.md             # Community standards
├── CHANGELOG.md                   # Version history
├── .gitignore                     # Git ignore rules
├── REMOTE_ACCESS_COMPLETE.sh      # Credentials (git-ignored)
│
├── .github/
│   └── copilot-instructions.md    # 11. This file (AI context)
│
├── mlflow-server/
│   ├── README.md                  # 9. MLflow operations
│   ├── .github/
│   │   └── copilot-instructions.md  # MLflow AI context
│   ├── docker-compose.yml         # 8 MLflow services
│   ├── api/                       # MLflow API enhancements
│   ├── scripts/                   # Management utilities
│   ├── secrets/                   # Git-ignored
│   └── data/                      # Git-ignored
│
├── ray_compute/
│   ├── README.md                  # 10. Ray operations
│   ├── .github/
│   │   └── copilot-instructions.md  # Ray AI context
│   ├── docker-compose.*.yml       # 10 Ray services
│   ├── api/                       # Ray Compute API
│   ├── web_ui/                    # Next.js dashboard
│   ├── scripts/                   # Management utilities
│   ├── .env                       # Git-ignored
│   └── data/                      # Git-ignored
│
├── traefik/
│   ├── docker-compose.gateway.yml # Gateway configuration
│   └── traefik.yml                # Traefik config
│
├── inference/                     # Local LLM + Image Gen
│   ├── docker-compose.inference.yml
│   ├── qwen3-vl/                  # Qwen3-VL-8B service
│   ├── z-image/                   # Z-Image-Turbo service
│   ├── gateway/                   # Queue, rate limit, history
│   ├── scripts/                   # start/stop/download
│   ├── secrets/                   # Git-ignored
│   └── data/models/               # Git-ignored, HuggingFace cache
│
├── scripts/                       # Platform scripts
│   ├── start_all.sh
│   ├── stop_all.sh
│   └── check_platform_status.sh
│
└── archived/                      # Consolidated docs
    └── v0.1.0-consolidation/      # 26 archived files
        └── README.md              # Migration guide
```

---

## 🏗️ Architecture Overview

### Service Topology

**MLflow Stack (8 services):**
- mlflow-server (tracking server)
- mlflow-api (enhanced API)
- postgres (tracking DB)
- redis (cache)
- nginx (reverse proxy)
- prometheus (metrics)
- grafana (dashboards)
- backup (automated backups)

**Ray Compute Stack (10 services):**
- ray-compute-api (job submission)
- ray-compute-ui (Next.js dashboard)
- authentik-server (OAuth)
- authentik-worker (background tasks)
- authentik-postgres (auth DB)
- authentik-redis (cache)
- ray-prometheus (metrics)
- ray-grafana (dashboards)
- ray-loki (logs)
- ray-promtail (log shipping)

**Traefik Gateway (1 service):**
- traefik (reverse proxy, load balancer)

**Inference Stack (4 services):**
- qwen3-vl-api (LLM, RTX 2070, INT4 quantized)
- z-image-api (Image Gen, RTX 3090, on-demand)
- inference-gateway (queue, rate limit, history)
- inference-postgres (chat history DB)

**Total: 23 containers (19 core + 4 inference)**

### Network Architecture

```
ml-platform network (shared)
├── traefik (gateway) - :80, :8090
├── mlflow-server - :8080
├── mlflow-api - :8000
├── ray-compute-api - :8000
├── ray-compute-ui - :3002
├── authentik - :9000
├── qwen3-vl-api - :8000 (via /api/llm)
├── z-image-api - :8000 (via /api/image)
├── inference-gateway - :8000 (via /inference)
└── monitoring services
```

---

## 🤖 Inference Stack (Local LLM + Image Generation)

### GPU Allocation Strategy
- **RTX 2070 (cuda:0, 8GB)**: Qwen3-VL-8B-INT4 - always loaded
- **RTX 3090 (cuda:1, 24GB)**: Z-Image - on-demand, yields to training

### Key Endpoints
```
/api/llm/v1/chat/completions  - OpenAI-compatible LLM
/api/llm/health               - Qwen3-VL status
/api/image/v1/generate        - Image generation
/api/image/yield-to-training  - Free RTX 3090 for training
/inference/health             - Gateway status
/inference/conversations      - Chat history
/inference/queue/status       - Request queue
```

### Privacy Guarantees
- `TRANSFORMERS_OFFLINE=1` - No outbound connections
- Models cached locally after one-time download
- Chat history in local PostgreSQL only
- Tailscale VPN required for remote access
- No telemetry, no prompt logging

### Resource Management
```bash
# Before training on RTX 3090:
curl -X POST http://localhost/api/image/yield-to-training

# Z-Image auto-unloads after 5min idle
# Z-Image auto-reloads on next request
```

---

## 🔒 Security Standards

### Secrets Management

**Git-Ignored Files:**
- `REMOTE_ACCESS_COMPLETE.sh` - Contains ALL credentials, IPs, passwords
- `mlflow-server/secrets/` - Database passwords
- `ray_compute/.env` - OAuth secrets, API keys
- `*/data/` - Persistent data volumes
- `*/logs/` - Service logs
- `*/backups/` - Database backups

**Safe Files (Can Commit):**
- `.env.example` - Templates with placeholders
- All documentation files (17 files)
- Source code without secrets
- Configuration templates

### Placeholder Patterns

**Never in committed files:**
```
❌ PASSWORD=gNz8APgrUF8Q3hMe2sQXQK8DPGHs3CGcVhoPLbcqvi4=
❌ TAILSCALE_IP=${TAILSCALE_IP}
❌ DB_HOST=192.168.1.100
```

**Always use:**
```
✅ PASSWORD=<from-secrets-file>
✅ TAILSCALE_IP=<detected-dynamically>
✅ DB_HOST=<your-server-ip>
```

---

## 🎯 Critical Patterns (From LESSONS_LEARNED.md)

### 1. Traefik Router Priority

**Problem:** Traefik internal API intercepts `/api/*` requests
**Solution:** Application routers MUST use priority `2147483647` (max int32)

```yaml
labels:
  - traefik.http.routers.api.rule=PathPrefix(`/api/v1`)
  - traefik.http.routers.api.priority=2147483647  # CRITICAL
```

### 2. Ray Memory Allocation

**Problem:** Ray head crashes with memory errors
**Solution:** Follow memory calculation rule

```
container_memory ≥ object_store_memory + shm_size + 1GB
```

### 3. Docker Networking (Ubuntu apt docker.io)

**Problem:** Containers can't communicate after Docker reinstall
**Solution:** Disable bridge netfilter

```bash
sudo sysctl -w net.bridge.bridge-nf-call-iptables=0
sudo sysctl -w net.bridge.bridge-nf-call-ip6tables=0
```

### 4. Service Startup Order

**Problem:** Race conditions, orphaned containers
**Solution:** Use phased startup with cleanup

```bash
docker-compose down --remove-orphans
# Phase 1: Infrastructure (databases)
# Phase 2: Core services
# Phase 3: API services
# Phase 4: Monitoring
```

**See LESSONS_LEARNED.md for complete patterns**

---

## 🛠️ Common Tasks

### Platform Management

```bash
# Start entire platform
./start_all.sh

# Stop entire platform
./stop_all.sh

# Check all services
./check_platform_status.sh

# View specific service logs
docker logs mlflow-server -f
docker logs ray-compute-api -f
```

### Documentation Updates

```bash
# Always update existing files
vim README.md              # For overview/status
vim ARCHITECTURE.md        # For design decisions
vim INTEGRATION_GUIDE.md   # For usage patterns
vim TROUBLESHOOTING.md     # For problem solutions

# Never create new files without approval
# Never exceed 20 total documentation files
# Always update CHANGELOG.md
```

### Remote Access

```bash
# View public reference (safe)
cat REMOTE_QUICK_REFERENCE.md

# View complete credentials (local only, git-ignored)
cat REMOTE_ACCESS_COMPLETE.sh

# Export to remote machine
scp REMOTE_ACCESS_COMPLETE.sh user@remote:~/
scp NEW_GPU_SETUP.md user@remote:~/
```

---

## 📚 Documentation Maintenance

### When to Update Documentation

**Update README.md:**
- Service status changes
- New features added
- Quick start instructions
- Access URLs changed

**Update ARCHITECTURE.md:**
- New services added
- Infrastructure changes
- Design decisions
- System topology changes

**Update API_REFERENCE.md:**
- New endpoints
- API changes
- Schema updates
- Authentication changes

**Update INTEGRATION_GUIDE.md:**
- New integration patterns
- OAuth setup changes
- Best practices
- Usage examples

**Update TROUBLESHOOTING.md:**
- New issues discovered
- Solutions to problems
- Common errors
- Debugging procedures

**Update LESSONS_LEARNED.md:**
- Critical patterns discovered
- Gotchas and pitfalls
- Performance optimizations
- Configuration best practices

**Update CHANGELOG.md:**
- ALL changes to functionality
- ALL documentation updates
- Version releases
- Bug fixes

### Documentation Quality Standards

**Every documentation update must:**
1. Use clear, concise language
2. Include code examples where applicable
3. Use proper Markdown formatting
4. Cross-reference related sections
5. Include verification steps
6. Document "why" not just "what"

**Example Good Documentation:**
```markdown
## Feature: Job Cancellation

**Purpose:** Allows users to terminate running Ray jobs to free resources.

**API Endpoint:**
DELETE /api/v1/jobs/{job_id}

**Example:**
curl -X DELETE http://localhost:8000/api/v1/jobs/job-123 \
  -H "Authorization: Bearer $TOKEN"

**Response:**
{
  "job_id": "job-123",
  "status": "CANCELLED",
  "message": "Job terminated successfully"
}

**Verification:**
GET /api/v1/jobs/job-123
# Should show status="CANCELLED"

**Related:** See INTEGRATION_GUIDE.md for job submission patterns
```

---

## 🚦 Development Workflow

### Before Making Changes

1. **Review existing documentation:**
   - Check if feature/issue already documented
   - Identify which file(s) to update
   - Read related sections for context

2. **Check current state:**
   ```bash
   ./check_platform_status.sh
   docker ps
   ```

3. **Review file structure:**
   ```bash
   find . -name "*.md" -not -path "*/archived/*" | wc -l
   # Should show ≤20 files
   ```

### Making Changes

1. **Code changes:**
   - Follow existing patterns
   - Add tests
   - Update related documentation

2. **Documentation changes:**
   - Update existing files only
   - Add to appropriate sections
   - Use proper formatting
   - Update CHANGELOG.md

3. **Test changes:**
   - Verify services still work
   - Test new features
   - Check documentation accuracy

### After Making Changes

1. **Verify documentation count:**
   ```bash
   find . -name "*.md" -not -path "*/archived/*" -not -path "*/.git/*" | wc -l
   # MUST be ≤20
   ```

2. **Check for secrets:**
   ```bash
   git status
   git diff | grep -E "password|secret|token|key"
   # Should find none in committed files
   ```

3. **Update CHANGELOG.md:**
   - Add entry under [Unreleased]
   - Document what changed
   - Note which files modified

4. **Commit with clear message:**
   ```bash
   git add README.md CHANGELOG.md
   git commit -m "docs: Add job cancellation documentation to README"
   ```

---

## ⚠️ Critical Warnings

### Documentation Creation

**NEVER do this:**
```bash
# Creating new documentation files
touch NEW_FEATURE_GUIDE.md
touch DEPLOYMENT_CHECKLIST.md
touch OAUTH_SETUP.md
```

**ALWAYS do this:**
```bash
# Update existing documentation
vim INTEGRATION_GUIDE.md  # Add OAuth section
vim README.md             # Add deployment section
vim TROUBLESHOOTING.md    # Add feature issues
```

### File Count Validation

**Before ANY documentation change:**
```bash
# Check current count
find . -name "*.md" -not -path "*/archived/*" | wc -l

# MUST be ≤20
# Current: 17 files (3 files of buffer)
```

### Breaking the Documentation Limit

**If you absolutely must create a new file:**

1. **Archive an existing file first:**
   ```bash
   mv SOME_OLD_DOC.md archived/v0.1.0-consolidation/
   ```

2. **Update archive README:**
   ```bash
   vim archived/v0.1.0-consolidation/README.md
   # Document where content moved
   ```

3. **Get explicit user approval:**
   ```
   "I need to create NEW_FILE.md because [reason].
   This will use 18/20 documentation slots.
   Approve? (yes/no)"
   ```

4. **Update CHANGELOG.md** with justification

---

## 📖 Quick Reference

### Essential Commands

```bash
# Platform management
./start_all.sh                     # Start everything
./stop_all.sh                      # Stop everything
./check_platform_status.sh         # Health check

# Documentation check
find . -name "*.md" -not -path "*/archived/*" | wc -l  # Count docs

# Service access
open http://localhost:8080         # MLflow
open http://localhost:8000         # Ray API
open http://localhost:3002         # Ray UI
open http://localhost:9000         # Authentik

# Logs
docker logs mlflow-server
docker logs ray-compute-api
docker logs authentik-server
```

### File Locations

```bash
# Core documentation (11 files)
/home/axelofwar/Desktop/Projects/ml-platform/README.md
/home/axelofwar/Desktop/Projects/ml-platform/ARCHITECTURE.md
/home/axelofwar/Desktop/Projects/ml-platform/API_REFERENCE.md
/home/axelofwar/Desktop/Projects/ml-platform/INTEGRATION_GUIDE.md
/home/axelofwar/Desktop/Projects/ml-platform/TROUBLESHOOTING.md
/home/axelofwar/Desktop/Projects/ml-platform/LESSONS_LEARNED.md
/home/axelofwar/Desktop/Projects/ml-platform/REMOTE_QUICK_REFERENCE.md
/home/axelofwar/Desktop/Projects/ml-platform/NEW_GPU_SETUP.md
/home/axelofwar/Desktop/Projects/ml-platform/mlflow-server/README.md
/home/axelofwar/Desktop/Projects/ml-platform/ray_compute/README.md
/home/axelofwar/Desktop/Projects/ml-platform/.github/copilot-instructions.md

# Project files (6 files)
/home/axelofwar/Desktop/Projects/ml-platform/LICENSE
/home/axelofwar/Desktop/Projects/ml-platform/CONTRIBUTING.md
/home/axelofwar/Desktop/Projects/ml-platform/CODE_OF_CONDUCT.md
/home/axelofwar/Desktop/Projects/ml-platform/CHANGELOG.md
/home/axelofwar/Desktop/Projects/ml-platform/.gitignore
/home/axelofwar/Desktop/Projects/ml-platform/REMOTE_ACCESS_COMPLETE.sh
```

---

## 🔄 Version Information

- **Project Version:** 0.1.0
- **License:** MIT (axelofwar, 2025)
- **MLflow:** 2.17.2
- **Ray:** 2.8.1
- **Traefik:** 2.10
- **Authentik:** 2024.8.6
- **Docker Compose:** 3.8
- **Total Services:** 19 containers
- **Documentation Files:** 17/20 (14% buffer remaining)

---

## 📞 Support Resources

**Primary Documentation:**
- `README.md` - Start here
- `ARCHITECTURE.md` - System design
- `TROUBLESHOOTING.md` - Problem solutions
- `LESSONS_LEARNED.md` - Critical patterns

**Subproject Documentation:**
- `mlflow-server/README.md` - MLflow operations
- `ray_compute/README.md` - Ray operations

**Project Standards:**
- `CONTRIBUTING.md` - Contribution guidelines
- `CODE_OF_CONDUCT.md` - Community standards
- `CHANGELOG.md` - Version history

**AI Context:**
- `.github/copilot-instructions.md` - This file
- `mlflow-server/.github/copilot-instructions.md` - MLflow AI context
- `ray_compute/.github/copilot-instructions.md` - Ray AI context

---

**Last Updated:** November 23, 2025
**Next Update:** When documentation structure changes or new patterns discovered

**REMEMBER: <20 FILES TOTAL. CURRENT: 17 FILES. NEVER EXCEED THIS LIMIT.**

````
