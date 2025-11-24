# MD Files Audit & Consolidation Plan

## ROOT LEVEL (Projects/)

### KEEP (Updated)
- ✅ **README.md** - Quick start (update needed)
- ✅ **ARCHITECTURE.md** - Just created
- ✅ **ACCESS_URLS.md** - Simplify (remove API details)

### CONSOLIDATE → Remove after merge
- **ACCESS_GUIDE.md** → Merge into ACCESS_URLS.md
- **DEPLOYMENT_SUMMARY.md** → Merge into CURRENT_DEPLOYMENT.md
- **FINAL_DEPLOYMENT_STATUS.md** → Merge into CURRENT_DEPLOYMENT.md
- **REMOTE_ACCESS_GUIDE.md** → Merge into ACCESS_URLS.md
- **TRAEFIK_MLFLOW_SOLUTION.md** → Merge into TROUBLESHOOTING.md

### REMOVE
- **DOCUMENTATION_PLAN.md** - Planning doc, not needed
- **FILE_MANIFEST.md** - Auto-generated, not needed
- **GIT_SAFETY_CHECK.md** - One-time check, not needed

---

## MLFLOW-SERVER/

### KEEP
- **README.md** - Rebuild as stack-specific guide
- **TROUBLESHOOTING.md** - Keep, update

### CONSOLIDATE
- **CONSOLIDATION_SUMMARY.md** → Remove (outdated)
- **CURRENT_DEPLOYMENT.md** → Merge to root CURRENT_DEPLOYMENT.md
- **DEPLOYMENT_CHECKLIST.md** → Merge to TROUBLESHOOTING.md
- **QUICK_REFERENCE.md** → Merge to README.md
- **REPOSITORY_STRUCTURE.md** → Remove (obvious from tree)

### ml-platform/mlflow-server/docs/
**ACTION:** Consolidate entire folder

- **API_USAGE_GUIDE.md** → Merge to root API_REFERENCE.md
- **DEPLOYMENT_SUMMARY.md** → Merge to root CURRENT_DEPLOYMENT.md
- **FINAL_SECURITY_REPORT.md** → Merge to ARCHITECTURE.md security section
- **GIT_SETUP.md** → Remove (one-time setup)
- **LOCAL_CONFIG.md** → Merge to ml-platform/mlflow-server/README.md
- **MLFLOW_SETUP_GUIDE.md** → Merge to ml-platform/mlflow-server/README.md
- **QUICK_START.md** → Merge to ml-platform/mlflow-server/README.md
- **README.md** → Remove (parent README sufficient)
- **REMOTE_CLIENT_SETUP.md** → Merge to root ACCESS_URLS.md
- **SECURITY.md** → Merge to ARCHITECTURE.md
- **SECURITY_STATUS.md** → Merge to CURRENT_DEPLOYMENT.md
- **TROUBLESHOOTING.md** → Merge to parent TROUBLESHOOTING.md

### ml-platform/mlflow-server/mlflow_server/docs/
**ACTION:** Consolidate or remove entire folder

- **ARCHITECTURE_UPDATE.md** → Merge to root ARCHITECTURE.md
- **ARTIFACT_ORGANIZATION_GUIDE.md** → Merge to ml-platform/mlflow-server/README.md
- **BACKUP_RETENTION.md** → Merge to ml-platform/mlflow-server/README.md
- **COMPLETE_DEPLOYMENT_GUIDE.md** → Merge to ml-platform/mlflow-server/README.md
- **DATABASE_ACCESS_GUIDE.md** → Merge to ml-platform/mlflow-server/README.md
- **DIAGNOSTICS_GUIDE.md** → Merge to TROUBLESHOOTING.md
- **LARGE_UPLOAD_CONFIG.md** → Merge to ml-platform/mlflow-server/README.md
- **MIGRATION_GUIDE.md** → Archive (one-time task)
- **PASSWORD_UPDATE_GUIDE.md** → Merge to ml-platform/mlflow-server/README.md
- **PERFORMANCE_TUNING.md** → Merge to ARCHITECTURE.md
- **README.md** → Remove
- **SECURITY_ANALYSIS.md** → Merge to ARCHITECTURE.md
- **TESTING_GUIDE.md** → Merge to ml-platform/mlflow-server/README.md

### ml-platform/mlflow-server/mlflow_server/
**Duplicate structure - consolidate**

- **QUICK_REFERENCE.md** → Remove
- **QUICKSTART.md** → Remove
- **README.md** → Remove

### ml-platform/mlflow-server/scripts/
- **README.md** → Keep minimal (describe scripts)

### ml-platform/mlflow-server/secrets/
- **README.md** → Keep (important for secrets mgmt)

---

## RAY_COMPUTE/

### KEEP
- **README.md** - Update with integration details

### CONSOLIDATE
- **CONTRIBUTING.md** → Remove (not open source)
- **INFRASTRUCTURE_STATUS.md** → Merge to root CURRENT_DEPLOYMENT.md
- **LESSONS_LEARNED.md** → Archive
- **REPOSITORY_STATUS.md** → Merge to root CURRENT_DEPLOYMENT.md

### ml-platform/ray_compute/docs/
- **ARCHITECTURE.md** → Merge to root ARCHITECTURE.md
- **OAUTH_SETUP_GUIDE.md** → Keep (specific OAuth config)
- **OPERATIONS.md** → Merge to ml-platform/ray_compute/README.md
- **POST_REBOOT.md** → Merge to TROUBLESHOOTING.md
- **PRE_REBOOT_VERIFICATION.md** → Merge to TROUBLESHOOTING.md
- **STARTUP_GUIDE.md** → Merge to ml-platform/ray_compute/README.md

### ml-platform/ray_compute/web_ui/
- **DEPLOYMENT_STATUS.md** → Merge to CURRENT_DEPLOYMENT.md
- **LOGIN_TESTING_GUIDE.md** → Merge to ml-platform/ray_compute/README.md
- **README.md** → Merge to parent README.md

---

## GRAFANA PLUGINS
**ACTION:** Ignore (third-party, in data/)

- ml-platform/mlflow-server/data/grafana/plugins/**/README.md - Leave alone

---

## GITHUB
- ml-platform/mlflow-server/.github/copilot-instructions.md - Update
- ml-platform/ray_compute/.github/copilot-instructions.md - Update

---

## Summary

**Current:** 67 .md files  
**After consolidation:** ~15 files

**New Structure:**
```
Projects/
├── README.md (updated)
├── ARCHITECTURE.md (new)
├── API_REFERENCE.md (new)
├── ACCESS_URLS.md (updated)
├── CURRENT_DEPLOYMENT.md (new)
├── INTEGRATION_GUIDE.md (new)
├── TROUBLESHOOTING.md (new)
├── ml-platform/mlflow-server/
│   ├── README.md (rebuilt)
│   ├── NEXT_STEPS.md (new)
│   ├── TROUBLESHOOTING.md (updated)
│   ├── scripts/README.md (keep)
│   └── secrets/README.md (keep)
├── ml-platform/ray_compute/
│   ├── README.md (updated)
│   ├── NEXT_STEPS.md (new)
│   ├── docs/OAUTH_SETUP_GUIDE.md (keep)
│   └── .github/copilot-instructions.md (update)
└── .github/copilot-instructions.md (update)
```

**Reduction:** 67 → 15 files (77% reduction)
