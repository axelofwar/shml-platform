#!/usr/bin/env python3
"""
Watchdog Admin — Operations Control Center.

Zero-dependency HTTP server providing:
- Live watchdog status dashboard (HTML)
- API endpoints for pause/resume/stop controls
- Audit log viewer with intervention history
- Terminal-style log output
- Platform state JSON

Routes:
  GET  /             → HTML dashboard
  GET  /health       → Health check
  GET  /api/status   → Current status + platform state
  GET  /api/audit    → Last 100 audit entries
  GET  /api/logs     → Last 200 log lines
  POST /api/control  → {action: "pause"|"resume"|"stop-all"}

Port: 8099 (configurable via ADMIN_PORT)
"""

import http.server
import json
import os
import html as html_mod
from pathlib import Path
from urllib.parse import urlparse

STATE_DIR = os.getenv("WATCHDOG_STATE_DIR", "/var/lib/watchdog")
LOG_DIR = os.getenv("WATCHDOG_LOG_DIR", "/var/log/watchdog")
CONTROL_FILE = os.path.join(STATE_DIR, "control")
AUDIT_LOG = os.path.join(LOG_DIR, "audit.log")
WATCHDOG_LOG = os.path.join(LOG_DIR, "watchdog.log")
PLATFORM_STATE = os.path.join(STATE_DIR, "platform_state.json")
PORT = int(os.getenv("ADMIN_PORT", "8099"))
BASE_PATH = os.getenv("BASE_PATH", "/watchdog").rstrip("/")
DOZZLE_URL = os.getenv("DOZZLE_URL", "/logs/")
GRAFANA_URL = os.getenv("GRAFANA_DASHBOARD_URL", "/grafana/d/watchdog-overview")


def read_file_lines(path, n=100):
    """Read last N lines from a file."""
    if not os.path.exists(path):
        return []
    try:
        lines = Path(path).read_text().strip().split("\n")
        return lines[-n:]
    except Exception:
        return []


def read_json_file(path):
    """Read a JSON file safely."""
    if not os.path.exists(path):
        return None
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


def get_mode():
    """Get current watchdog operational mode."""
    if os.path.exists(CONTROL_FILE):
        mode = Path(CONTROL_FILE).read_text().strip()
        return mode if mode else "active"
    return "active"


