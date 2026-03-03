# SHML Platform — Cleanup & Documentation Plan

> Created: 2026-02-28 | Status: Planning
> Training completed: 5/5 epochs — mAP50=0.812, mAP50-95=0.413, P=0.891, R=0.738

---

## Objectives

1. **Clean README.md** — single, scannable entry point for users/devs/admins
2. **GitHub Pages docs site** — MkDocs Material with full SDK/API/architecture documentation
3. **Bloat removal** — eliminate 61+ GB of backups, stale docs, junk files, redundant CLIs
4. **Smart data management** — no duplication, S3/HuggingFace streaming, configurable paths
5. **Consistent config** — fix SDK defaults that mismatch platform.env

---

## Phase 1: Bloat Removal & Repository Hygiene

### 1.1 Delete Junk Files

| Action | Path | Reason |
|--------|------|--------|
| Delete | `test_agent_output/` | One-off test junk |
| Delete | `.agent_backups/` | Auto-generated, 236 KB |
| Delete | `docker-compose.yml.bak-include` | Stale backup in root |
| Delete | `docs/internal/house_taxes.md` | Personal file in repo |
| Delete | `tests/test_add_numbers.py` | Throwaway test |
| Delete | `tests/test_simple.py` | Throwaway test |
| Delete | `scripts/test_reorganization.py` | One-off script |
| Delete | `archived/v0.2.0-pre-unified-cleanup/.env.backup` | Stale env backup |
| Delete | `secrets/*.bak.*` | Stale cert backup files |

### 1.2 Prune Backups (est. 58 GB savings)

```
backups/platform/   →  Keep 2 most recent, delete other 24 snapshots (~58 GB)
backups/postgres/   →  Keep as-is (29 MB, reasonable)
```

### 1.3 Move Misplaced Files

| File | From | To |
|------|------|----|
| `IMPLEMENTATION_SUMMARY_NEMOTRON_OPENCODE.md` | root | `docs/internal/` |
| `SETUP_SCRIPT_README.md` | root | `docs/guides/setup.md` (rewrite) |
| `BOOTSTRAP.md` content | root | merge into README Quick Start |
| `test_dev_integration.sh` | root | `tests/` |
| `test_opencode_setup.sh` | root | `tests/` |
| `opencode_demo.sh` | root | `archived/` |

### 1.4 Deprecate Redundant CLIs

Three CLI implementations currently exist:

| CLI | Location | Lines | Action |
|-----|----------|-------|--------|
| SDK CLI | `sdk/shml/main.py` | 466 | **Keep** — canonical |
| Old Typer CLI | `cli/shml.py` | 1,253 | **Deprecate** — add deprecation notice, remove after v2.0 |
| Click CLI | `libs/client/shml/cli.py` | 551 | **Merge admin commands** into SDK CLI, deprecate |
| Admin CLI | `libs/client/shml/admin/cli.py` | 1,006 | **Keep as admin-only** — separate `shml-admin` entry point |

**Migration path:**
1. Add `[admin]` extras to SDK `pyproject.toml` importing `libs/client`
2. Add `shml admin` sub-command group in SDK CLI that delegates to admin client
3. Add `DEPRECATED` banner to `cli/shml.py` and `libs/client/shml/cli.py`

### 1.5 Consolidate Documentation (73 → ~30 files)

**Delete/archive these overlap clusters:**

