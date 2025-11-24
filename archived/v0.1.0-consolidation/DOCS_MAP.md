# Documentation Map

**Last Updated:** 2025-11-22

---

## Core Documentation (11 files)

### Root Level (7 files)
1. **README.md** - Quick start, stack overview
2. **ARCHITECTURE.md** - Tool decisions, scaling, network integration
3. **API_REFERENCE.md** - OpenAPI specs for all 4 APIs
4. **ACCESS_URLS.md** - Quick URL reference table
5. **INTEGRATION_GUIDE.md** - MLflow+Ray service communication
6. **CURRENT_DEPLOYMENT.md** - Deployment status, what's running
7. **TROUBLESHOOTING.md** - Common issues, fixes
8. **LESSONS_LEARNED.md** - Critical patterns: Traefik priorities, Ray memory, startup phasing ⭐

### MLflow Stack (2 files)
9. **ml-platform/mlflow-server/README.md** - MLflow setup, features, operations
10. **ml-platform/mlflow-server/NEXT_STEPS.md** - MLflow roadmap

### Ray Stack (2 files)
11. **ml-platform/ray_compute/README.md** - Ray setup, OAuth, features
12. **ml-platform/ray_compute/NEXT_STEPS.md** - Ray roadmap

---

## Supporting Documentation (4 files)

- **ml-platform/ray_compute/LESSONS_LEARNED.md** - OAuth debugging, React hydration
- **ml-platform/ray_compute/CONTRIBUTING.md** - Development guidelines
- **ml-platform/ray_compute/docs/OAUTH_SETUP_GUIDE.md** - OAuth configuration
- **ml-platform/ray_compute/web_ui/README.md** - Web UI development

---

## Operational Files (4 files)

- **ml-platform/mlflow-server/scripts/README.md** - MLflow script reference
- **ml-platform/mlflow-server/secrets/README.md** - Secrets management
- **ml-platform/mlflow-server/docs/README.md** - Placeholder
- **ml-platform.service** - Systemd auto-start

---

## Scripts (10 files)

### Unified
- **start_all.sh** - Start both stacks
- **stop_all.sh** - Stop both stacks
- **restart_all.sh** - Restart both stacks

### MLflow
- **ml-platform/mlflow-server/start.sh** - Start MLflow only
- **ml-platform/mlflow-server/stop.sh** - Stop MLflow only
- **ml-platform/mlflow-server/restart.sh** - Restart MLflow only

### Ray
- **ml-platform/ray_compute/start.sh** - Start Ray only
- **ml-platform/ray_compute/stop.sh** - Stop Ray only
- **ml-platform/ray_compute/restart.sh** - Restart Ray only

### Plus
- **ml-platform/mlflow-server/scripts/** - 15 management scripts (check_status.sh, etc.)

---

## Copilot Instructions (2 files)

- **ml-platform/mlflow-server/.github/copilot-instructions.md** - MLflow context
- **ml-platform/ray_compute/.github/copilot-instructions.md** - Ray context

---

## Archived (16 files in archived/ directories)

Reference only - old versions preserved for history.

---

## Total Active Docs

**Core:** 11 files  
**Supporting:** 4 files  
**Operational:** 4 files  
**Scripts:** 10 files  
**Copilot:** 2 files  
**Total:** 31 active documentation files (+ LESSONS_LEARNED.md)

**Reduction:** 106 → 32 files (70% reduction)

---

## Quick Reference

### Need to...
- **Get started?** → README.md
- **Understand architecture?** → ARCHITECTURE.md
- **Use APIs?** → API_REFERENCE.md
- **Access services?** → ACCESS_URLS.md
- **Connect MLflow+Ray?** → INTEGRATION_GUIDE.md
- **Check status?** → CURRENT_DEPLOYMENT.md
- **Fix issues?** → TROUBLESHOOTING.md
- **Setup MLflow?** → ml-platform/mlflow-server/README.md
- **Setup Ray?** → ml-platform/ray_compute/README.md
- **Debug OAuth?** → ml-platform/ray_compute/LESSONS_LEARNED.md

### Everything else
All info consolidated in core 11 docs above.

**Updated:** 2025-11-22