# ---------------------------------------------------------------------------
# HTML Dashboard Template
# Uses __PLACEHOLDER__ tokens to avoid CSS/JS brace conflicts
# ---------------------------------------------------------------------------
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Watchdog Operations Center</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #0d1117; color: #c9d1d9; }
  .header { background: #161b22; border-bottom: 1px solid #30363d;
            padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; }
  .header h1 { font-size: 20px; font-weight: 600; }
  .status { padding: 4px 12px; border-radius: 12px; font-size: 13px;
            font-weight: 600; text-transform: uppercase; }
  .status-active { background: #1a7f37; color: #fff; }
  .status-paused { background: #9e6a03; color: #fff; }
  .status-unknown { background: #6e7681; color: #fff; }
  .container { max-width: 1400px; margin: 0 auto; padding: 20px 24px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
           gap: 12px; margin-bottom: 20px; }
  .card { background: #161b22; border: 1px solid #30363d;
          border-radius: 8px; padding: 16px; text-align: center; }
  .card .value { font-size: 28px; font-weight: 700; color: #58a6ff; }
  .card .label { font-size: 12px; color: #8b949e; margin-top: 4px; text-transform: uppercase; }
  .card.warn .value { color: #d29922; }
  .card.danger .value { color: #f85149; }
  .card.ok .value { color: #3fb950; }
  .section { background: #161b22; border: 1px solid #30363d;
             border-radius: 8px; margin-bottom: 20px; overflow: hidden; }
  .section-header { padding: 12px 16px; border-bottom: 1px solid #30363d;
                    font-weight: 600; font-size: 14px;
                    display: flex; justify-content: space-between; align-items: center; }
  .section-header .badge { background: #30363d; padding: 2px 8px;
                           border-radius: 10px; font-size: 11px; font-weight: 400; }
  .terminal { background: #010409; padding: 12px 16px;
              font-family: 'SFMono-Regular', Consolas, monospace;
              font-size: 12px; line-height: 1.6; max-height: 400px;
              overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
  .terminal .line { color: #8b949e; }
  .terminal .line.warn { color: #d29922; }
  .terminal .line.error { color: #f85149; }
  .terminal .line.ok { color: #3fb950; }
  .terminal .line.action { color: #a371f7; }
  .audit-table { width: 100%; border-collapse: collapse; }
  .audit-table th { text-align: left; padding: 8px 12px; font-size: 12px;
                    color: #8b949e; border-bottom: 1px solid #30363d; }
  .audit-table td { padding: 6px 12px; font-size: 13px; border-bottom: 1px solid #21262d;
                    font-family: monospace; }
  .controls { display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
  .btn { padding: 8px 20px; border: 1px solid #30363d; border-radius: 6px;
         font-size: 14px; font-weight: 500; cursor: pointer; transition: all 0.15s; }
  .btn-pause { background: #9e6a03; color: #fff; border-color: #9e6a03; }
  .btn-pause:hover { background: #845306; }
  .btn-resume { background: #1a7f37; color: #fff; border-color: #1a7f37; }
  .btn-resume:hover { background: #116329; }
  .btn-stop { background: #da3633; color: #fff; border-color: #da3633; }
  .btn-stop:hover { background: #b62324; }
  .links { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }
  .links a { color: #58a6ff; text-decoration: none; padding: 6px 14px;
             background: #21262d; border-radius: 6px; font-size: 13px; }
  .links a:hover { background: #30363d; }
  .flash { position: fixed; top: 60px; right: 24px; padding: 10px 20px;
           border-radius: 6px; font-size: 13px; z-index: 100;
           animation: fadeout 3s forwards; }
  .flash-ok { background: #1a7f37; color: #fff; }
  .flash-err { background: #da3633; color: #fff; }
  @keyframes fadeout { 0%,70% { opacity: 1; } 100% { opacity: 0; } }
</style>
</head>
<body>
<div class="header">
  <h1>&#x1F6E1;&#xFE0F; Watchdog Operations Center</h1>
  <span class="status __MODE_CLASS__">__MODE_TEXT__</span>
</div>
<div class="container">
  <div class="controls">
    <button class="btn btn-pause" onclick="control('pause')">&#x23F8; Pause Remediation</button>
    <button class="btn btn-resume" onclick="control('resume')">&#x25B6; Resume</button>
    <button class="btn btn-stop" onclick="if(confirm('Stop ALL running interventions?'))control('stop-all')">&#x1F6D1; Stop All</button>
  </div>
  <div class="cards">__CARDS_HTML__</div>
  <div class="links">
    <a href="__GRAFANA_URL__" target="_blank">&#x1F4CA; Grafana Dashboard</a>
    <a href="__DOZZLE_URL__" target="_blank">&#x1F4CB; Live Logs (Dozzle)</a>
    <a href="__BASE_PATH__/api/status" target="_blank">&#x1F4C4; Status API</a>
    <a href="__BASE_PATH__/api/audit" target="_blank">&#x1F4DC; Audit API</a>
  </div>
  <div class="section">
    <div class="section-header">
      Interventions (Audit Log)
      <span class="badge">__AUDIT_COUNT__ entries</span>
    </div>
    <div style="max-height: 300px; overflow-y: auto;">
      <table class="audit-table">
        <thead><tr><th>Time</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead>
        <tbody>__AUDIT_ROWS__</tbody>
      </table>
    </div>
  </div>
  <div class="section">
    <div class="section-header">
      Watchdog Terminal
      <span class="badge">__LOG_COUNT__ lines</span>
    </div>
    <div class="terminal" id="terminal">__LOG_HTML__</div>
  </div>
</div>
<script>
  var BASE = '__BASE_PATH__';
  function control(action) {
    fetch(BASE + '/api/control', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: action})
    }).then(function(r) { return r.json(); })
      .then(function(d) {
        showFlash(d.status === 'ok' ? action + ' applied' : d.error, d.status === 'ok');
        setTimeout(function() { location.reload(); }, 1500);
      }).catch(function(e) { showFlash('Request failed: ' + e.message, false); });
  }
  function showFlash(msg, ok) {
    var f = document.createElement('div');
    f.className = 'flash ' + (ok ? 'flash-ok' : 'flash-err');
    f.textContent = msg;
    document.body.appendChild(f);
    setTimeout(function() { f.remove(); }, 3000);
  }
  var term = document.getElementById('terminal');
  if (term) term.scrollTop = term.scrollHeight;
  setTimeout(function() { location.reload(); }, 30000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------
class WatchdogAdminHandler(http.server.BaseHTTPRequestHandler):
    """Serves the admin dashboard and control API."""

    def log_message(self, format, *args):
        pass  # Suppress request logs

    def do_GET(self):
        path = urlparse(self.path).path
        if BASE_PATH and path.startswith(BASE_PATH):
            path = path[len(BASE_PATH) :]
        path = path.rstrip("/") or "/"

        if path == "/health":
            self._json(
                {"status": "ok", "service": "watchdog-admin", "mode": get_mode()}
            )
        elif path == "/":
            self._serve_dashboard()
        elif path == "/api/status":
            self._json(
                {
                    "mode": get_mode(),
                    "platform_state": read_json_file(PLATFORM_STATE),
                    "recent_audit": read_file_lines(AUDIT_LOG, 20),
                }
            )
        elif path == "/api/audit":
            entries = read_file_lines(AUDIT_LOG, 100)
            self._json({"entries": entries, "total": len(entries)})
        elif path == "/api/logs":
            lines = read_file_lines(WATCHDOG_LOG, 200)
            self._json({"lines": lines, "total": len(lines)})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if BASE_PATH and path.startswith(BASE_PATH):
            path = path[len(BASE_PATH) :]
        path = path.rstrip("/")

        if path == "/api/control":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            try:
                data = json.loads(body)
                action = data.get("action", "")
                if action in ("pause", "resume", "stop-all"):
                    if action == "resume":
                        if os.path.exists(CONTROL_FILE):
                            os.remove(CONTROL_FILE)
                    else:
                        Path(CONTROL_FILE).write_text(action)
                    self._json({"status": "ok", "action": action, "mode": get_mode()})
                else:
                    self._json({"error": f"unknown action: {action}"}, 400)
            except json.JSONDecodeError:
                self._json({"error": "invalid JSON"}, 400)
        else:
            self._json({"error": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, data, status=200):
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_dashboard(self):
        mode = get_mode()
        platform = read_json_file(PLATFORM_STATE) or {}
        audit = read_file_lines(AUDIT_LOG, 30)
        logs = read_file_lines(WATCHDOG_LOG, 100)

        # Mode styling
        if mode == "active":
            mode_class, mode_text = "status-active", "&#x25CF; ACTIVE"
        elif mode in ("pause", "paused"):
            mode_class, mode_text = "status-paused", "&#x23F8; PAUSED"
        else:
            mode_class, mode_text = "status-unknown", html_mod.escape(mode.upper())

        # Stats from platform_state.json
        containers = platform.get("containers", {})
        watchdog_cfg = platform.get("watchdog", {})
        gpu_list = platform.get("gpus", [])
        training = platform.get("training_jobs", [])
        total = containers.get("total", "?")
        unhealthy = containers.get("unhealthy", "?")

        # Count interventions from audit
        restart_count = sum(
            1 for e in audit if "ACTION=RESTART " in e or "ACTION=PREEMPTIVE" in e
        )
        escalation_count = sum(1 for e in audit if "ACTION=AGENT_" in e)
        oom_count = sum(1 for e in audit if "ACTION=OOM_" in e)

        uh_class = "ok"
        if isinstance(unhealthy, int) and unhealthy > 0:
            uh_class = "warn" if unhealthy < 3 else "danger"

        cards = [
            ("ok", str(total), "Containers"),
            (uh_class, str(unhealthy), "Unhealthy"),
            ("warn" if restart_count else "", str(restart_count), "Restarts (30m)"),
            ("warn" if escalation_count else "", str(escalation_count), "Escalations"),
            ("danger" if oom_count else "", str(oom_count), "OOM Kills"),
            ("ok" if training else "", str(len(training)), "Training Jobs"),
            ("ok", str(len(gpu_list)), "GPUs"),
            ("", str(watchdog_cfg.get("check_interval", "?")), "Check Interval"),
        ]

        cards_html = ""
        for cls, val, label in cards:
            cards_html += (
                f'<div class="card {cls}">'
                f'<div class="value">{val}</div>'
                f'<div class="label">{label}</div></div>\n'
            )

        # Audit table rows (newest first)
        audit_rows = ""
        for entry in reversed(audit):
            parts = entry.split(" ", 1)
            ts = html_mod.escape(parts[0].strip("[]")) if parts else ""
            rest = parts[1] if len(parts) > 1 else ""
            action = target = detail = ""
            for token in rest.split(" "):
                if token.startswith("ACTION="):
                    action = token[7:]
                elif token.startswith("TARGET="):
                    target = token[7:]
            if "DETAIL=" in rest:
                detail = rest.split("DETAIL=", 1)[1]
            action = html_mod.escape(action)
            target = html_mod.escape(target)
            detail = html_mod.escape(detail)
            row_style = ""
            if "RESTART" in action:
                row_style = 'style="color:#d29922"'
            elif "AGENT" in action:
                row_style = 'style="color:#a371f7"'
            elif "OOM" in action:
                row_style = 'style="color:#f85149"'
            elif "RECOVER" in action:
                row_style = 'style="color:#3fb950"'
            audit_rows += (
                f"<tr {row_style}><td>{ts}</td><td>{action}</td>"
                f"<td>{target}</td><td>{detail}</td></tr>\n"
            )

        # Terminal log lines with color coding
        log_html = ""
        for raw in logs:
            line = html_mod.escape(raw)
            cls = "line"
            lower = raw.lower()
            if "warn" in lower:
                cls = "line warn"
            elif any(k in lower for k in ("error", "critical", "alert")):
                cls = "line error"
            elif "ok:" in lower or "recovered" in lower:
                cls = "line ok"
            elif any(
                k in lower for k in ("remediate", "restart", "agent", "preemptive")
            ):
                cls = "line action"
            log_html += f'<div class="{cls}">{line}</div>\n'

        # Render template
        page = DASHBOARD_HTML
        page = page.replace("__MODE_CLASS__", mode_class)
        page = page.replace("__MODE_TEXT__", mode_text)
        page = page.replace("__CARDS_HTML__", cards_html)
        page = page.replace("__GRAFANA_URL__", GRAFANA_URL)
        page = page.replace("__DOZZLE_URL__", DOZZLE_URL)
        page = page.replace("__BASE_PATH__", BASE_PATH)
        page = page.replace("__AUDIT_COUNT__", str(len(audit)))
        page = page.replace("__AUDIT_ROWS__", audit_rows)
        page = page.replace("__LOG_COUNT__", str(len(logs)))
        page = page.replace("__LOG_HTML__", log_html)

        body = page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(f"Watchdog Admin starting on port {PORT} (base path: {BASE_PATH})")
    server = http.server.HTTPServer(("0.0.0.0", PORT), WatchdogAdminHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down")
        server.shutdown()
