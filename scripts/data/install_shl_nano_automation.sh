#!/usr/bin/env bash
# =============================================================================
# install_shl_nano_automation.sh — Install all SHML Platform systemd automation.
#
# Installs:
#   shl-nano-pipeline.timer   — nightly 02:00 full T8 pipeline run
#   shl-gitlab-sync.timer     — every 10min T8 GitLab issue sync
#   shl-platform-scan.timer   — every 30min repo scan + GitLab issue updates
#
# Usage:
#   bash scripts/data/install_shl_nano_automation.sh [--uninstall]
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
UNIT_SRC="$PLATFORM_DIR/scripts/monitoring/systemd"
UNIT_DST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GRN}[install]${NC} $*"; }
warn()  { echo -e "${YLW}[install WARN]${NC} $*"; }
error() { echo -e "${RED}[install ERROR]${NC} $*" >&2; exit 1; }

UNINSTALL=false
[[ "${1:-}" == "--uninstall" ]] && UNINSTALL=true

UNITS=(
    shl-nano-pipeline.service
    shl-nano-pipeline.timer
    shl-gitlab-sync.service
    shl-gitlab-sync.timer
    shl-platform-scan.service
    shl-platform-scan.timer
)

if [[ "$UNINSTALL" == "true" ]]; then
    info "Uninstalling SHL Platform automation …"
    for unit in "${UNITS[@]}"; do
        systemctl --user disable --now "$unit" 2>/dev/null || true
        rm -f "$UNIT_DST/$unit"
        info "  removed $unit"
    done
    systemctl --user daemon-reload
    info "Done."
    exit 0
fi

# ── Check systemd user session ────────────────────────────────────────────────
if ! systemctl --user list-unit-files >/dev/null 2>&1; then
    error "systemd user session not available. Enable with: loginctl enable-linger \$USER"
fi

# ── Make pipeline scripts executable ─────────────────────────────────────────
chmod +x \
    "$SCRIPT_DIR/shl_nano_pipeline.sh" \
    "$SCRIPT_DIR/update_gitlab_board.sh" \
    "$SCRIPT_DIR/setup_shl_nano.sh" \
    "$SCRIPT_DIR/run_shl_nano_sft.sh" \
    "$SCRIPT_DIR/start_shl_nano_server.sh"
chmod +x \
    "$PLATFORM_DIR/scripts/platform/scan_repo_state.sh" \
    "$PLATFORM_DIR/scripts/platform/gitlab_board_updater.py" 2>/dev/null || true

# ── Install units ─────────────────────────────────────────────────────────────
mkdir -p "$UNIT_DST"
for unit in "${UNITS[@]}"; do
    src="$UNIT_SRC/$unit"
    [[ -f "$src" ]] || { warn "Unit source not found: $src — skipping"; continue; }
    cp -f "$src" "$UNIT_DST/$unit"
    info "  installed $unit → $UNIT_DST/"
done

systemctl --user daemon-reload
info "Systemd user daemon reloaded."

# ── Enable and start timers ───────────────────────────────────────────────────
systemctl --user enable --now shl-nano-pipeline.timer
systemctl --user disable --now shl-nano-kanban.timer 2>/dev/null || true
systemctl --user enable --now shl-gitlab-sync.timer
systemctl --user enable --now shl-platform-scan.timer

# ── Run initial sync ────────────────────────────────────────────────────────────────
info "Running initial GitLab sync + platform scan …"
bash "$SCRIPT_DIR/update_gitlab_board.sh" && info "GitLab board updated." || \
    warn "GitLab board update failed (non-fatal)"
bash "$PLATFORM_DIR/scripts/platform/scan_repo_state.sh" && info "Platform scan done." || \
    warn "Platform scan failed (non-fatal)"

# ── Status summary ────────────────────────────────────────────────────────────
echo ""
info "══════════════════════════════════════════════════════════════"
info "SHML Platform automation installed."
info ""
info "Timers:"
systemctl --user list-timers shl-nano-pipeline.timer shl-gitlab-sync.timer shl-platform-scan.timer \
    --no-pager 2>/dev/null || true
echo ""
info "Commands:"
info "  Trigger pipeline now:   systemctl --user start shl-nano-pipeline.service"
info "  Sync T8 GitLab now:     systemctl --user start shl-gitlab-sync.service"
info "  Platform scan now:      systemctl --user start shl-platform-scan.service"
info "  Run specific stage:     bash scripts/data/shl_nano_pipeline.sh --stage=2"
info "  Pipeline logs:          journalctl --user -u shl-nano-pipeline.service -f"
info "  Scan logs:              journalctl --user -u shl-platform-scan.service -f"
info "  Uninstall:              bash scripts/data/install_shl_nano_automation.sh --uninstall"
info "══════════════════════════════════════════════════════════════"