| Cluster | Files to consolidate | Target |
|---------|---------------------|--------|
| Remote Access (3 files, 1,241 lines) | `REMOTE_ACCESS_NEW.md`, `REMOTE_QUICK_REFERENCE.md`, `REMOTE_JOB_SUBMISSION.md` | → `docs/guides/remote-access.md` |
| MLflow (3 files, 3,042 lines) | `MLFLOW_VERIFICATION.md`, `MLFLOW_GOVERNANCE_RESEARCH.md`, `MLFLOW_GOVERNANCE_ANALYSIS.md` | → `docs/guides/mlflow.md` + archive research |
| Grafana (2 files, 917 lines) | `GRAFANA_INTEGRATION_VERIFICATION.md`, `GRAFANA_DASHBOARD_CONSOLIDATION.md` | → `docs/guides/monitoring.md` |
| Architecture (2 files, 1,447 lines) | `ARCHITECTURE_REDESIGN.md`, `internal/ARCHITECTURE.md` | → `docs/architecture.md` |
| Phase 1 (3 files, 1,466 lines) | `PHASE1_LAUNCH_READY.md`, `PHASE1_EXPERT_ANALYSIS.md`, `PHASE_P1_COMPLETION_REPORT.md` | → `docs/internal/archived_approaches/phase1.md` |
| Research (3 files, 2,688 lines) | `COMPREHENSIVE_ANALYSIS_2025_12.md`, `RESEARCH_FINDINGS_2025_12.md`, `RESEARCH_INTEGRATION_SUMMARY.md` | → `docs/research/analysis-dec-2025.md` |
| v0.3.0 Consolidation (20 files) | Everything in `archived_approaches/v0.3.0-consolidation/` | → single summary + zip |

**Special cases:**
- `PLATFORM_IMPROVEMENTS_PROJECT_BOARD.md` (7,851 lines) → Move to GitHub Issues/Projects
- `TROUBLESHOOTING.md` (1,280 lines) → Keep as `docs/guides/troubleshooting.md`, remove duplicated section from README

---

## Phase 2: Smart Data Management

### 2.1 Problem Statement

Data is currently duplicated and hardcoded:
- `/tmp/ray/data/wider_face_yolo/` hardcoded in 3+ files
- `/tmp/ray/checkpoints/face_detection/` with run-specific timestamps in 4+ files  
- Host path `/home/axelofwar/Projects/shml-platform/ray_compute/data/...` leaked into eval script
- No mechanism to use data already present in Ray without re-uploading
- No S3/remote streaming — datasets permanently stored on local disk

### 2.2 Data Path Configuration

**Replace all hardcoded paths with SDK config resolution:**

```python
# sdk/shml/config.py — new DataConfig
@dataclass
class DataConfig:
    """Data location configuration — zero duplication, configurable paths."""

    # Base directories (inside Ray container)
    ray_data_dir: str = "/tmp/ray/data"
    ray_checkpoint_dir: str = "/tmp/ray/checkpoints"

    # Dataset references (can be local path, s3://, hf://, or named)
    dataset: str = "wider_face_yolo"  # Resolved to {ray_data_dir}/{dataset}/data.yaml

    # Model artifact source
    checkpoint: str | None = None     # Phase checkpoint to fine-tune from

    # Remote sources
    hf_dataset: str | None = None     # e.g. "wider_face" (downloads if not cached)
    s3_uri: str | None = None         # e.g. "s3://bucket/datasets/wider_face/"

    # Lifecycle
    persist_remote_data: bool = False  # If False, use temp cache for remote data
    max_cache_gb: float = 50.0        # Auto-evict old cached datasets

    def resolve_data_yaml(self) -> str:
        """Resolve the actual data.yaml path, checking existence."""
        ...

    def resolve_checkpoint(self) -> str | None:
        """Resolve checkpoint — latest phase, specific path, or MLflow model URI."""
        ...
```

**Resolution chain for datasets:**
1. Check if `{ray_data_dir}/{dataset}/data.yaml` exists → use directly (no copy)
2. Check if `{dataset}` is an absolute path → use directly
3. Check if `hf_dataset` is set → `huggingface_hub` streaming or cached download
4. Check if `s3_uri` is set → mount via `s3fs`/`fsspec` or stream
5. Fail with clear error message listing what was tried

**Resolution chain for checkpoints:**
1. Explicit path → use directly
2. `"latest"` → glob `{checkpoint_dir}/*/weights/best.pt`, sort by mtime
3. `"mlflow:{model_name}/{version}"` → fetch from MLflow model registry
4. Phase name like `"phase5"` → glob `phase_5_*/weights/best.pt`

