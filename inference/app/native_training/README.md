# Native Training System (Option 6: Hybrid Native Training + Docker Inference)

## Architecture Overview

This system implements **Option 6** from our architecture analysis - running training natively on the host
while keeping inference in Docker containers. This solves the MPS (Multi-Process Service) conflict that
causes `torch.cuda.is_available()` to hang in Docker containers.

### Why This Approach?

**Problem Discovered:**
- MPS daemon runs at `/tmp/nvidia-mps` on host (PID 1493 control, 54070 server)
- MPS with 100% thread allocation blocks ALL new CUDA context initialization
- `torch.cuda.is_available()` hangs for ANY process (Docker or native) when MPS is active
- This includes inference containers AND native training processes

**Solution:**
- Set `CUDA_MPS_PIPE_DIRECTORY=""` to bypass MPS for training
- Training runs with direct CUDA access (no MPS)
- Inference continues using MPS for efficient multi-model serving
- Signal-based pause/resume coordinates GPU time-sharing

## Security Model

### Bubblewrap Sandboxing

Training runs in a bubblewrap sandbox with:
- **Filesystem isolation**: Read-only root, bind mounts only for required paths
- **GPU device access**: `/dev/nvidia*` passed through
- **Network restriction**: Only Docker bridge network (172.30.0.0/16)
- **No privilege escalation**: `--unshare-user`, `--new-session`
- **Process isolation**: Separate PID namespace

### Network Access

The sandbox can ONLY reach:
- `172.30.0.5:5432` - Postgres (shml-postgres)
- `172.30.0.11:5000` - MLflow (mlflow-server)
- `172.30.0.15:8265` - Ray dashboard (optional, for status)

### Resource Limits

Via systemd unit:
- `MemoryMax=58G` (leaves 6GB for system)
- `CPUQuota=800%` (8 cores max)
- `IOWeight=50` (deprioritize disk vs inference)

## Components

### 1. `training_coordinator.py`
Main coordinator that manages training lifecycle:
- Monitors inference queue for pause triggers
- Sends SIGUSR1 to pause training
- Sends SIGUSR2 to resume training
- Validates checkpoints before resuming

### 2. `native_trainer.py`
SOTA training script implementing:
- Multi-scale training (640 → 960 → 1280)
- AdamW optimizer with cosine LR
- Label smoothing (0.1)
- Close mosaic (last 10 epochs)
- Gradient checkpointing for memory efficiency
- MLflow experiment tracking
- Signal handlers for graceful pause/resume

### 3. `sandbox_training.sh`
Bubblewrap wrapper for secure training execution:
```bash
bwrap --ro-bind / / \
      --bind $CHECKPOINT_DIR $CHECKPOINT_DIR \
      --bind $DATA_DIR $DATA_DIR \
      --dev-bind /dev/nvidia0 /dev/nvidia0 \
      --dev-bind /dev/nvidia-uvm /dev/nvidia-uvm \
      --dev-bind /dev/nvidiactl /dev/nvidiactl \
      --unshare-pid \
      --new-session \
      python3 native_trainer.py "$@"
```

### 4. `shml-training.service`
Systemd service file for training management:
```ini
[Service]
Type=notify
ExecStart=/path/to/sandbox_training.sh
MemoryMax=58G
CPUQuota=800%
```

## Integration Points

### MLflow (verified working ✓)
```python
MLFLOW_TRACKING_URI = "http://172.30.0.11:5000"
# Requires Host header: "Host: mlflow-server"
```

### Postgres (verified working ✓)
```python
POSTGRES_HOST = "172.30.0.5"
POSTGRES_DB = "mlflow_db"
POSTGRES_USER = "mlflow"
# Password from secrets/shared_db_password.txt
```

### Inference Coordinator
Training checks queue status via REST API:
```
GET http://localhost:8000/queue/status
Response: {"pending": 3, "processing": 1, "avg_wait_time": 45.2}
```

## Pause/Resume Protocol

### Trigger Conditions
Training pauses when inference queue shows:
- `pending >= 3` requests, OR
- `avg_wait_time >= 30` seconds

### Signal Flow
```
1. Coordinator detects queue pressure
2. Coordinator sends SIGUSR1 to training process
3. Training saves checkpoint + state to disk
4. Training releases GPU memory (del model, torch.cuda.empty_cache())
5. MPS-based inference handles queue
6. Queue clears (pending=0, avg_wait=0)
7. Coordinator sends SIGUSR2 to training
8. Training reloads from checkpoint, resumes
```

### Checkpoint Format
```
checkpoints/
├── latest.pt                 # Symlink to newest
├── epoch_15_step_1234.pt     # Model weights
├── epoch_15_step_1234_state.json  # Training state
└── epoch_15_step_1234_optimizer.pt # Optimizer state
```

## Usage

### Start Training
```bash
# Via systemd (recommended)
sudo systemctl start shml-training

# Manual (for testing)
./sandbox_training.sh --model yolov8n.pt --data wider_face.yaml --epochs 100
```

### Monitor Training
```bash
# Training logs
journalctl -u shml-training -f

# MLflow UI
open https://${PUBLIC_DOMAIN}/mlflow/

# Coordinator status
curl http://localhost:8000/training/status
```

### Manual Pause/Resume
```bash
# Pause (for maintenance)
sudo systemctl kill -s SIGUSR1 shml-training

# Resume
sudo systemctl kill -s SIGUSR2 shml-training
```

## Data Management

Training expects data at:
- `/opt/shml-platform/data/training/`
  - `wider_face/` - WIDER FACE dataset (auto-downloaded)
  - `custom/` - Custom training data

Checkpoints stored at:
- `/opt/shml-platform/data/checkpoints/`

## Backup Integration

Postgres backup continues working:
```bash
# Existing backup script works unchanged
./scripts/backup_postgres.sh
```

The training coordinator doesn't interfere with Docker services.
