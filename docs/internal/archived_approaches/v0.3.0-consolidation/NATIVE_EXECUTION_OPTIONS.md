# Native Execution Options for Agent Code Execution

## Overview

This document compares approaches for allowing agents to execute code with varying levels of system access (sudo, docker, VMs) while maintaining security. Inspired by [Ariana.dev](https://ariana.dev/) which uses "isolated, hardened VMs with dedicated IPv4s".

## Current System Capabilities

| Feature | Status | Notes |
|---------|--------|-------|
| CPU Virtualization (AMD-V/SVM) | ✅ Available | AMD Ryzen 9 3900X supports SVM |
| KVM Module | ⚠️ Not loaded | Can be enabled with `modprobe kvm_amd` |
| Bubblewrap | ✅ Installed | v0.9.0 - unprivileged sandboxing |
| Firecracker | ❌ Not installed | Can be added |
| AppArmor | ✅ Enabled | Linux Security Module |
| Seccomp | ✅ Enabled | System call filtering |
| User Namespaces | ✅ Enabled | Unprivileged containers |
| Docker Runtimes | ✅ runc, nvidia | Standard container runtimes |

## Execution Isolation Spectrum

```
Most Restrictive ←────────────────────────────────────────→ Least Restrictive

┌─────────────────────────────────────────────────────────────────────────────┐
│  Container     Bubblewrap    MicroVM        Full VM        Native           │
│  (seccomp)     (namespaces)  (Firecracker)  (QEMU/KVM)     (sudo)           │
│                                                                              │
│  - No sudo     - Limited     - Full VM      - Full OS      - Full access    │
│  - No docker     syscalls      isolation      isolation    - Host system    │
│  - No network  - Restricted  - <125ms boot  - Slower boot  - Direct docker  │
│    by default    fs access   - <5MB memory  - More RAM     - Real networking│
│                - User-space  - KVM-based    - GPU passthru - Persistent     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Option 1: Bubblewrap Sandboxing (No KVM Required)

### Description
Bubblewrap (`bwrap`) uses Linux namespaces to create unprivileged sandboxes. No special kernel modules needed.

### Architecture
```
┌─────────────────────────────────────────────────────────────────┐
│                        Agent Request                             │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Sandbox Manager API                          │
│   - Validates request tier (viewer/developer/elevated/admin)     │
│   - Applies resource limits and security policy                  │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Bubblewrap Sandbox                           │
│   bwrap \                                                        │
│     --ro-bind /usr /usr \              # Read-only system        │
│     --tmpfs /tmp \                      # Ephemeral scratch      │
│     --bind $WORKSPACE /workspace \      # Project files          │
│     --unshare-pid \                     # Isolated process tree  │
│     --unshare-net \                     # No network by default  │
│     --seccomp $PROFILE \                # Syscall filtering      │
│     --die-with-parent \                 # Cleanup on exit        │
│     -- $COMMAND                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Tier Capabilities

| Tier | Filesystem | Network | Docker | Sudo | Duration |
|------|------------|---------|--------|------|----------|
| Viewer | Read-only `/workspace` | ❌ None | ❌ No | ❌ No | 30s |
| Developer | RW `/workspace` | ❌ None | ❌ No | ❌ No | 5m |
| Elevated | RW `/workspace` + `/tmp` | ✅ Filtered | ❌ No | ❌ No | 30m |
| Admin | RW host dirs | ✅ Full | ✅ Yes | ✅ Limited | Unlimited |

### Example Implementation

```python
# sandbox_manager.py
import subprocess
import tempfile
from pathlib import Path

class BubblewrapSandbox:
    """Tier-based bubblewrap sandboxing."""

    TIER_CONFIGS = {
        "viewer": {
            "timeout": 30,
            "network": False,
            "filesystem": "readonly",
            "seccomp": "strict",
        },
        "developer": {
            "timeout": 300,
            "network": False,
            "filesystem": "workspace-rw",
            "seccomp": "standard",
        },
        "elevated-developer": {
            "timeout": 1800,
            "network": "filtered",  # via proxy
            "filesystem": "workspace-rw",
            "seccomp": "permissive",
        },
        "admin": {
            "timeout": None,
            "network": True,
            "filesystem": "host-rw",
            "seccomp": "none",
        }
    }

    def execute(self, command: str, tier: str, workspace: Path) -> dict:
        config = self.TIER_CONFIGS.get(tier, self.TIER_CONFIGS["viewer"])

        bwrap_args = [
            "bwrap",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--symlink", "usr/bin", "/bin",
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            "--unshare-pid",
            "--die-with-parent",
            "--new-session",
        ]

        # Filesystem access
        if config["filesystem"] == "readonly":
            bwrap_args += ["--ro-bind", str(workspace), "/workspace"]
        elif config["filesystem"] in ("workspace-rw", "host-rw"):
            bwrap_args += ["--bind", str(workspace), "/workspace"]

        # Network isolation
        if not config["network"]:
            bwrap_args += ["--unshare-net"]

        # Seccomp filter
        if config["seccomp"] != "none":
            seccomp_file = f"/etc/seccomp/{config['seccomp']}.json"
            if Path(seccomp_file).exists():
                bwrap_args += ["--seccomp", seccomp_file]

        bwrap_args += ["--", "sh", "-c", command]

        result = subprocess.run(
            bwrap_args,
            capture_output=True,
            text=True,
            timeout=config["timeout"],
            cwd="/workspace"
        )

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode
        }
```

### Pros
- ✅ **Zero additional setup** - bubblewrap already installed
- ✅ **No KVM required** - works on any Linux system
- ✅ **Fast startup** - <10ms overhead
- ✅ **Low resource usage** - no VM memory overhead
- ✅ **Unprivileged** - runs without root

### Cons
- ❌ **Same kernel** - container escape vulnerabilities affect host
- ❌ **Limited sudo** - cannot grant real sudo (security risk)
- ❌ **No Docker-in-Docker** - can't run containers inside sandbox
- ❌ **Shared kernel resources** - less isolation than VMs

---

## Option 2: Firecracker MicroVMs (Kata-like, KVM Required)

### Description
Firecracker creates lightweight VMs using KVM. Each agent gets a full isolated VM that boots in <125ms with <5MB memory overhead.

### Architecture
```
┌─────────────────────────────────────────────────────────────────┐
│                        Agent Request                             │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     VM Pool Manager                              │
│   - Pre-warmed VM pool for instant allocation                   │
│   - Tier-based resource allocation (vCPUs, RAM)                 │
│   - Snapshotting for fast restore                               │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Firecracker MicroVM                            │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  Guest Kernel (minimal)                                  │   │
│   │  ┌─────────────────────────────────────────────────────┐│   │
│   │  │  Full userspace (Ubuntu/Alpine minimal)             ││   │
│   │  │  - Real sudo capability                             ││   │
│   │  │  - Docker daemon (optional)                         ││   │
│   │  │  - Full networking (via TAP)                        ││   │
│   │  │  - Mounted workspace via virtio                     ││   │
│   │  └─────────────────────────────────────────────────────┘│   │
│   └─────────────────────────────────────────────────────────┘   │
│   Communication: vsock, virtio-net, serial console               │
└─────────────────────────────────────────────────────────────────┘
```

### Setup Required

```bash
# 1. Load KVM module (one-time, add to /etc/modules)
sudo modprobe kvm_amd

# 2. Install Firecracker
ARCH=$(uname -m)
release_url="https://github.com/firecracker-microvm/firecracker/releases"
latest=$(curl -fsSL "${release_url}/latest" | grep -o 'tag/v[0-9]*\.[0-9]*\.[0-9]*' | head -1 | cut -d'/' -f2)
curl -L "${release_url}/download/${latest}/firecracker-${latest}-${ARCH}.tgz" | tar xz
sudo mv release-${latest}-${ARCH}/firecracker-${latest}-${ARCH} /usr/local/bin/firecracker
sudo mv release-${latest}-${ARCH}/jailer-${latest}-${ARCH} /usr/local/bin/jailer

# 3. Create minimal kernel and rootfs
# (Use pre-built images or build custom)
```

### Tier Capabilities (Full VM)

| Tier | vCPUs | RAM | Disk | Network | Docker | Sudo | Duration |
|------|-------|-----|------|---------|--------|------|----------|
| Viewer | 1 | 256MB | 1GB RO | ❌ None | ❌ No | ❌ No | 30s |
| Developer | 2 | 512MB | 5GB RW | ❌ Isolated | ❌ No | ✅ In VM | 5m |
| Elevated | 4 | 2GB | 20GB RW | ✅ NAT | ✅ In VM | ✅ In VM | 30m |
| Admin | 8 | 8GB | Unlimited | ✅ Bridge | ✅ In VM | ✅ In VM | Unlimited |

### Pros
- ✅ **Full VM isolation** - kernel-level separation
- ✅ **Real sudo** - full root inside VM (safe!)
- ✅ **Docker-in-VM** - can run containers inside
- ✅ **Fast boot** - <125ms with pre-warmed pool
- ✅ **Low overhead** - <5MB base memory per VM

### Cons
- ❌ **Requires KVM** - need to enable kernel module
- ❌ **No GPU passthrough** - Firecracker doesn't support GPU
- ❌ **More complex setup** - need kernel/rootfs images
- ❌ **Network complexity** - TAP devices, bridges

---

## Option 3: QEMU/KVM Full VMs (Maximum Flexibility)

### Description
Traditional VMs with QEMU provide maximum isolation and can support GPU passthrough for admin users needing full machine access.

### Architecture
```
┌─────────────────────────────────────────────────────────────────┐
│                        Agent Request                             │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     libvirt/QEMU Manager                         │
│   - Pre-configured VM templates per tier                        │
│   - GPU passthrough for admin tier                              │
│   - Snapshot/restore for quick state reset                      │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      QEMU/KVM Full VM                            │
│   - Full Ubuntu/Fedora installation                              │
│   - Dedicated vCPUs, RAM, storage                                │
│   - Optional GPU passthrough (admin only)                        │
│   - SSH/VNC access for interactive sessions                      │
└─────────────────────────────────────────────────────────────────┘
```

### Tier Capabilities

| Tier | vCPUs | RAM | GPU | Full Desktop | Notes |
|------|-------|-----|-----|--------------|-------|
| Developer | 2 | 4GB | ❌ No | ❌ No | CLI only |
| Elevated | 4 | 8GB | ❌ No | Optional | SSH access |
| Admin | 12 | 32GB | ✅ RTX 2070 | ✅ Yes | Full workstation |

### Pros
- ✅ **Maximum isolation** - complete VM separation
- ✅ **GPU passthrough** - can give admin GPU access
- ✅ **Full OS** - any software, any configuration
- ✅ **Persistent** - can maintain state across sessions
- ✅ **Remote desktop** - VNC/SPICE for GUI apps

### Cons
- ❌ **Heavy resource usage** - GBs of RAM per VM
- ❌ **Slower startup** - 10-30 seconds to boot
- ❌ **Complex management** - libvirt, networking
- ❌ **GPU passthrough complexity** - IOMMU groups, driver binding

---

## Option 4: Hybrid Approach (Recommended)

### Description
Use different isolation levels based on operation type:

```
┌─────────────────────────────────────────────────────────────────┐
│                       Operation Type                             │
└──────┬────────────────────────────────────────────────┬─────────┘
       │                                                │
       ▼                                                ▼
┌──────────────────┐                          ┌──────────────────┐
│  Quick Commands  │                          │  Long-Running /  │
│  (code snippets, │                          │  Interactive     │
│   file analysis) │                          │  (servers, VMs)  │
└────────┬─────────┘                          └────────┬─────────┘
         │                                             │
         ▼                                             ▼
┌──────────────────┐                          ┌──────────────────┐
│   Bubblewrap     │                          │  Firecracker or  │
│   (viewer,       │                          │  QEMU/KVM        │
│    developer)    │                          │  (elevated,      │
│                  │                          │   admin)         │
└──────────────────┘                          └──────────────────┘
```

### Implementation Matrix

| Operation | Viewer | Developer | Elevated | Admin |
|-----------|--------|-----------|----------|-------|
| Run code snippet | Bubblewrap | Bubblewrap | Bubblewrap | Direct |
| File operations | Bubblewrap (RO) | Bubblewrap (RW) | Bubblewrap | Direct |
| Install packages | ❌ Denied | Bubblewrap | MicroVM | Direct |
| Run Docker | ❌ Denied | ❌ Denied | MicroVM | Direct |
| Run server | ❌ Denied | ❌ Denied | MicroVM | Direct |
| GPU workloads | ❌ Denied | ❌ Denied | ❌ Denied | Direct/VM |
| System admin | ❌ Denied | ❌ Denied | ❌ Denied | Direct |

---

## Recommended Implementation Path

### Phase 1: Bubblewrap for All (Week 1-2)
- Implement tiered bubblewrap sandboxes
- No additional infrastructure needed
- Covers 90% of use cases safely

### Phase 2: Add Firecracker for Elevated+ (Week 3-4)
- Enable KVM module
- Set up Firecracker VM pool
- Enable Docker-in-VM for elevated developers

### Phase 3: Admin Host Access (Week 5+)
- Implement audit logging for direct access
- Create restricted sudo profiles
- Optional: GPU-passthrough VM for admin workstation

---

## Quick Start: Bubblewrap Implementation

```bash
# Test bubblewrap sandbox manually:
bwrap \
  --ro-bind /usr /usr \
  --ro-bind /lib /lib \
  --ro-bind /lib64 /lib64 \
  --symlink usr/bin /bin \
  --proc /proc \
  --dev /dev \
  --tmpfs /tmp \
  --unshare-pid \
  --unshare-net \
  --die-with-parent \
  --new-session \
  -- python3 -c "print('Hello from sandbox!')"
```

---

## Security Considerations

### Bubblewrap
- Uses `PR_SET_NO_NEW_PRIVS` to prevent privilege escalation
- Seccomp filters block dangerous syscalls
- AppArmor provides MAC enforcement

### Firecracker
- KVM-based isolation (hypervisor level)
- Minimal device model reduces attack surface
- Jailer adds namespace/cgroup isolation around VMM

### Admin Access
- All operations logged to append-only audit log
- HMAC signatures prevent log tampering
- Real-time alerts for sensitive operations

---

## Decision Matrix

| Factor | Bubblewrap | Firecracker | QEMU/KVM |
|--------|------------|-------------|----------|
| Setup Complexity | ⭐ Easy | ⭐⭐ Medium | ⭐⭐⭐ Hard |
| Resource Usage | ⭐ Low | ⭐⭐ Medium | ⭐⭐⭐ High |
| Isolation Level | ⭐⭐ Good | ⭐⭐⭐ Excellent | ⭐⭐⭐ Excellent |
| Startup Time | ⭐⭐⭐ <10ms | ⭐⭐⭐ <125ms | ⭐ 10-30s |
| GPU Support | ❌ No | ❌ No | ✅ Yes |
| Docker Inside | ❌ No | ✅ Yes | ✅ Yes |
| Real Sudo | ❌ No | ✅ Yes (in VM) | ✅ Yes (in VM) |

---

## Conclusion

For your platform with ~48GB available RAM and focus on developer productivity:

1. **Start with Bubblewrap** - handles most code execution needs with zero setup
2. **Add Firecracker** when you need Docker-in-sandbox or real sudo (elevated tier)
3. **Reserve QEMU/KVM** for admin-only GPU workloads or persistent dev environments

This matches Ariana.dev's approach of "isolated, hardened VMs" while being more resource-efficient for your single-server deployment.