### 2.3 Private/Proprietary Data Protection

```python
class DataConfig:
    # ... fields above ...

    # Privacy controls
    persist_remote_data: bool = False   # Don't permanently store referenced data
    auto_cleanup_after_hours: float = 0  # 0 = keep until evicted, >0 = auto-delete
    data_isolation: bool = True          # Each job gets isolated data view
```

**Behavior for private data:**
- When `persist_remote_data=False` and `s3_uri` or `hf_dataset` is set:
  - Data is streamed or cached to a **temp directory** inside the Ray job workspace
  - After training completes, the cached data is deleted
  - Only model weights and metrics are persisted
- When `data_isolation=True`:
  - Job receives a read-only bind of the shared dataset
  - Writes go to job-specific workspace
  - No cross-contamination between users' data

### 2.4 Data Deduplication in Ray

**Problem:** Users re-upload the same dataset for every job submission.

**Solution:** Content-addressed dataset registry:

```python
# In sdk/shml/client.py
def submit_training(self, config: TrainingConfig) -> Job:
    """Smart submit — checks if data exists in Ray before uploading."""

    data_path = config.data.resolve_data_yaml()

    # Check if dataset already exists in Ray
    if self._dataset_exists_in_ray(config.data.dataset):
        # Use existing data — don't upload
        payload["use_existing_dataset"] = config.data.dataset
    elif config.data.s3_uri:
        # Pass S3 URI — Ray worker fetches directly
        payload["data_source"] = {"type": "s3", "uri": config.data.s3_uri}
    elif config.data.hf_dataset:
        # Pass HF reference — Ray worker downloads
        payload["data_source"] = {"type": "huggingface", "name": config.data.hf_dataset}
    else:
        # Local file — upload only if not already present
        payload["data_source"] = {"type": "local", "data_yaml": data_path}
```

---

## Phase 3: README.md Rewrite

### 3.1 Structure (target: ~400 lines, down from 675)

```markdown
# SHML Platform

> Self-Hosted ML Platform — GPU-optimized training, experiment tracking,
> model registry, and agentic development on your own hardware.

## Quick Start (5 min)
- Prerequisites (Docker, NVIDIA Container Toolkit, 24GB+ VRAM)
- `./setup.sh && ./start_all_safe.sh`
- Verify: `shml platform status`

## SDK Installation
- `pip install -e sdk/`
- `shml train --profile quick-test --dry-run`
- `shml config list-profiles`

## Training (The Main Event)
### Via CLI
- `shml train --profile balanced --epochs 10`
- `shml train --profile quick-test`
- `shml status <job_id>`

### Via Python SDK
```python
from shml import Client, TrainingConfig
with Client() as c:
    job = c.submit_training("balanced", epochs=10)
    final = c.wait_for_job(job.job_id)
```

### Via API
```bash
curl -X POST http://localhost/api/ray/jobs \
  -H "X-API-Key: $SHML_API_KEY" \
  -d '{"name": "my-training", "gpu": 1.0, ...}'
```

### Training Profiles
| Profile | Epochs | Batch | ImgSz | Duration |
|---------|--------|-------|-------|----------|
| quick-test | 2 | 8 | 640 | ~10 min |
| balanced | 10 | 4 | 1280 | ~2.5 hr |
| full-finetune | 50 | 4 | 1280 | ~12 hr |
| foundation | 100 | 4 | 1280 | ~24 hr |

### Data Management
- Using existing data in Ray (zero-copy)
- HuggingFace datasets (streaming)
- S3/remote references (private data)
- Custom datasets (data.yaml format)

## Architecture
- Diagram (Mermaid)
- Service groups (1 paragraph each)
- Link to full architecture doc

## Services & Ports
- Compact table of all services

## GPU Management
- `shml gpu status|yield|reclaim`

## Monitoring
- Grafana dashboards + links
- MLflow experiment tracking
- Prometheus metrics

## User Roles
| Role | Capabilities |
|------|-------------|
| viewer | Read dashboards, view experiments |
| developer | Submit jobs, manage own experiments |
| elevated-developer | GPU management, model registry |
| admin | Platform management, user admin |

## Documentation
- [Full Documentation](https://shml-platform.github.io/docs)
- [SDK Reference](https://shml-platform.github.io/docs/sdk/)
- [Learning Series](https://shml-platform.github.io/docs/learning/)

## License
```

