# Setup Checklist - Remote Compute Server

## Prerequisites

- [x] Ubuntu 20.04 server
- [x] NVIDIA RTX 2070 GPU installed
- [x] MLflow server running (port 8080)
- [x] Tailscale VPN configured (100.69.227.36)
- [x] 1.7TB storage available
- [x] 15GB RAM available

## Phase 1: System Dependencies

### 1.1 Install NVIDIA Drivers

```bash
cd /home/$USER/Projects/mlflow-server/ray_compute
sudo bash scripts/install_nvidia_drivers.sh
```

- [ ] Script completed successfully
- [ ] System rebooted
- [ ] Run `nvidia-smi` to verify GPU detected
- [ ] GPU shows "NVIDIA GeForce RTX 2070"

**Expected output after reboot:**

```
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 525.xx.xx    Driver Version: 525.xx.xx    CUDA Version: 12.0   |
|-------------------------------+----------------------+----------------------+
|   0  NVIDIA GeForce RTX 2070  | ...                  | ...                  |
+-------------------------------+----------------------+----------------------+
```

### 1.2 Install Docker + NVIDIA Container Toolkit

```bash
sudo bash scripts/install_docker_nvidia.sh
```

- [ ] Docker installed
- [ ] User added to docker group
- [ ] NVIDIA Container Toolkit installed
- [ ] Test GPU in container: `docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi`
- [ ] GPU visible in container

**Expected output:**

```
Status: Downloaded newer image for nvidia/cuda:11.8.0-base-ubuntu20.04
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 525.xx.xx    Driver Version: 525.xx.xx    CUDA Version: 12.0   |
...
```

### 1.3 Install Ray + ML Libraries

```bash
sudo bash scripts/install_ray_cluster.sh
```

- [ ] Ray 2.9.0 installed
- [ ] PyTorch with CUDA support installed
- [ ] Ultralytics YOLO installed
- [ ] MLflow client installed
- [ ] Directories created: `/opt/ray/tmp`, `/opt/ray/logs`, `/opt/ray/jobs`
- [ ] Run `python3 -c "import ray; import torch; print(f'Ray: {ray.__version__}, Torch: {torch.__version__}, CUDA: {torch.cuda.is_available()}')"`

**Expected output:**

```
Ray: 2.9.0, Torch: 2.1.0+cu118, CUDA: True
```

## Phase 2: Docker Images

### 2.1 Build GPU Image

```bash
cd docker
bash build_images.sh
```

- [ ] Build started for `mlflow-compute-gpu`
- [ ] Base image downloaded: nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu20.04
- [ ] PyTorch 2.1.0+cu118 installed in image
- [ ] Ultralytics YOLO installed in image
- [ ] Build completed successfully
- [ ] Verify: `docker images | grep mlflow-compute-gpu`

### 2.2 Build CPU Image

- [ ] Build started for `mlflow-compute-cpu`
- [ ] Base image: ubuntu:20.04
- [ ] scikit-learn, XGBoost installed
- [ ] Build completed successfully
- [ ] Verify: `docker images | grep mlflow-compute-cpu`

**Expected output:**

```
mlflow-compute-gpu    latest    abc123def456    ...    5.2GB
mlflow-compute-cpu    latest    def789ghi012    ...    1.8GB
```

## Phase 3: Start Services

### 3.1 Start Ray Cluster

```bash
cd /home/$USER/Projects/mlflow-server/ray_compute
bash start_all_remote.sh
```

- [ ] Ray head node started
- [ ] Ray Dashboard accessible at http://localhost:8265
- [ ] MLflow server verified at http://localhost:8080
- [ ] Remote API started on port 8266
- [ ] Tailscale IP confirmed: 100.69.227.36

**Expected output:**

```
==================================================
Ray Compute - Remote Edition Started
==================================================

Services:
  - Ray Dashboard:  http://localhost:8265
  - MLflow Server:  http://localhost:8080
  - Compute API:    http://localhost:8266
  - Remote API:     http://100.69.227.36:8266
```

### 3.2 Verify Services

```bash
bash scripts/check_status.sh
```

- [ ] Ray head node: RUNNING
- [ ] Remote API server: RUNNING (port 8266)
- [ ] MLflow server: RUNNING (port 8080)
- [ ] GPU detected: 1x NVIDIA GeForce RTX 2070

