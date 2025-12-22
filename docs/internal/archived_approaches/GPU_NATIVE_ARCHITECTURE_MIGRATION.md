# GPU Native Architecture Migration Plan

## Executive Summary

This document outlines the migration from Docker-containerized GPU workloads to a hybrid native/VM architecture that maximizes flexibility, enables full sudo/docker capabilities per tier, and optimizes dual-GPU utilization using FSDP, DeepSpeed, and advanced GPU sharing frameworks.

---

## Current State Analysis

### GPU Resources
| GPU | Model | VRAM | IOMMU Group | Current Use |
|-----|-------|------|-------------|-------------|
| GPU 0 | RTX 3090 Ti | 24GB | Group 27 (clean) | Primary coding model (22.6GB) |
| GPU 1 | RTX 2070 | 8GB | Group 28 (clean) | Fallback model (7.5GB) |

### Current Containerized Services Using GPUs

| Service | Container | GPU | Memory | Purpose |
|---------|-----------|-----|--------|---------|
| `coding-model-primary` | vLLM | GPU 0 | 22.6GB | Qwen2.5-Coder-32B |
| `coding-model-fallback` | vLLM | GPU 1 | 6GB | Qwen2.5-Coder-3B |
| `ray-head` | Ray | GPU 0,1 | Minimal | Ray cluster coordinator |

### Services NOT Using GPUs (Keep Containerized)
- Traefik, PostgreSQL, Redis, FusionAuth, OAuth2-Proxy
- MLflow server, Prometheus, Grafana
- Chat API, Chat UI, Homer dashboard
- Infisical, role-auth, dozzle

---

## Target Architecture

### Tiered Access Model

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              SHML Platform - GPU Access Tiers                        │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │
│  │   VIEWER    │  │  DEVELOPER  │  │  ELEVATED   │  │    ADMIN    │                 │
│  │             │  │             │  │  DEVELOPER  │  │             │                 │
│  ├─────────────┤  ├─────────────┤  ├─────────────┤  ├─────────────┤                 │
│  │ Sandbox:    │  │ Sandbox:    │  │ Sandbox:    │  │ Access:     │                 │
│  │ Bubblewrap  │  │ Bubblewrap  │  │ MicroVM/    │  │ Native/     │                 │
│  │             │  │             │  │ Full VM     │  │ Full VM     │                 │
│  ├─────────────┤  ├─────────────┤  ├─────────────┤  ├─────────────┤                 │
│  │ GPU: None   │  │ GPU: Shared │  │ GPU: Shared │  │ GPU: Full   │                 │
│  │ (API only)  │  │ via MPS     │  │ via MPS/    │  │ Passthrough │                 │
│  │             │  │ Max 2GB     │  │ FSDP/DS     │  │ OR Native   │                 │
│  │             │  │             │  │ Max 16GB    │  │             │                 │
│  ├─────────────┤  ├─────────────┤  ├─────────────┤  ├─────────────┤                 │
│  │ Network:    │  │ Network:    │  │ Network:    │  │ Network:    │                 │
│  │ None        │  │ Filtered    │  │ NAT         │  │ Full        │                 │
│  ├─────────────┤  ├─────────────┤  ├─────────────┤  ├─────────────┤                 │
│  │ Docker: No  │  │ Docker: No  │  │ Docker: Yes │  │ Docker: Yes │                 │
│  │ Sudo: No    │  │ Sudo: No    │  │ Sudo: In VM │  │ Sudo: Full  │                 │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘                 │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## GPU Sharing & Multi-Tenant Strategies

### Option A: NVIDIA MPS (Multi-Process Service) - Current Partial Use

**How it works:** MPS enables multiple CUDA applications to share a single GPU context, reducing context switching overhead.

```
┌─────────────────────────────────────────────────────────────────┐
│                    NVIDIA MPS Architecture                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                   MPS Control Daemon                     │    │
│  │                 (runs on each GPU)                       │    │
│  └───────────────────────┬─────────────────────────────────┘    │
│                          │                                       │
│    ┌─────────────────────┼─────────────────────┐                │
│    │                     │                     │                │
│    ▼                     ▼                     ▼                │
│  ┌─────────┐       ┌─────────┐       ┌─────────┐               │
│  │ Client 1│       │ Client 2│       │ Client N│               │
│  │ (vLLM)  │       │ (Ray)   │       │ (Train) │               │
│  │ 50% GPU │       │ 30% GPU │       │ 20% GPU │               │
│  └─────────┘       └─────────┘       └─────────┘               │
│                                                                  │
│  Benefits:                                                       │
│  - Fine-grained GPU sharing (percent-based)                     │
│  - Reduced context switching overhead                           │
│  - Works with existing CUDA applications                        │
│                                                                  │
│  Limitations:                                                    │
│  - All clients must use same CUDA version                       │
│  - Memory isolation is advisory, not enforced                   │
│  - One fault crashes all clients                                │
└─────────────────────────────────────────────────────────────────┘
```