**Key changes from current README:**
- Removed 100+ lines of troubleshooting (→ docs site)
- Removed inline architecture deep-dives (→ docs site)
- Added SDK/CLI front and center
- Added training profiles table
- Added data management section
- Removed agentic development section (→ docs site, niche audience)
- Compact service table instead of verbose listing

---

## Phase 4: GitHub Pages Documentation Site

### 4.1 Tool Choice: MkDocs Material

**Why:** Markdown-native (reuses existing `.md` files), built-in search, code tabs, admonitions, API docs integration, dark mode, GitHub Actions deployment.

### 4.2 Site Structure

```
docs/
├── index.md                          # Home — overview + quick links
├── getting-started/
│   ├── installation.md               # Prerequisites, setup.sh, first run
│   ├── quickstart.md                 # 5-minute hello world
│   └── configuration.md              # platform.env, profiles, .env
├── sdk/
│   ├── index.md                      # SDK overview
│   ├── client.md                     # Client class reference
│   ├── config.md                     # PlatformConfig, TrainingConfig, DataConfig
│   ├── training-profiles.md          # Profile YAML format, built-in profiles
│   ├── training-runner.md            # TrainingRunner lifecycle
│   └── integrations/
│       ├── mlflow.md                 # MLflow client — experiments, metrics, registry
│       ├── nessie.md                 # Nessie — branch/tag lifecycle
│       ├── fiftyone.md               # FiftyOne — dataset viz, evaluation
│       ├── feature-store.md          # Feature client
│       └── prometheus.md             # Pushgateway metrics
├── cli/
│   ├── index.md                      # CLI overview
│   ├── train.md                      # shml train reference
│   ├── jobs.md                       # status, logs, cancel, list
│   ├── gpu.md                        # gpu status, yield, reclaim
│   ├── config-commands.md            # config show, list-profiles, validate
│   └── auth.md                       # auth login, status, logout
├── api/
│   ├── index.md                      # API overview, authentication
│   ├── jobs.md                       # POST/GET/DELETE /api/ray/jobs
│   ├── gpu.md                        # GPU management API
│   └── admin.md                      # Admin endpoints (user management)
├── guides/
│   ├── training-walkthrough.md       # End-to-end training guide
│   ├── data-management.md            # Datasets, dedup, S3, HuggingFace, privacy
│   ├── remote-access.md              # Tailscale, remote job submission
│   ├── monitoring.md                 # Grafana, Prometheus, Loki, alerting
│   ├── mlflow.md                     # MLflow deep-dive — experiments, model registry
│   ├── gpu-management.md             # Yield/reclaim, multi-GPU, scheduling
│   ├── troubleshooting.md            # Common issues + resolutions
│   └── model-deployment.md           # From training → inference
├── architecture/
│   ├── index.md                      # System architecture overview + diagram
│   ├── services.md                   # Service inventory with ports/roles
│   ├── security.md                   # Auth flow, RBAC, secrets, TLS
│   ├── data-flow.md                  # How data flows: upload → Ray → training → MLflow
│   └── docker-compose.md             # Compose file organization, profiles
├── reference/
│   ├── environment-variables.md      # All env vars with descriptions
│   ├── training-hyperparameters.md   # Complete YOLO hyperparameter reference
│   ├── docker-volumes.md             # Named volumes, bind mounts, data lifecycle
│   └── changelog.md                  # Moved from root CHANGELOG.md
├── learning/
│   ├── index.md                      # Learning series overview
│   ├── part1-benchmarking.md         # From openclaw learning series
│   ├── part2-distributed-compute.md  
│   ├── part3-table-formats.md  
│   ├── part4-feature-platform.md  
│   └── cheatsheet-iceberg.md  
├── admin/
│   ├── index.md                      # Admin overview
│   ├── user-management.md            # FusionAuth, roles, API keys
│   ├── backup-restore.md             # Postgres dumps, platform snapshots
│   ├── platform-operations.md        # start/stop, health checks, upgrades
│   └── secrets-management.md         # Cert rotation, DB passwords, key management
└── contributing.md                   # Moved from root CONTRIBUTING.md
```

