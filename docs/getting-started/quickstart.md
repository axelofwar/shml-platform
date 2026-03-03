# Quick Start

Go from zero to a completed training run in under five minutes.

!!! info "Prerequisites"

    This guide assumes you have already completed the [Installation](installation.md) steps
    and all platform services are running.

---

## 1. Start the Platform

If the platform isn't already running:

```bash
cd shml-platform
./start_all_safe.sh
```

`start_all_safe.sh` brings services up in dependency order and waits for
health checks — safe to run repeatedly.

Verify everything is healthy:

```bash
docker compose ps
```

---

## 2. Install the SDK

The SHML SDK gives you the `shml` CLI and Python client library:

```bash
pip install -e sdk/
```

Confirm it's working:

```bash
shml --version
shml platform status
```

!!! tip "Virtual environment"

    Consider installing into a dedicated virtualenv:

    ```bash
    python3 -m venv .venv && source .venv/bin/activate
    pip install -e sdk/
    ```

---

## 3. Run Your First Training Job

Launch a quick sanity-check training run using the built-in `quick-test` profile
(2 epochs, 640 px, light augmentation):

=== "CLI"

    ```bash
    shml train --profile quick-test
    ```

=== "Python"

    ```python
    from shml.config import JobConfig

    job = JobConfig.from_profile("quick-test")
    print(job.training.epochs)   # 2
    print(job.training.imgsz)    # 640
    ```

The `quick-test` profile is designed to validate the full pipeline —
MLflow logging, Nessie branching, and Prometheus metrics — in a few minutes.

### Override Parameters on the Fly

```bash
# Run quick-test but with 1 epoch and batch size 16
shml train --profile quick-test --epochs 1 --batch 16
```

---

## 4. Check Results

### Platform Status

```bash
shml platform status
```

Shows running services, GPU utilisation, and active training jobs.

### MLflow UI

Open **[http://localhost:5000](http://localhost:5000)** to see:

- Experiment runs with logged metrics (mAP, loss curves)
- Model artifacts and checkpoints
- Parameter comparison across runs

### Ray Dashboard

Open **[http://localhost:8265](http://localhost:8265)** to monitor:

- Active / pending Ray tasks
- GPU and CPU resource usage
- Worker logs

### Grafana Dashboards

Open **[http://localhost:3000](http://localhost:3000)** (default creds in `CREDENTIALS.txt`):

- **Training Overview** — real-time loss & mAP plots pushed via Prometheus Pushgateway
- **GPU Metrics** — utilisation, memory, temperature
- **Platform Health** — container status, request latency

---

## 5. Next Steps

| Goal | Command / Resource |
|------|--------------------|
| Full 10-epoch production run | `shml train --profile balanced` |
| Customise hyperparameters | See [Configuration](configuration.md) |
| Fine-tune from a checkpoint | `shml train --profile balanced --checkpoint runs/best.pt` |
| View available profiles | `ls config/profiles/` |
| Submit a remote job | See [Remote Job Submission](../guides/remote-access.md) |

!!! success "Done!"

    You've started the platform, run a training job, and inspected results.
    Head to [Configuration](configuration.md) to learn how to tune profiles
    and platform settings.
