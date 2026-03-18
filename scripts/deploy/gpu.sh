#!/usr/bin/env bash
# scripts/deploy/gpu.sh — NVIDIA GPU and MPS daemon management
#
# MPS at 100% thread allocation blocks Docker containers from accessing GPUs.
# This script stops MPS before starting Ray/inference to ensure GPU access.
#
# Provides: check_mps_status, stop_mps_daemon, verify_gpu_access

[[ -n "${_SHML_GPU_LOADED:-}" ]] && return 0
_SHML_GPU_LOADED=1

check_mps_status() {
    # Check if MPS control daemon is running (via systemd or standalone)
    if systemctl is-active --quiet nvidia-mps 2>/dev/null; then
        return 0  # MPS is running via systemd
    fi
    if pgrep -f "nvidia-cuda-mps-control" >/dev/null 2>&1; then
        return 0  # MPS is running standalone
    fi
    return 1  # MPS is not running
}

stop_mps_daemon() {
    if ! check_mps_status; then
        return 0  # Already stopped
    fi

    log_info "━━━ Stopping NVIDIA MPS Daemon ━━━"
    echo "MPS daemon blocks Docker GPU access - stopping for Ray containers..."

    # Try systemctl first (most reliable if MPS is managed by systemd)
    if systemctl is-active --quiet nvidia-mps 2>/dev/null; then
        echo -n "  Stopping nvidia-mps.service..."
        if sudo systemctl stop nvidia-mps 2>/dev/null; then
            echo -e " ${GREEN}✓${NC}"
            log_success "MPS service stopped"
            echo ""
            return 0
        fi
        echo -e " ${YELLOW}⚠${NC}"
    fi

    # Force kill any remaining MPS processes (don't try graceful - it hangs)
    echo -n "  Force killing MPS processes..."
    sudo pkill -9 nvidia-cuda-mps 2>/dev/null || true
    sleep 2

    # Verify stopped
    if ! pgrep -f "nvidia-cuda-mps-control" >/dev/null 2>&1; then
        echo -e " ${GREEN}✓${NC}"
        log_success "MPS daemon stopped"
    else
        echo -e " ${YELLOW}⚠${NC}"
        log_warn "MPS daemon may still be running (check systemd)"
    fi
    echo ""
}

verify_gpu_access() {
    echo -n "  Verifying GPU access..."
    if nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 | grep -q "NVIDIA"; then
        local gpu_count
        gpu_count=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l)
        echo -e " ${GREEN}✓${NC} ($gpu_count GPU(s) accessible)"
        return 0
    else
        echo -e " ${YELLOW}⚠${NC} (nvidia-smi failed)"
        return 1
    fi
}
