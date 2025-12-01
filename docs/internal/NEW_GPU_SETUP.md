# RTX 3090 Founders Edition - Dual GPU Installation Guide

## System Configuration Overview

### Current Hardware
- **Motherboard**: ASUS ROG Crosshair VIII Hero (Wi-Fi)
- **CPU**: AMD Ryzen 9 3900X 12-Core (24 PCIe 4.0 lanes)
- **Current GPU**: NVIDIA RTX 2070 in PCIEX16_1 slot
- **PSU**: Super Flower Leadex Platinum III 1300W ATX 3.0
- **Target GPU**: NVIDIA RTX 3090 Founders Edition (to be installed)

### PCIe Slot Configuration

| Slot | Type | Speed | Status | Assignment |
|------|------|-------|--------|------------|
| PCIEX16_1 | x16 PCIe 4.0 | Will run at x8 in dual GPU | In Use | RTX 2070 (Keep) |
| PCIEX16_2 | x8 PCIe 4.0 | x8 | Available | RTX 3090 (Install here) |
| PCIEX1_1 | x1 PCIe | x1 | Available | Skip |
| PCIEX16_3 | x4 PCIe | x4 | Available | Skip |

**PCIe Lane Distribution (Dual GPU Mode)**:
- Ryzen 9 3900X provides 24 PCIe 4.0 lanes total
- When both PCIEX16_1 and PCIEX16_2 are populated: 8+8 configuration
- PCIe 4.0 x8 = ~16 GB/s bandwidth per GPU (more than sufficient for ML workloads)
- Remaining 8 lanes: 4 for M.2 NVMe, 4 for chipset

---

## Power Requirements & Analysis

### Power Budget Breakdown
| Component | Maximum Power | Notes |
|-----------|---------------|-------|
| RTX 3090 FE | 350W | Requires 2x 8-pin PCIe (via 12-pin adapter) |
| RTX 2070 | 175W | Requires 1x 8-pin PCIe |
| Ryzen 9 3900X | 140W | TDP at full load |
| System/Peripherals | 100W | Motherboard, RAM, storage, fans |
| **Total Max Draw** | **765W** | Peak simultaneous load |
| **PSU Capacity** | **1300W** | Super Flower Leadex Platinum III |
| **Safety Headroom** | **535W** | 41% overhead - excellent margin |

### PSU Quality Check ✓
- **Model**: Super Flower Leadex Platinum III 1300W
- **Efficiency**: 80+ Platinum certified
- **Spec**: ATX 3.0 compliant
- **Quality**: Tier A+ PSU (top-tier Japanese capacitors)
- **12V Rails**: Multiple independent rails with high amperage
- **Verdict**: More than sufficient for dual RTX 3090 setup if needed

### Power Cable Requirements

**Critical: Do NOT use daisy-chained/pigtail PCIe cables for RTX 3090**

Required cables from PSU:
1. **2x separate 8-pin PCIe cables** → RTX 3090 via 12-pin adapter (included with card)
2. **1x 8-pin PCIe cable** → RTX 2070 (existing)

**Total: 3 independent 8-pin PCIe power connectors**

Your Leadex Platinum III has 4-6 PCIe connectors, so you're well covered.

---

## RTX 3090 Founders Edition Specifications

### Physical Dimensions
- **Length**: 313mm (12.3 inches)
- **Width**: 138mm (5.4 inches - 3-slot design)
- **Height**: 112mm
- **Slot Occupancy**: 3 full expansion slots
- **Weight**: 2.21 kg (4.87 lbs)

### Unique Cooling Design
- **Flow-through design**: Intake on one side, exhaust through rear
- **Dual axial fans**: One pulls air in, one pushes air through and out
- **Thermal requirement**: Needs good case airflow
- **Spacing**: Leave at least 1 slot gap from other GPUs (your config provides this)

### Power Connector
- **Card connector**: 12-pin Micro-Fit 3.0 connector
- **Included adapter**: 2x 8-pin to 12-pin adapter (in box)
- **Power draw**: Up to 350W sustained, 400W peak transient

### Compute Specifications
- **CUDA Cores**: 10496
- **Tensor Cores**: 328 (3rd gen)
- **RT Cores**: 82 (2nd gen)
- **Memory**: 24GB GDDR6X
- **Memory Bandwidth**: 936 GB/s
- **Ideal for**: Large model training, multi-GPU inference, Ray distributed computing

---

## Pre-Installation Checklist

