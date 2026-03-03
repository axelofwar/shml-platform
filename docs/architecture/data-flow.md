# Data Flow

How data moves through the SHML Platform — from dataset upload to trained model.

---

## End-to-End Training Flow

```mermaid
graph LR
    subgraph Input["Data Input"]
        Dataset["YOLO Dataset<br/>(data.yaml)"]
        Weights["Pretrained Weights<br/>(yolo11x.pt)"]
    end

    subgraph Compute["Ray Cluster"]
        RayAPI["Ray Compute API"]
        RayHead["Ray Head Node<br/>(GPU 0 + GPU 1)"]
    end

    subgraph Tracking["Experiment Tracking"]
        MLflow["MLflow Server"]
        Registry["Model Registry"]
        Artifacts["Artifact Store<br/>(/mlflow/artifacts)"]
    end

    subgraph Monitoring["Observability"]
        Pushgateway["Pushgateway"]
        Prometheus["Prometheus"]
        Grafana["Grafana Dashboards"]
    end

    Dataset --> RayAPI
    Weights --> RayHead
    RayAPI -->|Submit Job| RayHead
    RayHead -->|Metrics per epoch| MLflow
    RayHead -->|Training metrics| Pushgateway
    MLflow --> Registry
    MLflow --> Artifacts
    Pushgateway --> Prometheus
    Prometheus --> Grafana
```

---

## Checkpoint Flow

Training checkpoints follow a dual-storage strategy: fast local writes during training with asynchronous sync to MLflow.

```mermaid
sequenceDiagram
    participant T as Training Job
    participant L as Local Disk<br/>/tmp/ray/checkpoints
    participant M as MLflow<br/>Model Registry
    participant A as Artifact Store<br/>/mlflow/artifacts

    T->>L: Save checkpoint (every epoch)
    T->>L: Save best.pt (on improvement)
    T-->>M: Async: Register model version
    T-->>A: Async: Upload weights + metadata
    Note over L: Fast I/O during training
    Note over M,A: Background sync — no training overhead

    T->>M: End of training: register final model
    M->>A: Store final artifacts
```

**Local checkpoint structure:**

```
/tmp/ray/
├── checkpoints/
│   ├── epoch_001/weights/best.pt
│   ├── epoch_002/weights/best.pt
│   └── ...
└── data/
    └── wider_face_yolo/
        ├── data.yaml
        ├── train/images/
        └── val/images/
```

---

## Dataset Flow

YOLO datasets are mounted into the Ray container and referenced by `data.yaml`.

```mermaid
graph TD
    subgraph Host["Host Filesystem"]
        DataYaml["data.yaml"]
        TrainImages["train/images/ + labels/"]
        ValImages["val/images/ + labels/"]
    end

    subgraph Ray["Ray Container"]
        Volume["/tmp/ray/data/"]
        Worker["Training Worker"]
        Loader["DataLoader<br/>(workers=4)"]
    end

    DataYaml -->|Volume mount| Volume
    TrainImages -->|Volume mount| Volume
    ValImages -->|Volume mount| Volume
    Volume --> Loader
    Loader -->|Augmented batches| Worker
```

!!! note "Dataset Configuration"
    The `data.yaml` path is set in `TrainingConfig.data_yaml` (default: `/tmp/ray/data/wider_face_yolo/data.yaml`). The SDK and CLI both accept this as a parameter.

---

## Metrics Flow

Training metrics flow to three destinations simultaneously:

```mermaid
graph LR
    Job["Training Job"]

    Job -->|"log_metric()"| MLflow["MLflow<br/>(experiment history)"]
    Job -->|"push_to_gateway()"| Push["Pushgateway<br/>(real-time gauges)"]
    Job -->|"ray.train.report()"| RayDash["Ray Dashboard<br/>(job status)"]

    Push --> Prom["Prometheus"]
    Prom --> Grafana["Grafana"]
    MLflow --> GrafanaMLflow["Grafana<br/>(MLflow datasource)"]
```

| Destination | What it captures | Retention |
|------------|-----------------|-----------|
| MLflow | Epoch-level metrics (loss, mAP50, recall, precision) | Permanent |
| Pushgateway → Prometheus | Real-time training gauges (GPU util, VRAM, cost) | 90 days |
| Ray Dashboard | Job status, logs, runtime metadata | Session |

---

## Model Promotion Flow

After training completes, models move through the registry:

```mermaid
stateDiagram-v2
    [*] --> Training: Submit job
    Training --> Checkpoint: Save best.pt
    Checkpoint --> Registered: Register in MLflow
    Registered --> Staging: Manual promotion
    Staging --> Production: Validation passed
    Production --> Archived: Newer model promoted
```

!!! info "Model Naming"
    The default model name in the registry is `face-detection-yolov8l-p2` (set via `MLFLOW_REGISTRY_MODEL_NAME` in `config/platform.env`).

---

## Data Lifecycle

| Data Type | Location | Persistent? | Backed Up? |
|-----------|----------|:-----------:|:----------:|
| Training datasets | `/tmp/ray/data/` (volume) | Yes | No (re-downloadable) |
| Checkpoints (during training) | `/tmp/ray/checkpoints/` | Yes | Via MLflow sync |
| MLflow artifacts | `/mlflow/artifacts/` (bind mount) | Yes | Yes |
| MLflow metadata | PostgreSQL `mlflow_db` | Yes | Yes (every 6h) |
| Prometheus metrics | `global-prometheus-data` volume | Yes | No |
| Grafana dashboards | `unified-grafana-data` volume | Yes | No (provisioned from files) |