**Configuration:**
```bash
# Start MPS daemon for GPU 0 (3090 Ti)
export CUDA_VISIBLE_DEVICES=0
export CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps-0
export CUDA_MPS_LOG_DIRECTORY=/tmp/nvidia-mps-log-0
nvidia-cuda-mps-control -d

# Set memory limits per client
echo "set_default_active_thread_percentage 50" | nvidia-cuda-mps-control
```

### Option B: NVIDIA MIG (Multi-Instance GPU) - NOT Available

**Status:** RTX 3090 Ti and RTX 2070 do NOT support MIG (requires A100/H100).

### Option C: Time-Slicing (vGPU) - Available but Limited

**How it works:** NVIDIA's time-slicing allows multiple VMs/containers to share GPU time.

```yaml
# nvidia-device-plugin ConfigMap for Kubernetes (or native)
sharing:
  timeSlicing:
    resources:
    - name: nvidia.com/gpu
      replicas: 4  # Create 4 virtual GPUs from 1 physical
```

**Limitations:**
- No memory isolation
- Context switching overhead
- Not ideal for latency-sensitive inference

### Option D: FSDP (Fully Sharded Data Parallel) - For Training

**How it works:** PyTorch FSDP shards model parameters, gradients, and optimizer states across GPUs.

```
┌─────────────────────────────────────────────────────────────────┐
│                    FSDP Multi-GPU Training                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌───────────────────────┐     ┌───────────────────────┐        │
│  │      GPU 0 (3090)     │     │      GPU 1 (2070)     │        │
│  │                       │     │                       │        │
│  │  ┌─────────────────┐  │     │  ┌─────────────────┐  │        │
│  │  │ Model Shard 1   │  │◄───►│  │ Model Shard 2   │  │        │
│  │  │ (layers 0-15)   │  │     │  │ (layers 16-31)  │  │        │
│  │  └─────────────────┘  │     │  └─────────────────┘  │        │
│  │                       │     │                       │        │
│  │  ┌─────────────────┐  │     │  ┌─────────────────┐  │        │
│  │  │ Optimizer Shard │  │◄───►│  │ Optimizer Shard │  │        │
│  │  │ (params 0-50%)  │  │     │  │ (params 50-100%)│  │        │
│  │  └─────────────────┘  │     │  └─────────────────┘  │        │
│  │                       │     │                       │        │
│  │  Available: 24GB      │     │  Available: 8GB       │        │
│  └───────────────────────┘     └───────────────────────┘        │
│                                                                  │
│  Use Case: Fine-tuning models up to ~70B parameters             │
│  Note: Asymmetric VRAM (24GB + 8GB = 32GB effective)            │
└─────────────────────────────────────────────────────────────────┘
```

**PyTorch FSDP Configuration:**
```python
from torch.distributed.fsdp import FullyShardedDataParallel as FSDP
from torch.distributed.fsdp import ShardingStrategy

# Optimal for asymmetric GPUs (24GB + 8GB)
model = FSDP(
    model,
    sharding_strategy=ShardingStrategy.FULL_SHARD,
    device_id=torch.cuda.current_device(),
    # Limit memory on smaller GPU
    limit_all_gathers=True,
)
```

### Option E: DeepSpeed ZeRO - For Training

**How it works:** DeepSpeed ZeRO progressively shards optimizer states, gradients, and parameters.

