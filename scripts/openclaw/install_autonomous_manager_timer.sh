#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_SRC_DIR="$ROOT_DIR/scripts/openclaw/systemd"
UNIT_DST_DIR="$HOME/.config/systemd/user"

mkdir -p "$UNIT_DST_DIR"
cp -f "$UNIT_SRC_DIR/openclaw-autonomous-manager.service" "$UNIT_DST_DIR/"
cp -f "$UNIT_SRC_DIR/openclaw-autonomous-manager.timer" "$UNIT_DST_DIR/"

systemctl --user daemon-reload
systemctl --user enable --now openclaw-autonomous-manager.timer

echo "Installed and started: openclaw-autonomous-manager.timer"
echo "Check status: systemctl --user status openclaw-autonomous-manager.timer"
echo "Recent logs:  journalctl --user -u openclaw-autonomous-manager.service -n 100 --no-pager"