### 3.3 Test Local Access

```bash
# Health check
curl http://localhost:8266/health
```

- [ ] Response: `{"status": "healthy", "ray": "healthy", "mlflow": "healthy", ...}`

```bash
# Resources
curl http://localhost:8266/resources
```

- [ ] Shows available CPU, memory, GPU

## Phase 4: Remote Client Setup

### 4.1 Copy Client Library (on remote machine)

```bash
scp user@100.69.227.36:/home/$USER/Projects/mlflow-server/ray_compute/api/client_remote.py .
```

- [ ] File copied successfully
- [ ] Install dependency: `pip install requests`

### 4.2 Test Remote Connection (from remote machine)

```bash
curl http://100.69.227.36:8266/health
```

- [ ] Response received
- [ ] Status: "healthy"

## Phase 5: Validation Tests

### 5.1 Copy Test Script (to remote machine)

```bash
scp user@100.69.227.36:/home/$USER/Projects/mlflow-server/ray_compute/test_remote_compute.py .
```

- [ ] File copied successfully

### 5.2 Run Validation (from remote machine)

```bash
python3 test_remote_compute.py http://100.69.227.36:8266
```

- [ ] Test 1: Connection - PASS
- [ ] Test 2: Resources - PASS
- [ ] Test 3: CPU Job - PASS
  - [ ] Job submitted
  - [ ] Job completed successfully
  - [ ] Artifacts downloaded
  - [ ] Artifact content verified
  - [ ] Server cleaned up workspace
- [ ] Test 4: GPU Job - PASS
  - [ ] Job submitted with GPU
  - [ ] PyTorch CUDA detected
  - [ ] GPU computation completed
  - [ ] Artifacts downloaded
  - [ ] Server cleaned up workspace

**Expected output:**

```
============================================================
Test Summary
============================================================
✓ PASS: Connection
✓ PASS: Resources
✓ PASS: CPU Job
✓ PASS: GPU Job

============================================================
🎉 ALL TESTS PASSED!
Remote compute server is ready for production use.
============================================================
```

## Phase 6: Verify Artifact Cleanup

### 6.1 Check Workspaces (on server)

```bash
ls -la /opt/ray/job_workspaces/
```

- [ ] Directory exists
- [ ] No job directories remain (all cleaned up)
- [ ] Or only recent jobs (within 24h if `cleanup_after=False`)

### 6.2 Submit Test with Cleanup Disabled

```python
from client_remote import RemoteComputeClient

client = RemoteComputeClient("http://100.69.227.36:8266")
job_id = client.submit_job(
    name="cleanup_test",
    code="print('test')",
    cleanup_after=False  # Keep artifacts
)
```

- [ ] Job completed
- [ ] Workspace exists: `/opt/ray/job_workspaces/{job_id}/`
- [ ] Artifacts available for download
- [ ] Can manually delete: `rm -rf /opt/ray/job_workspaces/{job_id}/`

## Phase 7: Production Deployment (Optional)

### 7.1 Install Systemd Services

```bash
sudo bash scripts/install_systemd_services.sh
```

- [ ] Choose option 2: Remote API
- [ ] ray-head.service installed
- [ ] ray-compute-api-remote.service installed
- [ ] Services enabled for boot
- [ ] Choose to start services now

### 7.2 Verify Systemd Services

```bash
sudo systemctl status ray-head ray-compute-api-remote
```

- [ ] ray-head: active (running)
- [ ] ray-compute-api-remote: active (running)

### 7.3 Test Automatic Restart

```bash
# Stop services
sudo systemctl stop ray-compute-api-remote ray-head

# Start services
sudo systemctl start ray-head
sleep 3
sudo systemctl start ray-compute-api-remote

# Check status
sudo systemctl status ray-head ray-compute-api-remote
```

- [ ] Services restarted successfully
- [ ] No errors in logs

## Phase 8: Final Verification

### 8.1 Submit Real Training Job (from remote)

```python
from client_remote import submit_training_job

result = submit_training_job(
    server_url="http://100.69.227.36:8266",
    name="yolo_test",
    code="""
from ultralytics import YOLO
from pathlib import Path
import os

output_dir = Path(os.environ['JOB_OUTPUT_DIR'])

model = YOLO('yolov8n.pt')
results = model.train(data='coco128.yaml', epochs=5, imgsz=640)

model.save(output_dir / 'model.pt')
""",
    mlflow_experiment="test-training"
)
```

