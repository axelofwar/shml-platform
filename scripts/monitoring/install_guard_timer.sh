#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_SRC_DIR="$ROOT_DIR/scripts/monitoring/systemd"
UNIT_DST_DIR="$HOME/.config/systemd/user"

mkdir -p "$UNIT_DST_DIR"

# Migrate from deprecated OpenClaw timer if present
if systemctl --user list-unit-files >/dev/null 2>&1; then
	if systemctl --user list-unit-files | grep -q '^openclaw-autonomous-manager.timer'; then
		systemctl --user disable --now openclaw-autonomous-manager.timer 2>/dev/null || true
	fi
	if systemctl --user list-unit-files | grep -q '^openclaw-autonomous-manager.service'; then
		systemctl --user disable --now openclaw-autonomous-manager.service 2>/dev/null || true
	fi
fi
rm -f "$UNIT_DST_DIR/openclaw-autonomous-manager.service" "$UNIT_DST_DIR/openclaw-autonomous-manager.timer"

cp -f "$UNIT_SRC_DIR/autonomous-guard-remediation.service" "$UNIT_DST_DIR/"
cp -f "$UNIT_SRC_DIR/autonomous-guard-remediation.timer" "$UNIT_DST_DIR/"

systemctl --user daemon-reload
systemctl --user enable --now autonomous-guard-remediation.timer

echo "Installed and started: autonomous-guard-remediation.timer"
echo "Check status: systemctl --user status autonomous-guard-remediation.timer"
echo "Recent logs:  journalctl --user -u autonomous-guard-remediation.service -n 100 --no-pager"