```
┌─────────────────────────────────────────────────────────────────┐
│                    DeepSpeed ZeRO Stages                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ZeRO-1: Optimizer State Sharding                               │
│  ├── Each GPU holds 1/N of optimizer states                     │
│  └── Memory: ~4x reduction in optimizer memory                  │
│                                                                  │
│  ZeRO-2: + Gradient Sharding                                    │
│  ├── Gradients sharded across GPUs                              │
│  └── Memory: ~8x reduction                                      │
│                                                                  │
│  ZeRO-3: + Parameter Sharding (Recommended)                     │
│  ├── Model parameters sharded                                   │
│  ├── Parameters gathered on-demand during forward/backward      │
│  └── Memory: Linear scaling with # GPUs                         │
│                                                                  │
│  ZeRO-Offload: CPU/NVMe offloading                              │
│  ├── Offload optimizer states to CPU RAM                        │
│  └── With 64GB RAM: Train ~100B+ models on 2 GPUs!              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**DeepSpeed Config for Dual-GPU (asymmetric):**
```json
{
  "train_batch_size": 8,
  "gradient_accumulation_steps": 4,
  "zero_optimization": {
    "stage": 3,
    "offload_optimizer": {
      "device": "cpu",
      "pin_memory": true
    },
    "offload_param": {
      "device": "cpu",
      "pin_memory": true
    },
    "overlap_comm": true,
    "contiguous_gradients": true,
    "reduce_bucket_size": 5e7,
    "stage3_prefetch_bucket_size": 5e7,
    "stage3_param_persistence_threshold": 1e5
  },
  "fp16": {
    "enabled": true,
    "auto_cast": true
  }
}
```

### Option F: vLLM Tensor Parallelism - For Inference

**How it works:** vLLM can split model layers across multiple GPUs for inference.

```
┌─────────────────────────────────────────────────────────────────┐
│              vLLM Tensor Parallelism (TP=2)                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                      Single Model                          │ │
│  │              (e.g., Qwen2.5-Coder-32B)                      │ │
│  └──────────────────────────┬─────────────────────────────────┘ │
│                             │                                    │
│            ┌────────────────┴────────────────┐                  │
│            │       Tensor Split              │                  │
│            ▼                                 ▼                  │
│  ┌─────────────────────┐       ┌─────────────────────┐         │
│  │      GPU 0          │       │      GPU 1          │         │
│  │    (3090 Ti)        │       │    (2070)           │         │
│  │                     │       │                     │         │
│  │  Attention heads    │       │  Attention heads    │         │
│  │  0-31 (50%)         │◄─────►│  32-63 (50%)        │         │
│  │                     │ NVLink│                     │         │
│  │  MLP neurons        │  or   │  MLP neurons        │         │
│  │  0-50%              │ PCIe  │  50-100%            │         │
│  │                     │       │                     │         │
│  │  ~12GB usage        │       │  ~12GB usage        │         │
│  └─────────────────────┘       └─────────────────────┘         │
│                                                                  │
│  Note: Without NVLink, PCIe bandwidth limits performance        │
│  Your setup: PCIe 4.0 x16 - ~32GB/s bidirectional               │
│  Recommendation: Use pipeline parallelism instead for           │
│  asymmetric GPUs (24GB + 8GB)                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Problem with TP on Asymmetric GPUs:**
- Tensor parallelism requires equal VRAM splits
- 24GB + 8GB = can only use 8GB each = 16GB total (wasteful)
- Better approach: Pipeline Parallelism or separate models

---

## Recommended Architecture by Service

### 1. Inference Services (coding-model)

| Current | Recommended | Rationale |
|---------|-------------|-----------|
| Docker + nvidia-runtime | **Native systemd service** | Lower latency, direct GPU access |

**Architecture:**
```
┌─────────────────────────────────────────────────────────────────┐
│              Native Inference Architecture                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    systemd services                          ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │                                                              ││
│  │  ┌─────────────────┐         ┌─────────────────┐            ││
│  │  │ vllm-primary    │         │ vllm-fallback   │            ││
│  │  │ (systemd)       │         │ (systemd)       │            ││
│  │  │                 │         │                 │            ││
│  │  │ GPU: 0 (3090)   │         │ GPU: 1 (2070)   │            ││
│  │  │ Model: 32B      │         │ Model: 3B       │            ││
│  │  │ Port: 8000      │         │ Port: 8001      │            ││
│  │  └─────────────────┘         └─────────────────┘            ││
│  │                                                              ││
│  └─────────────────────────────────────────────────────────────┘│
│                              ▲                                   │
│                              │                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Traefik (Docker)                          ││
│  │  - Routes /api/coding to healthy backend                     ││
│  │  - Health checks both services                               ││
│  │  - Fails over to fallback when primary unhealthy            ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Benefits:**
- ~10-20% lower inference latency (no container overhead)
- Direct CUDA driver access
- Simpler debugging (no docker exec)
- Native MPS integration

### 2. Ray Compute (Training/Jobs)

| Current | Recommended | Rationale |
|---------|-------------|-----------|
| Docker + GPU passthrough | **Hybrid: Native Ray + VM sandboxes** | User jobs in VMs, Ray native |

**Architecture:**
```
┌─────────────────────────────────────────────────────────────────┐
│              Hybrid Ray Architecture                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │              Native Ray Head (systemd)                       ││
│  │  - Coordinates cluster                                       ││
│  │  - No GPU allocation (coordinator only)                      ││
│  │  - Manages MPS for GPU sharing                               ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│              ┌───────────────┴───────────────┐                  │
│              │                               │                  │
│              ▼                               ▼                  │
│  ┌───────────────────────┐     ┌───────────────────────┐       │
│  │   Native GPU Worker    │     │   VM-based Worker     │       │
│  │   (elevated/admin)     │     │   (elevated)          │       │
│  │                        │     │                        │       │
│  │   - Direct GPU access  │     │   - QEMU/KVM VM       │       │
│  │   - FSDP/DeepSpeed     │     │   - GPU passthrough   │       │
│  │   - Full sudo          │     │   - Full sudo in VM   │       │
│  │   - 24GB + 8GB VRAM    │     │   - Isolated env      │       │
│  └───────────────────────┘     └───────────────────────┘       │
│                                                                  │
│  Job Routing:                                                   │
│  - Developer tier → MPS-shared GPU (limited VRAM)              │
│  - Elevated tier → MicroVM with MPS or time-slice              │
│  - Admin tier → Native full GPU access OR VM with passthrough  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3. User Sandbox Environments

