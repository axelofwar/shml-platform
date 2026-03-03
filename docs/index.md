---
hide:
  - navigation
---

# SHML Platform

**Self-Hosted ML Platform** — GPU-optimized training, experiment tracking, model registry, and agentic development on your own hardware.

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } __Quick Start__

    ---

    Get the platform running in 5 minutes.

    [:octicons-arrow-right-24: Getting Started](getting-started/quickstart.md)

-   :material-console:{ .lg .middle } __SDK & CLI__

    ---

    Train models with one command: `shml train --profile balanced`

    [:octicons-arrow-right-24: SDK Reference](sdk/index.md)

-   :material-chart-line:{ .lg .middle } __Monitoring__

    ---

    Grafana dashboards, Prometheus metrics, SLO tracking.

    [:octicons-arrow-right-24: Monitoring Guide](guides/monitoring.md)

-   :material-lock:{ .lg .middle } __Architecture__

    ---

    Service topology, auth flows, Docker Compose organization.

    [:octicons-arrow-right-24: Architecture](architecture/index.md)

</div>

## What You Get

| Capability | Technology | Status |
|-----------|-----------|--------|
| **Experiment Tracking** | MLflow 2.x + PostgreSQL | :white_check_mark: Production |
| **Distributed Training** | Ray 2.35 + multi-GPU | :white_check_mark: Production |
| **Data Versioning** | Nessie + Apache Iceberg | :white_check_mark: Production |
| **Dataset Visualization** | FiftyOne | :white_check_mark: Production |
| **Feature Store** | Spark-backed feature extraction | :white_check_mark: Available |
| **Monitoring** | Grafana + Prometheus + SLOs | :white_check_mark: Production |
| **Auth & RBAC** | FusionAuth + OAuth2-Proxy (4-tier) | :white_check_mark: Production |
| **Model Registry** | MLflow Model Registry | :white_check_mark: Production |
| **GPU Management** | Yield/Reclaim lifecycle | :white_check_mark: Production |
| **Object Detection** | YOLOv8/11 fine-tuning pipeline | :white_check_mark: Production |

## Latest Training Results

!!! success "Phase 8 Integrated Training (5 epochs)"
    | Metric | Value |
    |--------|-------|
    | mAP50 | **0.812** |
    | mAP50-95 | **0.413** |
    | Precision | **0.891** |
    | Recall | **0.738** |

    All integrations verified: MLflow logging, Nessie branching, FiftyOne dataset, Prometheus metrics.

## Hardware

| Component | Spec |
|-----------|------|
| CPU | AMD Ryzen 9 3900X (12C/24T) |
| GPU 0 | NVIDIA RTX 3090 Ti (24GB) — Training |
| GPU 1 | NVIDIA RTX 2070 (8GB) — Inference |
| RAM | 64 GB DDR4 |
| Storage | 2 TB NVMe |