### 4.3 MkDocs Configuration

```yaml
# mkdocs.yml
site_name: SHML Platform
site_url: https://shml-platform.github.io/docs
repo_url: https://github.com/yourusername/shml-platform
repo_name: shml-platform

theme:
  name: material
  palette:
    - scheme: slate
      primary: deep purple
      accent: amber
      toggle:
        icon: material/brightness-4
        name: Switch to light mode
    - scheme: default
      primary: deep purple
      accent: amber
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.expand
    - navigation.top
    - search.suggest
    - search.highlight
    - content.code.copy
    - content.code.annotate
    - content.tabs.link

plugins:
  - search
  - mkdocstrings:
      handlers:
        python:
          paths: [sdk]
          options:
            show_source: true
            show_root_heading: true

markdown_extensions:
  - admonition
  - pymdownx.details
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_mermaid
  - pymdownx.tabbed:
      alternate_style: true
  - pymdownx.highlight:
      anchor_linenums: true
  - pymdownx.inlinehilite
  - toc:
      permalink: true

nav:
  - Home: index.md
  - Getting Started:
    - Installation: getting-started/installation.md
    - Quick Start: getting-started/quickstart.md
    - Configuration: getting-started/configuration.md
  - SDK:
    - Overview: sdk/index.md
    - Client: sdk/client.md
    - Configuration: sdk/config.md
    - Training Profiles: sdk/training-profiles.md
    - Training Runner: sdk/training-runner.md
    - Integrations:
      - MLflow: sdk/integrations/mlflow.md
      - Nessie: sdk/integrations/nessie.md
      - FiftyOne: sdk/integrations/fiftyone.md
      - Feature Store: sdk/integrations/feature-store.md
      - Prometheus: sdk/integrations/prometheus.md
  - CLI:
    - Overview: cli/index.md
    - Training: cli/train.md
    - Jobs: cli/jobs.md
    - GPU: cli/gpu.md
    - Config: cli/config-commands.md
    - Auth: cli/auth.md
  - API Reference:
    - Overview: api/index.md
    - Jobs API: api/jobs.md
    - GPU API: api/gpu.md
    - Admin API: api/admin.md
  - Guides:
    - Training Walkthrough: guides/training-walkthrough.md
    - Data Management: guides/data-management.md
    - Remote Access: guides/remote-access.md
    - Monitoring: guides/monitoring.md
    - MLflow: guides/mlflow.md
    - GPU Management: guides/gpu-management.md
    - Model Deployment: guides/model-deployment.md
    - Troubleshooting: guides/troubleshooting.md
  - Architecture:
    - Overview: architecture/index.md
    - Services: architecture/services.md
    - Security: architecture/security.md
    - Data Flow: architecture/data-flow.md
    - Docker Compose: architecture/docker-compose.md
  - Reference:
    - Environment Variables: reference/environment-variables.md
    - Hyperparameters: reference/training-hyperparameters.md
    - Docker Volumes: reference/docker-volumes.md
    - Changelog: reference/changelog.md
  - Learning Series:
    - Overview: learning/index.md
    - "Part 1: Benchmarking": learning/part1-benchmarking.md
    - "Part 2: Distributed Compute": learning/part2-distributed-compute.md
    - "Part 3: Table Formats": learning/part3-table-formats.md
    - "Part 4: Feature Platform": learning/part4-feature-platform.md
    - "Cheatsheet: Iceberg SQL": learning/cheatsheet-iceberg.md
  - Admin:
    - Overview: admin/index.md
    - User Management: admin/user-management.md
    - Backup & Restore: admin/backup-restore.md
    - Platform Operations: admin/platform-operations.md
    - Secrets Management: admin/secrets-management.md
  - Contributing: contributing.md
```