| Tier | Execution Environment | GPU Access |
|------|----------------------|------------|
| Viewer | Bubblewrap (no GPU) | None - API only |
| Developer | Bubblewrap + MPS | Shared via MPS (max 2GB) |
| Elevated | Firecracker MicroVM | MPS or time-slice (max 16GB) |
| Admin | Native OR QEMU VM | Full passthrough or native |

---

## Migration Plan by Phase

### Phase 1: Enable KVM & Native GPU Access (Week 1)

```bash
# 1. Load KVM module (add to /etc/modules for persistence)
sudo modprobe kvm_amd
echo "kvm_amd" | sudo tee -a /etc/modules

# 2. Set up IOMMU (edit GRUB)
# Add to /etc/default/grub GRUB_CMDLINE_LINUX_DEFAULT:
# amd_iommu=on iommu=pt

# 3. Install QEMU/KVM
sudo apt install qemu-kvm libvirt-daemon-system virtinst

# 4. Add user to groups
sudo usermod -aG kvm,libvirt $USER

# 5. Verify
virsh list --all
```

### Phase 2: Native Inference Services (Week 1-2)

**Create systemd service for vLLM:**

```ini
# /etc/systemd/system/vllm-primary.service
[Unit]
Description=vLLM Primary Model Service (Qwen2.5-Coder-32B on RTX 3090 Ti)
After=network.target
Wants=nvidia-mps.service

[Service]
Type=simple
User=inference
Group=inference
Environment="CUDA_VISIBLE_DEVICES=0"
Environment="CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps-0"
Environment="HF_HOME=/opt/models"
Environment="MODEL_ID=Qwen/Qwen2.5-Coder-32B-Instruct-AWQ"
ExecStart=/opt/vllm/venv/bin/python -m vllm.entrypoints.openai.api_server \
    --model ${MODEL_ID} \
    --host 0.0.0.0 \
    --port 8000 \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.92 \
    --dtype auto
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Phase 3: Native Ray Head (Week 2)

```ini
# /etc/systemd/system/ray-head.service
[Unit]
Description=Ray Head Node
After=network.target

[Service]
Type=simple
User=ray
Group=ray
Environment="RAY_ADDRESS=auto"
ExecStart=/opt/ray/bin/ray start --head \
    --port=6379 \
    --dashboard-host=0.0.0.0 \
    --dashboard-port=8265 \
    --num-cpus=8 \
    --num-gpus=0 \
    --object-store-memory=2147483648 \
    --block
Restart=always

[Install]
WantedBy=multi-user.target
```

### Phase 4: GPU Worker Pool with MPS (Week 2-3)

**MPS Configuration:**
```bash
# /etc/systemd/system/nvidia-mps@.service
[Unit]
Description=NVIDIA MPS Control Daemon for GPU %i
After=nvidia-persistenced.service

[Service]
Type=forking
Environment="CUDA_VISIBLE_DEVICES=%i"
Environment="CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps-%i"
Environment="CUDA_MPS_LOG_DIRECTORY=/var/log/nvidia-mps-%i"
ExecStartPre=/bin/mkdir -p /tmp/nvidia-mps-%i /var/log/nvidia-mps-%i
ExecStart=/usr/bin/nvidia-cuda-mps-control -d
ExecStop=/bin/echo quit | /usr/bin/nvidia-cuda-mps-control

