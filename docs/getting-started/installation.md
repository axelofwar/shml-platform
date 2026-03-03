# Installation

Get the SHML Platform running on your machine with GPU-accelerated ML training,
experiment tracking, and full observability.

---

## Prerequisites

### Hardware

| Component | Minimum           | Recommended              |
|-----------|-------------------|--------------------------|
| GPU       | NVIDIA GTX 1080   | NVIDIA RTX 3090 Ti 24 GB |
| RAM       | 16 GB             | 32 GB+                   |
| Disk      | 50 GB free        | 100 GB+ (datasets + artifacts) |
| CPU       | 4 cores           | 8+ cores                 |

### Software

!!! warning "Required before you begin"

    All of the following must be installed and functional before running `setup.sh`.

- **Docker Engine** ≥ 24.0 with Compose V2 (`docker compose`)
- **NVIDIA Driver** ≥ 535 (`nvidia-smi` should show your GPU)
- **NVIDIA Container Toolkit** — enables GPU passthrough to containers
- **Git** and **Python 3.11+**
- **curl** and **openssl** (used by setup script)

Verify your prerequisites:

```bash
# Docker
docker --version && docker compose version

# NVIDIA driver + GPU visibility
nvidia-smi

# NVIDIA Container Toolkit
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi

# Python
python3 --version
```

---

## Clone the Repository

```bash
git clone https://github.com/your-org/shml-platform.git
cd shml-platform
```

---

## Run the Setup Script

The interactive `setup.sh` script handles end-to-end provisioning:

```bash
./setup.sh
```

### What `setup.sh` Does

The script runs through these phases automatically:

=== "1. Dependency Checks"

    Verifies Docker, Docker Compose, NVIDIA drivers, NVIDIA Container Toolkit,
    and required CLI tools (`curl`, `openssl`, etc.) are present on the system.

=== "2. Secrets & Credentials"

    Generates (or prompts you for) secure passwords for:

    - PostgreSQL (MLflow metadata store)
    - Redis (caching / task broker)
    - Grafana admin
    - FusionAuth admin
    - MLflow proxy auth

    Credentials are saved to `secrets/` files (one secret per file, git-ignored)
    and summarised in `CREDENTIALS.txt` for your reference.

=== "3. Environment Configuration"

    Writes `config/platform.env` with service-discovery variables
    (hostnames, ports, URIs) that map 1:1 to future Kubernetes ConfigMaps.

=== "4. Docker Compose Up"

    Pulls images and starts services in dependency order:

    1. **Infrastructure** — Traefik, PostgreSQL, Redis
    2. **Auth** — FusionAuth, OAuth2 Proxy
    3. **ML Services** — MLflow, Ray Head + Workers, Nessie, FiftyOne
    4. **Observability** — Prometheus, Grafana, Loki, Tempo, OTEL Collector

=== "5. Health Verification"

    Waits for each service to become healthy and reports status.

!!! tip "Re-running is safe"

    `setup.sh` is idempotent — it detects existing secrets and running containers,
    skipping steps that are already complete.

---

## Verifying Installation

After `setup.sh` finishes, confirm everything is up:

```bash
# Quick container check
docker compose ps

# Platform status via the CLI (after SDK install)
pip install -e sdk/
shml platform status
```

### Service Endpoints

| Service        | URL                          |
|----------------|------------------------------|
| MLflow UI      | `http://localhost:5000`       |
| Ray Dashboard  | `http://localhost:8265`       |
| Grafana        | `http://localhost:3000`       |
| FiftyOne       | `http://localhost:5151`       |
| Prometheus     | `http://localhost:9090`       |
| FusionAuth     | `http://localhost:9011`       |
| Traefik        | `http://localhost:8080`       |

!!! success "You're ready"

    If all containers show **Up (healthy)** and you can reach MLflow at
    `http://localhost:5000`, proceed to the [Quick Start](quickstart.md).

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `nvidia-smi` not found | Install NVIDIA driver ≥ 535 |
| GPU not visible in containers | Install NVIDIA Container Toolkit, restart Docker |
| Port conflict on 5000/3000/etc. | Stop the conflicting service or edit port mappings in `docker-compose.yml` |
| OAuth2 Proxy unhealthy | Expected — its scratch image has no shell; Traefik uses "running" status instead |

See [TROUBLESHOOTING.md](../guides/troubleshooting.md) for the full guide.