- [ ] Job submitted successfully
- [ ] Job completed successfully
- [ ] MLflow run created
- [ ] Artifacts downloaded to local machine
- [ ] Server workspace cleaned up

### 8.2 Check MLflow UI

```bash
# From remote machine
xdg-open http://100.69.227.36:8080
# Or visit in browser
```

- [ ] Experiment "test-training" visible
- [ ] Run appears with metrics
- [ ] Tags show remote_job: true
- [ ] Parameters logged (cpu, gpu, memory_gb)

## Troubleshooting

### Issue: NVIDIA driver not detected

```bash
# Verify driver installation
nvidia-smi
lsmod | grep nvidia

# If not loaded
sudo modprobe nvidia
sudo systemctl restart ray-head
```

### Issue: Ray Dashboard not accessible

```bash
# Check Ray process
pgrep -f "ray start"

# Check logs
tail -f /home/$USER/Projects/mlflow-server/ray_compute/logs/ray_head.log

# Restart
bash stop_all_remote.sh && bash start_all_remote.sh
```

### Issue: Remote API not accessible from remote machine

```bash
# On server, check if listening
ss -tulpn | grep 8266

# Check Tailscale
tailscale status
tailscale ping 100.69.227.36

# Check firewall
sudo ufw status
# If needed: sudo ufw allow 8266/tcp
```

### Issue: Job fails with CUDA error

```bash
# Verify GPU in container
docker run --rm --gpus all mlflow-compute-gpu nvidia-smi

# Check CUDA version compatibility
docker run --rm --gpus all mlflow-compute-gpu python3 -c "import torch; print(torch.cuda.is_available())"
```

## Success Criteria

All checkboxes must be checked for successful setup:

**Core Functionality:**

- [x] GPU detected and accessible
- [ ] Ray cluster running
- [ ] Remote API accessible
- [ ] Test jobs complete successfully
- [ ] Artifacts download correctly
- [ ] Server cleans up after download

**Remote Access:**

- [ ] Tailscale VPN working
- [ ] Remote client can connect
- [ ] Jobs submit from remote machine
- [ ] Artifacts download to remote machine

**Integration:**

- [ ] MLflow tracking works
- [ ] GPU jobs utilize RTX 2070
- [ ] Docker images built successfully
- [ ] Resource scheduling works

**Production Readiness (Optional):**

- [ ] Systemd services installed
- [ ] Services auto-start on boot
- [ ] Logs accessible via journalctl

## Next Steps After Setup

1. **Integrate with your training scripts**

   - Replace local training with remote job submission
   - Use `submit_training_job()` convenience function
   - Leverage MLflow experiment tracking

2. **Monitor resource usage**

   - Watch GPU utilization: `watch -n 1 nvidia-smi`
   - Check Ray Dashboard: http://100.69.227.36:8265
   - Monitor API: `curl http://localhost:8266/resources`

3. **Set up additional remote clients**

   - Copy `client_remote.py` to other machines
   - Share Tailscale network access
   - Submit jobs from multiple locations

4. **Customize job configurations**
   - Adjust resource requirements
   - Configure MLflow experiments
   - Set custom environment variables

## Documentation Reference

- **This Checklist**: `SETUP_CHECKLIST.md`
- **Complete Guide**: `REMOTE_SETUP_GUIDE.md`
- **Quick Reference**: `REMOTE_QUICK_REFERENCE.md`
- **Implementation Summary**: `REMOTE_IMPLEMENTATION_SUMMARY.md`
- **Architecture Details**: `docs/ARCHITECTURE.md`

## Support

If you encounter issues:

1. Check logs: `logs/api_remote.log`, `logs/ray_head.log`
2. Review troubleshooting section above
3. Verify all prerequisites met
4. Check service status: `bash scripts/check_status.sh`

---

**Current Status**: Ready to begin Phase 1 (Install NVIDIA Drivers)

**Time Estimate**:

- Phase 1-2: 30-45 minutes (includes reboot)
- Phase 3-5: 15-20 minutes
- Phase 6-8: 10-15 minutes
- **Total**: ~1-1.5 hours

**Start Command**:

```bash
cd /home/$USER/Projects/mlflow-server/ray_compute
sudo bash scripts/install_nvidia_drivers.sh
```
