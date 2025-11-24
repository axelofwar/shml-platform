# Archived Documentation - v0.1.0 Consolidation

**Archive Date:** 2025-11-23  
**Reason:** Documentation consolidation from 74 files to <20 files

---

## Purpose

These files were archived during the v0.1.0 release documentation consolidation. The content from these files has been merged into the core documentation set to maintain a cleaner, more maintainable structure.

---

## Where Content Moved

### Merged into README.md:
- CURRENT_DEPLOYMENT.md (deployment status)
- QUICK_REFERENCE.md (quick start)
- DOCS_MAP.md (documentation index)
- ACCESS_URLS.md (service URLs)

### Merged into INTEGRATION_GUIDE.md:
- AUTHENTIK_OAUTH_SETUP.md
- OAUTH_SETUP_COMPLETE.md
- OAUTH_QUICKSTART.md
- OAUTH_SETUP_GUIDE.md
- RAY_JOB_SUBMISSION_GUIDE.md
- MLFLOW_BEST_PRACTICES.md
- RESOURCE_MANAGEMENT_GUIDE.md
- REMOTE_ACCESS_GUIDE.md (superseded by REMOTE_QUICK_REFERENCE.md)
- ray_compute/docs/OAUTH_SETUP_GUIDE.md

### Merged into ARCHITECTURE.md:
- MONITORING_SETUP_COMPLETE.md
- MONITORING_STATUS.md
- DATABASE_PERSISTENCE_COMPLETE.md
- DATABASE_MIGRATIONS.md
- PII_PRO_SETUP_COMPLETE.md
- RAY_SETUP_COMPLETE.md
- SECURITY_NETWORK_IMPLEMENTATION.md
- NETWORK_ACCESS_SETUP.md

### Merged into LESSONS_LEARNED.md:
- STARTUP_ANALYSIS.md
- STARTUP_SUCCESS.md
- IMPLEMENTATION_SUMMARY.md
- ray_compute/LESSONS_LEARNED.md

### Merged into API_REFERENCE.md:
- mlflow-server/API_IMPLEMENTATION_SUMMARY.md
- mlflow-server/API_ENHANCEMENT_PLAN.md
- mlflow-server/API_STATUS_SUMMARY.md
- mlflow-server/API_QUICK_REFERENCE.md
- mlflow-server/API_QUICKSTART.md

### Merged into CONTRIBUTING.md:
- ray_compute/CONTRIBUTING.md

### Obsolete/Superseded:
- README.old.md (old version)
- DOCUMENTATION_PLAN.md (planning document, no longer needed)
- MD_AUDIT.md (audit document, no longer needed)
- mlflow-server/QUICK_START_REMOTE.md (superseded by REMOTE_QUICK_REFERENCE.md)
- mlflow-server/NEXT_STEPS.md (merged into mlflow-server/README.md)

---

## Current Documentation Structure

See the main README.md for the current documentation structure.

**Core Docs (11 files):**
1. README.md
2. ARCHITECTURE.md
3. API_REFERENCE.md
4. INTEGRATION_GUIDE.md
5. TROUBLESHOOTING.md
6. LESSONS_LEARNED.md
7. REMOTE_QUICK_REFERENCE.md
8. NEW_GPU_SETUP.md
9. mlflow-server/README.md
10. ray_compute/README.md
11. Copilot instructions (2 files)

**Project Files (6 files):**
- CHANGELOG.md
- CONTRIBUTING.md
- LICENSE
- CODE_OF_CONDUCT.md
- .gitignore
- REMOTE_ACCESS_COMPLETE.sh (git-ignored)

---

## Accessing Archived Content

These files are preserved for reference but are no longer maintained. If you need information from these files, check the current documentation first as it contains the most up-to-date and consolidated information.

To view archived files:
```bash
cd archived/v0.1.0-consolidation
ls -la
cat <filename>
```

---

## Questions?

If you can't find specific information that was in these archived files, check:
1. The main documentation (README.md, ARCHITECTURE.md, etc.)
2. CHANGELOG.md for a summary of what changed
3. Git history for the full context

---

**Note:** These files may be deleted in future releases once the consolidation has been stable for several versions.