[Install]
WantedBy=multi-user.target
```

### Phase 5: VM-based Sandboxes (Week 3-4)

**Firecracker for Elevated Users:**
```bash
# Download Firecracker
ARCH=$(uname -m)
curl -L https://github.com/firecracker-microvm/firecracker/releases/latest/download/firecracker-$ARCH.tgz | tar xz
sudo mv release-*/firecracker /usr/local/bin/
sudo mv release-*/jailer /usr/local/bin/

# Create minimal kernel and rootfs
# (Use pre-built or build custom with CUDA support)
```

**QEMU/KVM for Admin GPU Passthrough:**
```xml
<!-- /etc/libvirt/qemu/admin-workstation.xml -->
<domain type='kvm'>
  <name>admin-workstation</name>
  <memory unit='GiB'>32</memory>
  <vcpu>12</vcpu>
  <os>
    <type arch='x86_64'>hvm</type>
    <boot dev='hd'/>
  </os>
  <features>
    <acpi/>
    <apic/>
  </features>
  <devices>
    <!-- GPU Passthrough - RTX 2070 -->
    <hostdev mode='subsystem' type='pci' managed='yes'>
      <source>
        <address domain='0x0000' bus='0x0b' slot='0x00' function='0x0'/>
      </source>
    </hostdev>
    <hostdev mode='subsystem' type='pci' managed='yes'>
      <source>
        <address domain='0x0000' bus='0x0b' slot='0x00' function='0x1'/>
      </source>
    </hostdev>
    <!-- Network -->
    <interface type='bridge'>
      <source bridge='br0'/>
      <model type='virtio'/>
    </interface>
  </devices>
</domain>
```

---

## GPU Allocation Strategy

### Inference Mode (Default - No Training)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Inference Mode GPU Layout                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  GPU 0 (RTX 3090 Ti - 24GB)          GPU 1 (RTX 2070 - 8GB)     │
│  ┌────────────────────────┐          ┌────────────────────┐     │
│  │ vllm-primary (22GB)    │          │ vllm-fallback (6GB)│     │
│  │ Qwen2.5-Coder-32B      │          │ Qwen2.5-Coder-3B   │     │
│  ├────────────────────────┤          ├────────────────────┤     │
│  │ MPS Reserved (2GB)     │          │ MPS Reserved (2GB) │     │
│  │ - Developer sandbox    │          │ - Developer sandbox│     │
│  │ - Small CUDA tasks     │          │ - Small CUDA tasks │     │
│  └────────────────────────┘          └────────────────────┘     │
│                                                                  │
│  Total Available for Users: ~4GB shared via MPS                 │
└─────────────────────────────────────────────────────────────────┘
```

### Training Mode (Ray Job Running)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Training Mode GPU Layout                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  GPU 0 (RTX 3090 Ti - 24GB)          GPU 1 (RTX 2070 - 8GB)     │
│  ┌────────────────────────┐          ┌────────────────────┐     │
│  │ FSDP/DeepSpeed         │          │ vllm-fallback (6GB)│     │
│  │ Training Job           │◄────────►│ (still serving!)   │     │
│  │ (Full 24GB)            │  Shared  ├────────────────────┤     │
│  │                        │  params  │ Training Shard     │     │
│  │                        │          │ (ZeRO-3 offload)   │     │
│  │                        │          │ (2GB)              │     │
│  └────────────────────────┘          └────────────────────┘     │
│                                                                  │
│  Primary model: STOPPED (yields to training)                    │
│  Fallback model: SERVING (maintains availability)               │
│  Training: Uses both GPUs via FSDP/DeepSpeed                    │
└─────────────────────────────────────────────────────────────────┘
```

### Admin Workstation Mode (GPU Passthrough)

```
┌─────────────────────────────────────────────────────────────────┐
│               Admin Workstation Mode (GPU Passthrough)           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Host System                         Admin VM (QEMU/KVM)        │
│  ┌────────────────────────┐          ┌────────────────────┐     │
│  │ GPU 0 (RTX 3090 Ti)    │          │ GPU 1 (RTX 2070)   │     │
│  │                        │          │ ───────────────────│     │
│  │ vllm-primary (22GB)    │          │ Full Passthrough   │     │
│  │ Still serving!         │          │                    │     │
│  │                        │          │ - Real desktop     │     │
│  │                        │          │ - Full CUDA        │     │
│  │                        │          │ - Docker-in-VM     │     │
│  │                        │          │ - Any workload     │     │
│  └────────────────────────┘          └────────────────────┘     │
│                                                                  │
│  Note: Admin can also access GPU 0 natively via sudo           │
│  This mode gives full isolated workstation for experiments     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Service Migration Checklist