### 4.4 GitHub Actions Deployment

```yaml
# .github/workflows/docs.yml
name: Deploy Documentation
on:
  push:
    branches: [main]
    paths: ['docs/**', 'mkdocs.yml', 'sdk/**']
  workflow_dispatch:

permissions:
  contents: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install mkdocs-material mkdocstrings[python] pymdown-extensions
      - run: mkdocs gh-deploy --force
```

---

## Phase 5: Fix Configuration Inconsistencies

### 5.1 SDK Defaults vs platform.env Mismatches

| Field | SDK Default | platform.env Value | Fix |
|-------|-------------|-------------------|-----|
| `mlflow_artifact_root` | `/tmp/ray/mlflow-artifacts` | `/mlflow/artifacts` | Use `from_env()` inheritance — value comes from platform.env, not hardcoded default |
| `mlflow_registry_model` | `face-detection-yolov8` | `face-detection-yolov8l-p2` | Same — inherit from env |
| `data_yaml` | `/tmp/ray/data/wider_face_yolo/data.yaml` | (not in env) | Replace with `DataConfig` resolution chain |

### 5.2 Secrets Cleanup

| Action | Target |
|--------|--------|
| Remove | `secrets/sfml-platform.tail38b60a.ts.net.crt.bak.*` (stale backups) |
| Remove | `secrets/sfml-platform.tail38b60a.ts.net.key.bak.*` (stale backups) |
| Audit | Which `*_db_password.txt` files are active vs legacy |
| Document | In `docs/admin/secrets-management.md` — every secret file, what uses it, rotation procedure |

### 5.3 Hardcoded Host Path Removal

| File | Line | Current | Fix |
|------|------|---------|-----|
| `wider_face_eval.py` | L809 | `/home/axelofwar/Projects/shml-platform/ray_compute/data/...` | Use `DataConfig.ray_checkpoint_dir` |
| `train_phase8_integrated.py` | L158 | `Path("/tmp/ray/checkpoints/face_detection")` | Use `DataConfig.ray_checkpoint_dir` |
| `train_phase8_integrated.py` | L159 | Run-specific timestamp path | Use `DataConfig.resolve_checkpoint("phase5")` |

---

## Phase 6: SOTA Integration Documentation

### 6.1 Already Implemented (Document These)

| Integration | Status | Documentation Priority |
|-------------|--------|----------------------|
| MLflow 2.x | Working | High — experiment tracking, model registry, artifact management |
| Nessie (Iceberg catalog) | Working | High — data versioning, experiment branching |
| FiftyOne | Working | Medium — dataset visualization, evaluation |
| Prometheus + Grafana | Working | High — real-time training metrics dashboards |
| Feature Store (Spark-backed) | Available | Medium — feature extraction and logging |
| Ray cluster (multi-GPU) | Working | High — distributed training, job orchestration |
| YOLO11x fine-tuning | Working | High — primary training pipeline |
| OAuth2 (FusionAuth) | Working | Medium — RBAC, API keys, 4-tier roles |
| Traefik reverse proxy | Working | Low — infrastructure detail |

### 6.2 SOTA Features to Document

| Feature | Where to Document |
|---------|------------------|
| Curriculum learning (multi-phase training) | `guides/training-walkthrough.md` |
| Automatic mixed precision (AMP) | `reference/training-hyperparameters.md` |
| Mosaic + MixUp + CopyPaste augmentation | `reference/training-hyperparameters.md` |
| Multi-scale training (P2 detection head) | `guides/training-walkthrough.md` |
| Model registry with versioning | `sdk/integrations/mlflow.md` |
| Git-like data branching (Nessie) | `sdk/integrations/nessie.md` |
| Real-time loss monitoring (Pushgateway) | `guides/monitoring.md` |
| Profile-driven reproducible training | `sdk/training-profiles.md` |
| GPU yield/reclaim lifecycle | `guides/gpu-management.md` |