### Hardware Verification
- [x] PSU is 1300W Super Flower Leadex Platinum III
- [x] Have 3 separate 8-pin PCIe cables available
- [x] RTX 3090 FE 12-pin adapter is in the box
- [ ] Case has 313mm GPU clearance
- [ ] Case has adequate airflow (front intake, rear exhaust)
- [ ] Anti-static wrist strap or grounding method ready

### System Preparation
- [ ] Backup current system state and important data
- [ ] Document current NVIDIA driver version: `nvidia-smi --query-gpu=name,driver_version --format=csv`
- [ ] Verify current GPU is working

### Physical Space
- [ ] Clear workspace with good lighting
- [ ] Phillips screwdriver available
- [ ] Cable ties for cable management

---

## Installation Procedure

### Step 1: System Shutdown & Preparation

```bash
# Verify current GPU status
nvidia-smi

# Clean shutdown
sudo shutdown -h now
```

**After shutdown:**
1. **Unplug power cable** from wall outlet (not just from PSU)
2. **Press power button** 2-3 times to discharge capacitors
3. **Ground yourself** - touch metal case frame before touching components

### Step 2: Case Access

1. Remove side panel (usually left side when facing front)
2. Locate PCIEX16_2 slot (second full-length PCIe slot)
3. Remove **3 expansion slot covers** for the 3-slot RTX 3090
4. Set screws aside in a safe container

### Step 3: RTX 3090 Installation

**Physical Installation:**
1. Hold RTX 3090 by the edges (avoid touching PCB or connectors)
2. Align card with PCIEX16_2 slot (second full-length slot)
3. Ensure I/O bracket aligns with case opening
4. Apply firm, even pressure until card seats fully
5. You should hear/feel a click from the PCIe retention clip
6. Secure card with screws through I/O bracket
7. RTX 2070 remains in PCIEX16_1 (top slot)

**Power Connection:**
1. Take the 2x 8-pin to 12-pin adapter from RTX 3090 box
2. Connect **2 separate 8-pin PCIe cables** from PSU to adapter
   - Use cables labeled "PCIe" or "VGA"
   - Do NOT use single daisy-chained cable
   - Each 8-pin should come directly from PSU
3. Connect 12-pin adapter to RTX 3090
4. Ensure connection is firm and fully seated
5. Verify RTX 2070's 8-pin power is still connected

### Step 4: Cable Management & Final Check

1. Route cables neatly to avoid blocking airflow
2. Ensure no cables touch GPU fans or heatsinks
3. Double-check all connections:
   - [ ] RTX 3090 seated in PCIEX16_2 and screwed in
   - [ ] RTX 3090 12-pin power connected with 2 separate 8-pin cables
   - [ ] RTX 2070 still seated in PCIEX16_1
   - [ ] RTX 2070 8-pin power still connected
   - [ ] No cables obstructing fans

---

## BIOS/UEFI Configuration

### First Boot - BIOS Setup

1. **Press DEL key repeatedly** during POST to enter BIOS
2. If you miss it and boot to Linux, restart and try again

### Required BIOS Settings (ASUS UEFI)

**Navigate to: Advanced Mode (F7) → Advanced**

#### Critical Settings:

**1. Above 4G Decoding** ⚠️ REQUIRED
```
Advanced → System Agent Configuration → Above 4G Decoding
Setting: ENABLED
```
- **Why**: Required for GPUs with >4GB memory (RTX 3090 has 24GB)
- **Without this**: System may not detect RTX 3090

**2. Re-Size BAR Support** (Optional but Recommended)
```
Advanced → PCI Subsystem Settings → Re-Size BAR Support
Setting: ENABLED
```
- **Benefit**: Can improve performance by 5-10%

**3. PCIe Configuration**
```
Advanced → PCI Subsystem Settings
PCIEX16_1 Link Speed: Auto (will negotiate Gen4 x8)
PCIEX16_2 Link Speed: Auto (will negotiate Gen4 x8)
```

**4. Primary Display**
```
Advanced → System Agent Configuration → Primary Display
Setting: Auto or PCIe
```

**5. Save & Exit**: Press F10, confirm, and system will reboot

---

## Post-Installation Verification

### 1. Verify Both GPUs Detected

```bash
lspci | grep -i vga
```

**Expected**: Both RTX 2070 and RTX 3090 listed

### 2. Check PCIe Link Status

```bash
sudo lspci -vv | grep -A 20 "VGA compatible" | grep -E "VGA|LnkSta.*Width"
```