### Keep Containerized ✅
| Service | Reason |
|---------|--------|
| Traefik | Networking isolation, easy config |
| PostgreSQL | Data isolation, backup tooling |
| Redis | Simple service, no GPU |
| FusionAuth | Java app, container optimized |
| OAuth2-Proxy | Stateless, easy updates |
| MLflow Server | Python app, no GPU |
| Prometheus/Grafana | Monitoring stack, stable |
| Chat API/UI | Web services, no GPU |
| Infisical | Security sensitive, isolated |

### Migrate to Native 🔄
| Service | Current | Target | Priority |
|---------|---------|--------|----------|
| vLLM Primary | Docker | systemd | High |
| vLLM Fallback | Docker | systemd | High |
| Ray Head | Docker | systemd | Medium |
| MPS Daemon | N/A | systemd | High |

### Add New 🆕
| Service | Type | Purpose |
|---------|------|---------|
| nvidia-mps@0 | systemd | MPS for GPU 0 |
| nvidia-mps@1 | systemd | MPS for GPU 1 |
| sandbox-manager | systemd + API | Manages bubblewrap/Firecracker |
| vm-pool-manager | systemd + API | Pre-warms VMs for elevated users |

---

## Decision Points - Your Input Needed

### 1. Primary Inference Model Strategy

**Option A: Keep Primary on 3090 Ti (Current)**
- Pros: Best quality (32B model), proven setup
- Cons: No GPU sharing during inference

**Option B: Use Tensor Parallel across both GPUs**
- Pros: Could run larger model (up to 50B)
- Cons: Limited by 8GB 2070, PCIe bandwidth bottleneck, complexity

**Option C: Pipeline Parallel (GPU 0 → GPU 1)**
- Pros: Better for asymmetric GPUs
- Cons: Higher latency, complex setup

**Recommendation:** Keep Option A, it's optimal for your hardware.

### 2. Training Mode GPU Allocation

**Option A: Full GPU 0 for Training, Fallback on GPU 1**
- Pros: Simple, maximum training VRAM
- Cons: Training limited to 24GB

**Option B: FSDP/DeepSpeed across both GPUs + CPU offload**
- Pros: Train up to ~100B models (with 64GB RAM offload)
- Cons: Stops fallback model during training

**Option C: MPS sharing - Training gets 80% GPU 0, Inference keeps 20%**
- Pros: Maintain some inference during training
- Cons: Slower training, potential OOM issues

**Recommendation:** Option A for simplicity, Option B for maximum capability.

### 3. Admin GPU Access

**Option A: Native Access (sudo nvidia-smi)**
- Pros: Zero overhead, full control
- Cons: No isolation, could crash inference

**Option B: GPU Passthrough VM (RTX 2070)**
- Pros: Full isolation, can't affect production
- Cons: GPU 1 dedicated to admin VM when in use

**Option C: Time-based Scheduling**
- Pros: Admin gets both GPUs at scheduled times
- Cons: Complex, inflexible

**Recommendation:** Option B - give admin full VM with RTX 2070 passthrough.

---

## Implementation Priority

1. **Week 1:** Enable KVM, install QEMU, test IOMMU passthrough
2. **Week 1-2:** Migrate vLLM to native systemd services
3. **Week 2:** Set up MPS daemons for GPU sharing
4. **Week 2-3:** Migrate Ray head to native (keep API containerized)
5. **Week 3-4:** Implement Firecracker/QEMU sandbox manager
6. **Week 4+:** Integration testing, documentation

---

## SOTA Best Practices Integration

> Based on research documented in `docs/research/SOTA_BEST_PRACTICES_SUMMARY.md`

### 1. AG-UI Protocol for Agent Interactions

**Source:** CopilotKit AG-UI Protocol

All agent-user interactions should implement the AG-UI event protocol for real-time streaming:

```yaml
# Event types to implement
events:
  - TEXT_MESSAGE_START/CONTENT/END    # For chat responses
  - TOOL_CALL_START/ARGS/END          # For tool usage visibility
  - STATE_SNAPSHOT/DELTA              # For progress tracking
  - RUN_STARTED/FINISHED/ERROR        # For job lifecycle

# Implementation targets
targets:
  - Chat UI → streaming responses
  - Jupyter notebooks → cell execution status
  - Training jobs → epoch/loss updates
  - Admin dashboard → system state changes
```

**Integration Points:**
- Training job progress: `STATE_DELTA` events with epoch, loss, GPU utilization
- Inference requests: `RUN_STARTED` → `TEXT_MESSAGE_*` → `RUN_FINISHED`
- Tool orchestration: `TOOL_CALL_*` events when routing to different backends

### 2. Unsloth Memory Optimization Techniques

**Source:** Unsloth 500K Context Blog