### 6.3 Potential SOTA Additions (Future Work)

| Integration | Value | Effort | Notes |
|-------------|-------|--------|-------|
| Weights & Biases | Alternative experiment tracker | Low | Document as optional MLflow alternative |
| DVC (Data Version Control) | Dataset versioning | Medium | Nessie already provides this |
| ONNX export pipeline | Model optimization | Low | Add to model deployment guide |
| TensorRT optimization | Inference speedup | Medium | Existing inference services could benefit |
| HuggingFace Hub integration | Model sharing | Low | Push fine-tuned models to HF |
| Label Studio integration | Active learning loop | Medium | Data annotation → training feedback loop |
| Ray Tune | Hyperparameter optimization | Low | Already have Ray — just need Tune config |
| Distributed training (multi-node) | Scale beyond single machine | High | Architecture change needed |

---

## Phase 7: Execution Order & Dependencies

```
Phase 1: Bloat Removal ─────────────────────────── (2-3 hours)
    ↓
Phase 2: Data Management ───────────────────────── (4-6 hours)
    │   - DataConfig class
    │   - Resolution chain
    │   - SDK integration
    ↓
Phase 3: README.md Rewrite ─────────────────────── (1-2 hours)
    │
Phase 4: GitHub Pages Site ─────────────────────── (8-12 hours)
    │   - mkdocs.yml setup
    │   - Port/consolidate existing docs
    │   - Write new SDK/CLI/API reference
    │   - Learning series integration
    │   - GitHub Actions deployment
    ↓
Phase 5: Config Fixes ──────────────────────────── (1-2 hours)
    │   - SDK defaults alignment
    │   - Secrets cleanup
    │   - Hardcoded path removal
    ↓
Phase 6: SOTA Documentation ────────────────────── (3-4 hours)
    │   - Training walkthrough
    │   - Integration deep-dives
    │   - Feature reference
    ↓
Ready for Clean Upload ───────────────────────────
```

**Total estimated effort:** 20-30 hours across all phases

---

## Appendix A: Files to Delete (Complete List)

```bash
# Junk files
rm -rf test_agent_output/
rm -rf .agent_backups/
rm -f docker-compose.yml.bak-include
rm -f docs/internal/house_taxes.md
rm -f tests/test_add_numbers.py
rm -f tests/test_simple.py
rm -f scripts/test_reorganization.py

# Stale cert backups  
rm -f secrets/*.bak.*

# Prune platform backups (keep 2 most recent)
ls -t backups/platform/ | tail -n +3 | xargs -I {} rm -rf backups/platform/{}
```

## Appendix B: Files to Move

```bash
# Root → docs/
mv IMPLEMENTATION_SUMMARY_NEMOTRON_OPENCODE.md docs/internal/
mv SETUP_SCRIPT_README.md docs/internal/

# Root → tests/
mv test_dev_integration.sh tests/
mv test_opencode_setup.sh tests/

# Root → archived/
mv opencode_demo.sh archived/
```

## Appendix C: Documentation Source Mapping

Where existing content goes in the new docs site:

| Source File | Target in MkDocs | Action |
|-------------|-----------------|--------|
| `README.md` | Complete rewrite → `docs/index.md` + root README | Rewrite |
| `CONTRIBUTING.md` | `docs/contributing.md` | Move |
| `CHANGELOG.md` | `docs/reference/changelog.md` | Move |
| `AGENTS.md` | Keep in root (Copilot/agent instruction file) | Keep |
| `SOUL.md`, `IDENTITY.md`, `USER.md`, `HEARTBEAT.md`, `TOOLS.md` | Keep in root (agent files) | Keep |
| `docs/research/REMOTE_ACCESS_NEW.md` | `docs/guides/remote-access.md` | Consolidate |
| `docs/research/REMOTE_QUICK_REFERENCE.md` | Merge into above | Delete |
| `docs/research/REMOTE_JOB_SUBMISSION.md` | Merge into above | Delete |
| `docs/MLFLOW_VERIFICATION.md` | `docs/guides/mlflow.md` | Consolidate |
| `docs/MLFLOW_GOVERNANCE_RESEARCH.md` | `docs/research/` archive | Archive |
| `docs/internal/MLFLOW_GOVERNANCE_ANALYSIS.md` | `docs/research/` archive | Archive |
| `docs/GRAFANA_*.md` | `docs/guides/monitoring.md` | Consolidate |
| `docs/ARCHITECTURE_REDESIGN.md` | `docs/architecture/index.md` | Consolidate |
| `docs/internal/ARCHITECTURE.md` | Merge into above | Delete |
| `docs/internal/TROUBLESHOOTING.md` | `docs/guides/troubleshooting.md` | Move |
| `docs/PLATFORM_IMPROVEMENTS_PROJECT_BOARD.md` | GitHub Issues + delete | Delete |
| `openclaw/research/learning_series/PART*.md` | `docs/learning/part*.md` | Copy/link |
| `openclaw/research/learning_series/CHEATSHEET*.md` | `docs/learning/cheatsheet*.md` | Copy/link |

## Appendix D: Root Directory Target State

After cleanup, the root should contain only:

```
shml-platform/
├── README.md                    # Clean, concise entry point
├── LICENSE
├── CHANGELOG.md                 # Symlink → docs/reference/changelog.md
├── CONTRIBUTING.md              # Symlink → docs/contributing.md  
├── CODE_OF_CONDUCT.md
├── AGENTS.md                    # Agent instruction file
├── SOUL.md                      # Agent persona
├── IDENTITY.md                  # Agent identity
├── USER.md                      # Agent user context
├── HEARTBEAT.md                 # Agent heartbeat
├── TOOLS.md                     # Agent tools
├── mkdocs.yml                   # Docs site config
├── docker-compose.yml           # Main compose (include-based)
├── docker-compose.infra.yml     # Infrastructure services
├── docker-compose.dev.yml       # Dev overrides
├── docker-compose.secrets.yml   # Secrets overlay
├── docker-compose.tracing.yml   # Tracing overlay
├── docker-compose.logging.yml   # Logging overlay
├── .env                         # Environment config
├── .env.example                 # Template
├── .gitignore
├── setup.sh                     # One-time setup
├── start_all_safe.sh            # Production start
├── start_all_dev.sh             # Dev mode start
├── stop_all.sh                  # Stop all services
├── stop_dev.sh                  # Stop dev services
├── check_platform_status.sh     # Health check
├── run_tests.sh                 # Test runner
├── ml-platform.service          # Systemd service
├── shml-platform.service        # Systemd service
├── .github/                     # CI/CD workflows
├── archived/                    # Legacy code (gitignored in docs)
├── backups/                     # Gitignored
├── config/                      # Platform + profile configs
├── data/                        # Gitignored model/data files
├── docs/                        # MkDocs source directory
├── inference/                   # Inference services
├── libs/                        # Platform libraries + admin client
├── logs/                        # Gitignored  
├── mlflow-server/               # MLflow compose + config
├── monitoring/                  # Grafana, Prometheus, exporters
├── oauth2-proxy/                # OAuth proxy config
├── postgres/                    # DB init scripts
├── ray_compute/                 # Ray cluster + training jobs
├── runs/                        # Gitignored training runs
├── scripts/                     # Utility scripts
├── sdk/                         # SHML SDK package
├── secrets/                     # Gitignored secrets
└── tests/                       # All test files
```

**Removed from root:** `BOOTSTRAP.md`, `SETUP_SCRIPT_README.md`, `IMPLEMENTATION_SUMMARY_NEMOTRON_OPENCODE.md`, `docker-compose.yml.bak-include`, `opencode_demo.sh`, `test_dev_integration.sh`, `test_opencode_setup.sh`, `opencode_demo.sh`, `evaluation_results.json`