**Expected**: Both at x8 width

### 3. Verify NVIDIA Driver Detects Both GPUs

```bash
nvidia-smi
```

**Expected**: Two GPUs listed with proper names and memory

### 4. Check GPU Topology

```bash
nvidia-smi topo -m
```

Shows GPU interconnect and peer-to-peer access

### 5. Temperature & Power Monitoring

```bash
# Real-time monitoring
watch -n 1 nvidia-smi

# Check idle temperatures
nvidia-smi --query-gpu=index,name,temperature.gpu,power.draw --format=csv
```

**Healthy idle values:**
- RTX 2070: 30-45°C, <50W
- RTX 3090: 35-50°C, <50W

### 6. CUDA Verification

```bash
python3 -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'Device count: {torch.cuda.device_count()}'); [print(f'GPU {i}: {torch.cuda.get_device_name(i)}') for i in range(torch.cuda.device_count())]"
```

**Expected**: Device count: 2, both GPUs listed

---

## Troubleshooting

### System Won't POST / Black Screen

1. **Above 4G Decoding not enabled**
   - Reset CMOS, boot with only RTX 2070
   - Enable Above 4G Decoding in BIOS
   - Shut down, reinstall RTX 3090

2. **GPU not fully seated**
   - Power off, remove RTX 3090
   - Inspect PCIe slot for debris
   - Reinstall with firm pressure

### Only One GPU Shows in `nvidia-smi`

```bash
# Check if both visible to PCI bus
lspci | grep -i vga

# Check kernel messages
dmesg | grep -i nvidia | tail -20

# Update NVIDIA driver if needed
sudo add-apt-repository ppa:graphics-drivers/ppa
sudo apt update
sudo apt install nvidia-driver-550
sudo reboot
```

### High Temperatures on RTX 3090

**Normal temperatures:**
- Idle: 35-50°C
- Training: 70-85°C
- Maximum safe: 88°C

**Solutions if >85°C:**
1. Improve case airflow (add fans)
2. Adjust fan curve
3. Remove side panel temporarily to test

### Power Throttling

```bash
# Check power state
nvidia-smi -q -d POWER

# Increase power limit if needed (PSU has headroom)
sudo nvidia-smi -i 1 -pl 380
```

---

## Quick Reference Commands

```bash
# Check both GPUs detected
lspci | grep -i vga

# Verify NVIDIA driver sees both
nvidia-smi

# Check PCIe link status
sudo lspci -vv | grep -A 20 "VGA" | grep -E "VGA|LnkSta"

# Monitor GPUs in real-time
watch -n 1 nvidia-smi

# Check GPU topology
nvidia-smi topo -m

# Test CUDA access
python3 -c "import torch; print(torch.cuda.device_count())"

# Check temperatures
nvidia-smi --query-gpu=index,name,temperature.gpu,power.draw --format=csv

# Enable persistence mode
sudo nvidia-smi -pm 1
```

---

## System Specifications Summary

| Component | Details |
|-----------|---------|
| **Motherboard** | ASUS ROG Crosshair VIII Hero (Wi-Fi) |
| **CPU** | AMD Ryzen 9 3900X 12-Core (24 PCIe 4.0 lanes) |
| **GPU 1** | NVIDIA RTX 2070 8GB @ PCIe 4.0 x8 (PCIEX16_1) |
| **GPU 2** | NVIDIA RTX 3090 24GB @ PCIe 4.0 x8 (PCIEX16_2) |
| **PSU** | Super Flower Leadex Platinum III 1300W |
| **Power Cables** | 3x independent 8-pin PCIe cables |
| **Total GPU Power** | 525W max (175W + 350W) |
| **Power Headroom** | 535W (41% overhead) |
| **PCIe Bandwidth** | 16GB/s per GPU (PCIe 4.0 x8) |

---

## Next Steps: Software Integration

Once hardware is verified:

1. **CUDA Environment Variables** - Device visibility and memory allocation
2. **MLflow Multi-GPU Integration** - Experiment tracking with GPU metrics
3. **Ray Distributed Computing** - GPU resource allocation per worker
4. **Training Framework Configuration** - PyTorch DDP, TensorFlow, Horovod
5. **Monitoring & Observability** - Grafana dashboards for GPU metrics

**Document Version**: 1.0  
**Last Updated**: November 23, 2025  
**Status**: Hardware installation guide complete - awaiting physical installation