**CRITICAL for training on our hardware (24GB + 8GB GPUs with 64GB RAM):**

```python
# Recommended training configuration
training_config = {
    # Chunked Cross-Entropy Loss (60% VRAM reduction)
    "chunked_loss": True,
    "chunked_loss_num_chunks": "auto",  # Auto-adjust based on available VRAM

    # Gradient Checkpointing with CPU Offload (0.1% overhead)
    "gradient_checkpointing": True,
    "gradient_checkpointing_offload": True,  # Offload to 64GB system RAM

    # Tiled MLP (2x context for 1.3x time cost)
    "tiled_mlp": True,

    # Memory budget per GPU
    "gpu_memory_utilization": {
        "gpu_0": 0.90,  # 3090 Ti: ~22GB of 24GB
        "gpu_1": 0.85,  # 2070: ~7GB of 8GB
    },

    # CPU offload for larger models
    "cpu_offload_params": True,  # For 7B+ parameter models
}
```

**Memory Budget:**
| Resource | Total | Reserved | Available for Training |
|----------|-------|----------|----------------------|
| GPU 0 (3090 Ti) | 24GB | 2GB MPS | 22GB |
| GPU 1 (2070) | 8GB | 0.5GB MPS | 7.5GB |
| System RAM | 64GB | 8GB OS | 56GB offload |
| **Effective VRAM** | - | - | **~80GB** (with offload) |

### 3. API Design Best Practices

**Source:** PostHog Blog - Good API Design

**Apply to all REST APIs:**

```yaml
# Idempotency Keys (required for all mutating operations)
training_api:
  POST /api/v1/training/jobs:
    headers:
      X-Idempotency-Key: required  # Prevents duplicate job creation on retry

# Rate Limiting Headers
response_headers:
  X-RateLimit-Limit: 60           # Requests per window
  X-RateLimit-Remaining: 57       # Remaining in current window
  X-RateLimit-Reset: 1704067200   # Unix timestamp of reset
  Retry-After: 30                 # Seconds until retry (on 429)

# Rate Limits by Tier
rate_limits:
  viewer:     10/minute
  developer:  60/minute
  elevated:   120/minute
  admin:      unlimited

# Cursor-Based Pagination (not offset)
pagination:
  type: cursor
  format: base64_encoded_timestamp_id
  response:
    next_cursor: "eyJ0IjoxNjcyNTMxMjAwLCJpZCI6MTIzfQ=="
    has_more: true
```

### 4. ToolOrchestra Pattern for Job Routing

**Source:** NVIDIA ToolOrchestra (arXiv:2511.21689)

**Key Insight:** Small orchestrator (8B) can outperform larger models by intelligently routing to appropriate tools/backends.

```yaml
# Orchestrator Architecture
orchestrator:
  model: "local-qwen-8b"  # Small, fast decision maker

  tools:
    - name: vllm_inference_3090
      cost: low
      latency: fast
      capability: "fast inference up to 32B models"

    - name: vllm_inference_2070
      cost: lowest
      latency: fast
      capability: "fallback inference, 3B models"

    - name: training_single_gpu
      cost: medium
      latency: variable
      capability: "fine-tune up to 13B models"

    - name: training_dual_gpu_fsdp
      cost: high
      latency: hours
      capability: "fine-tune up to 70B models with CPU offload"
      admin_only: true

    - name: external_api_openai
      cost: per_token
      latency: variable
      capability: "fallback for complex reasoning"
      requires_user_consent: true

  # Routing Policy
  routing:
    - if: simple_chat → vllm_inference_3090
    - if: vllm_3090_busy → vllm_inference_2070
    - if: training_small → training_single_gpu
    - if: training_large && admin → training_dual_gpu_fsdp
    - if: training_large && !admin → queue_for_approval

  # Cost Optimization (from ToolOrchestra paper)
  rewards:
    outcome_weight: 0.6     # Task completion
    efficiency_weight: 0.3  # Cost minimization
    preference_weight: 0.1  # User tool preferences
```

**Anti-Pattern Warning (from paper):**
- Avoid "self-enhancement bias" where orchestrator always picks familiar tools
- Train/configure with diverse tool availability
- Don't default to most expensive option

### 5. Training Queue System

**Informed by ToolOrchestra efficiency patterns:**

