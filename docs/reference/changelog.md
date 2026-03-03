# Changelog

Notable changes to the SHML Platform. Full history is in `CHANGELOG.md` at the project root.

---

## v2.0 — Platform Modernization (2026-02)

### Added

- **Python SDK (`shml`)** — `pip install` client for remote job submission, status polling, and model management
- **CLI tool (`shml`)** — Command-line interface for auth, job management, and API key operations
- **MkDocs Material documentation** — Structured docs site replacing flat Markdown files
- **Nessie catalog** — Apache Iceberg version control for datasets
- **FiftyOne** — CV dataset curation and visualization
- **Infisical** — Self-hosted secrets manager
- **Multi-model orchestration** — Vision (Qwen3-VL) + Coding pipeline
- **ACE-based agent service** — Agentic context engineering with composable skills
- **4-tier RBAC** — viewer / developer / elevated-developer / admin roles

### Changed

- Consolidated monitoring (4 containers → 2: single Prometheus + Grafana)
- Consolidated PostgreSQL (3 instances → 1 shared instance, ~1 GB RAM saved)
- Repository reorganization: modular `jobs/{training,evaluation,annotation,utils}` structure
- Authentication migrated from Authentik to FusionAuth

---

## v0.4.1 — Phase 1 Training Ready (2025-12-12)

### Added

- Phase 1 expert pre-training analysis (hardware budget, OOM risk, SOTA features)
- Training launch script (`scripts/launch_phase1_training.sh`)
- EMA (Exponential Moving Average) support for +2-3% mAP50

---

## v0.4.0 — Production Readiness (2025-12-12)

### Added

- 41-check production readiness verification (100% pass rate)
- Dual storage architecture (local checkpoints + MLflow registry)
- `DualStorageManager` and `MLflowHelper` utility classes

---

## v0.3.0 — FusionAuth Migration (2025-12-01)

### Changed

- Migrated from Authentik to FusionAuth for OAuth/SSO
- Added Google, GitHub, Twitter OAuth providers
- Configured Tailscale Funnel for public HTTPS access

---

## v0.1.0 — Initial Release (2025-11-23)

### Added

- MLflow 2.9.2 tracking server with PostgreSQL backend
- Ray 2.9.0-gpu cluster with CUDA support
- Traefik v2.10 API gateway
- FusionAuth OAuth provider
- Prometheus + Grafana monitoring
- Phased startup script (`start_all_safe.sh`)
- 12 core documentation files