```yaml
training_queue:
  # Fair share scheduling with admin priority
  scheduling:
    policy: fair_share_with_priority
    admin_priority: 2.0
    max_concurrent_per_user: 3

  # Auto-checkpoint on preemption
  checkpointing:
    strategy: on_preempt
    storage: /data/training/checkpoints
    retention: 30_days

  # Resource allocation
  resources:
    small_job:    # < 7B params
      gpu: single
      max_time: 4h
      auto_queue: true

    medium_job:   # 7B-30B params
      gpu: single_with_offload
      max_time: 12h
      auto_queue: true

    large_job:    # > 30B params
      gpu: dual_fsdp
      max_time: 48h
      requires_approval: !admin

  # Preemption rules
  preemption:
    - admin_jobs preempt non_admin_jobs
    - inference preempts training (graceful, with checkpoint)
    - training_small preempts training_large (if queue full)
```

### 6. VM Lifecycle Management

**For elevated/admin sandbox VMs:**

```yaml
vm_lifecycle:
  # On-demand provisioning
  provisioning:
    trigger: user_request
    max_startup_time: 60s
    base_image: ubuntu-22.04-cuda-12.1

  # Idle timeout with snapshot
  idle_management:
    idle_timeout: 30m
    on_idle:
      1. checkpoint_running_processes
      2. save_vm_snapshot
      3. release_gpu_resources
      4. hibernate_vm

  # Snapshot strategy
  snapshots:
    before_shutdown: always
    periodic: every_4h_if_active
    on_training_complete: always
    retention:
      user_snapshots: 30_days
      training_checkpoints: indefinite

  # Resource release
  gpu_release:
    immediate_on: vm_shutdown
    graceful_on: idle_timeout
    never_on: active_training
```

### 7. Notification Integration

```yaml
notifications:
  # Multi-channel support
  channels:
    - type: grafana_alerting
      for: system_alerts, threshold_breaches

    - type: homer_dashboard
      for: service_status, quick_overview

    - type: ntfy_push
      for: user_notifications, job_completion
      endpoint: https://ntfy.sh/shml-platform

  # Event types
  events:
    training_complete:
      channels: [ntfy, grafana]
      message: "Training job {job_id} completed. Loss: {final_loss}"

    gpu_contention:
      channels: [grafana]
      message: "GPU {gpu_id} queue depth: {depth}"

    vm_idle_shutdown:
      channels: [ntfy]
      message: "Your VM was hibernated after 30min idle. Snapshot saved."

    inference_degraded:
      channels: [grafana, homer]
      message: "Primary inference using fallback model"
```

### 8. Logging Architecture

**Immutable, signed audit logs:**

```yaml
logging:
  # Centralized collection
  collector: vector  # or fluentd

  # Log categories
  categories:
    audit:
      retention: indefinite
      signed: true  # GPG signed
      immutable: true
      includes: [auth, sudo, gpu_allocation, training_jobs]

    application:
      retention: 90_days
      signed: false
      includes: [inference, api_requests, errors]

    metrics:
      retention: 1_year
      aggregated_after: 7_days
      includes: [gpu_utilization, latency, throughput]

  # Signing configuration
  signing:
    key_location: infisical://super-admin/signing-key
    algorithm: ed25519
    rotation: manual  # Requires super-admin

  # Storage
  storage:
    hot: /data/logs/current  # 7 days
    warm: /data/logs/archive  # 90 days
    cold: s3://shml-logs/archive  # indefinite
```

---

## Updated Implementation Priority

| Phase | Tasks | Week | SOTA Integration |
|-------|-------|------|------------------|
| 1.0 | Enable KVM, IOMMU | 1 | - |
| 1.1 | Migrate vLLM to native | 1-2 | - |
| 1.2 | MPS daemons setup | 2 | Memory budgets from Unsloth |
| 2.0 | Ray native migration | 2-3 | - |
| 2.1 | Training service config | 3 | Chunked loss, CPU offload |
| 2.2 | API middleware | 3 | Idempotency, rate limits |
| 3.0 | VM sandbox manager | 3-4 | VM lifecycle patterns |
| 3.1 | Job orchestrator | 4 | ToolOrchestra routing |
| 3.2 | AG-UI protocol | 4-5 | Streaming events |
| 4.0 | Notification system | 5 | Grafana + ntfy |
| 4.1 | Audit logging | 5-6 | Signed immutable logs |

---

## Questions for You

1. **Training frequency:** How often do you expect to run training jobs? (affects GPU allocation strategy)

2. **Admin workstation:** Do you want a persistent GPU-passthrough VM for admin, or on-demand?

3. **Model serving during training:** Is it acceptable to fall back to 3B model during training, or do you need to maintain 32B?

4. **Multi-user training:** Should multiple elevated users be able to run training simultaneously (requires sophisticated queuing)?

5. **Fallback model:** Keep the 3B on RTX 2070, or use that slot for something else (e.g., embedding model, different task)?
