#!/usr/bin/env python3
"""
Service Connection Map Generator (Auto-Discovery)
==================================================
Scans docker-compose files, Traefik labels, and depends_on declarations to
auto-discover platform services and their connections.

Manual supplements add non-Docker services (MCP, Obsidian, GEPA) and planned
connections that can't be inferred from compose files.

Output: docs/obsidian-vault/20-Decisions/CONNECTION_MAP.md

CLI:
    python scripts/generate_connection_map.py            # generate map
    python scripts/generate_connection_map.py --drift    # drift check only (exit 1 if drift found)
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from textwrap import dedent

try:
    import yaml
except ImportError:
    sys.exit("ERROR: PyYAML required — pip install pyyaml")

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_DIR = REPO_ROOT / "deploy" / "compose"
OUT_PATH = REPO_ROOT / "docs" / "obsidian-vault" / "20-Decisions" / "CONNECTION_MAP.md"

SKIP_FILENAMES = {
    "docker-compose.networks.yml",
    "docker-compose.secrets.yml",
    "docker-compose.dev.yml",
}

EXTRA_COMPOSE_DIRS = [
    "chat-ui-v2",
    "inference",
    "inference/agent-service",
    "inference/chat-api",
    "inference/embedding-service",
    "inference/gpu-manager",
    "inference/qwopus",
    "inference/sam-audio",
    "mlflow-server",
    "ray_compute",
    "monitoring/dcgm-exporter",
]

# Legacy directories — decommissioned, excluded from map generation
# inference/coding-model → superseded by inference/qwopus

STATUS_EMOJI = {
    "connected": "🟢",
    "configured": "🟡",
    "disconnected": "🔴",
    "planned": "⚪",
}
STATUS_MERMAID_STYLE = {
    "connected": "stroke:#22c55e,stroke-width:2px",
    "configured": "stroke:#eab308,stroke-width:1.5px,stroke-dasharray:5 3",
    "disconnected": "stroke:#ef4444,stroke-width:1.5px,stroke-dasharray:3 3",
    "planned": "stroke:#94a3b8,stroke-width:1px,stroke-dasharray:2 4",
}
LAYER_COLOR = {
    "gateway": "fill:#1e3a5f,color:#fff",
    "auth": "fill:#312e81,color:#fff",
    "inference": "fill:#064e3b,color:#fff",
    "training": "fill:#1c1917,color:#fff",
    "data": "fill:#134e4a,color:#fff",
    "storage": "fill:#374151,color:#fff",
    "monitoring": "fill:#3b0764,color:#fff",
    "tooling": "fill:#1a1a1a,color:#ddd",
}


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _resolve_env(s: str) -> str:
    """Resolve ${VAR:-default} → default."""
    return re.sub(r"\$\{[^:}]+:-([^}]+)\}", r"\1", str(s))


def _make_id(name: str) -> str:
    """Consistent ID: strip 'shml-' prefix, lowercase, non-alnum → underscore."""
    name = _resolve_env(name).lower()
    name = re.sub(r"^shml[-_]", "", name)
    return re.sub(r"[^a-z0-9]+", "_", name).strip("_")


def _safe_mermaid(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", s)


def _infer_layer(compose_path: Path, container_name: str) -> str:
    """Infer service layer from compose file path and container name."""
    rel = str(compose_path.relative_to(REPO_ROOT))
    name = container_name.lower()

    if "inference/" in rel:
        return "inference"
    if "ray_compute/" in rel:
        return "training"
    if "mlflow-server/" in rel:
        return "data"
    if any(k in rel for k in ("dcgm-exporter", "logging", "tracing")):
        return "monitoring"
    if "watchdog" in rel:
        return "monitoring"
    if "nemoclaw" in rel:
        return "tooling"

    layers = [
        (["traefik"], "gateway"),
        (["oauth2", "fusionauth", "role-auth", "role_auth"], "auth"),
        (["postgres", "redis"], "storage"),
        (
            [
                "prometheus", "grafana", "alertmanager", "cadvisor",
                "node-exporter", "node_exporter", "pushgateway", "loki",
                "promtail", "tempo", "otel", "slo-exporter", "slo_exporter",
                "feature-scheduler", "feature_scheduler", "nightly-test",
                "nightly_test", "dcgm",
            ],
            "monitoring",
        ),
        (["mlflow", "nessie", "fiftyone"], "data"),
        (
            [
                "homer", "code-server", "code_server", "gitlab", "sba",
                "docker-proxy", "docker_proxy", "backup", "webhook",
            ],
            "tooling",
        ),
        (["ray"], "training"),
    ]
    for keywords, layer in layers:
        if any(k in name for k in keywords):
            return layer
    return "tooling"


# ═══════════════════════════════════════════════════════════════════════════
# COMPOSE FILE SCANNER
# ═══════════════════════════════════════════════════════════════════════════


def _find_compose_files() -> list[Path]:
    files: list[Path] = []
    for f in sorted(COMPOSE_DIR.glob("docker-compose*.yml")):
        if f.name not in SKIP_FILENAMES:
            files.append(f)
    for d in EXTRA_COMPOSE_DIRS:
        # Check both docker-compose.yml and docker-compose.*.yml patterns
        base = REPO_ROOT / d
        p = base / "docker-compose.yml"
        if p.exists():
            files.append(p)
        for extra in sorted(base.glob("docker-compose.*.yml")):
            if extra.name not in SKIP_FILENAMES and extra not in files:
                files.append(extra)
    return files


def scan_compose_files() -> tuple[dict[str, tuple], list[tuple]]:
    """
    Parse compose files → (services_dict, connections_list).

    services_dict: {svc_id: (svc_id, label, layer, description)}
    connections:   [(source_id, target_id, label, status), ...]
    """
    services: dict[str, tuple] = {}
    connections: list[tuple] = []
    seen_conn: set[tuple[str, str]] = set()

    for compose_file in _find_compose_files():
        try:
            data = yaml.safe_load(compose_file.read_text())
        except Exception as e:
            print(f"WARNING: {compose_file}: {e}", file=sys.stderr)
            continue
        if not data or "services" not in data:
            continue

        rel = str(compose_file.relative_to(REPO_ROOT))

        # Map compose service key → normalized svc_id within this file
        key_to_id: dict[str, str] = {}
        for svc_key, cfg in data["services"].items():
            if not isinstance(cfg, dict):
                continue
            cname = _resolve_env(cfg.get("container_name", svc_key))
            key_to_id[svc_key] = _make_id(cname)

        for svc_key, cfg in data["services"].items():
            if not isinstance(cfg, dict):
                continue
            cname = _resolve_env(cfg.get("container_name", svc_key))
            svc_id = _make_id(cname)
            layer = _infer_layer(compose_file, cname)
            label = cname.replace("-", " ").replace("_", " ").title()

            image = _resolve_env(cfg.get("image", ""))
            build = cfg.get("build")
            desc = rel
            if image:
                desc = f"{image.split(':')[0].split('/')[-1]} ({rel})"
            elif build:
                desc = f"custom build ({rel})"

            if svc_id not in services:
                services[svc_id] = (svc_id, label, layer, desc)

            # ── Traefik routing ─────────────────────────────────────
            labels_raw = cfg.get("labels", [])
            if isinstance(labels_raw, dict):
                labels_raw = [f"{k}={v}" for k, v in labels_raw.items()]
            labels_list = [str(lbl) for lbl in labels_raw]

            routes: list[str] = []
            for lbl in labels_list:
                m = re.search(
                    r"traefik\.http\.routers\.[^.]+\.rule=.*?"
                    r"PathPrefix\(`([^`]+)`\)",
                    lbl,
                )
                if m:
                    routes.append(m.group(1))
            routes = sorted(set(routes))

            if routes:
                key = ("traefik", svc_id)
                if key not in seen_conn:
                    route_str = ", ".join(routes[:2])
                    if len(routes) > 2:
                        route_str += f" +{len(routes) - 2}"
                    connections.append(("traefik", svc_id, route_str, "connected"))
                    seen_conn.add(key)

                if any("oauth2-auth" in lbl for lbl in labels_list):
                    key2 = ("oauth2_proxy", svc_id)
                    if key2 not in seen_conn:
                        connections.append(
                            ("oauth2_proxy", svc_id, "auth middleware", "connected")
                        )
                        seen_conn.add(key2)

            # ── depends_on ──────────────────────────────────────────
            depends = cfg.get("depends_on", {})
            if isinstance(depends, list):
                depends = {d: {} for d in depends}
            if isinstance(depends, dict):
                for dep_key in depends:
                    dep_id = key_to_id.get(dep_key, _make_id(dep_key))
                    key = (svc_id, dep_id)
                    if key not in seen_conn:
                        connections.append(
                            (svc_id, dep_id, "depends_on", "connected")
                        )
                        seen_conn.add(key)

            # ── Environment-based storage deps ──────────────────────
            env = cfg.get("environment", {})
            env_str = ""
            if isinstance(env, dict):
                env_str = " ".join(
                    f"{k}={v}" for k, v in env.items() if v is not None
                )
            elif isinstance(env, list):
                env_str = " ".join(str(e) for e in env)
            env_upper = env_str.upper()

            patterns = [
                (["POSTGRES", "DATABASE_URL", "DB_HOST", "PGHOST", "DATASOURCE"], "postgres"),
                (["REDIS"], "redis"),
                (["MLFLOW_TRACKING"], "mlflow_server"),
                (["RAY_HEAD", "RAY_ADDRESS"], "ray_head"),
            ]
            for keywords, dep_id in patterns:
                if any(kw in env_upper for kw in keywords):
                    key = (svc_id, dep_id)
                    if key not in seen_conn:
                        connections.append(
                            (svc_id, dep_id, "env config", "configured")
                        )
                        seen_conn.add(key)

    return services, connections


# ═══════════════════════════════════════════════════════════════════════════
# MANUAL SUPPLEMENTS  (non-discoverable items)
# ═══════════════════════════════════════════════════════════════════════════

# Override auto-discovered labels / descriptions / layers
SERVICE_META: dict[str, dict[str, str]] = {
    "traefik": {"label": "Traefik v2.11", "description": "Reverse proxy / TLS / routing"},
    "oauth2_proxy": {"label": "OAuth2 Proxy", "description": "OAuth2 PKCE middleware"},
    "fusionauth": {"label": "FusionAuth 1.52", "description": "SSO / OAuth2 identity provider"},
    "role_auth": {"label": "Role-Auth Service", "description": "RBAC enforcer (admin/dev/user)"},
    "agent_service": {"label": "Agent Service (FastAPI)", "description": "ACE pattern agent; /api/agent/*"},
    "chat_api": {"label": "Chat API", "description": "OpenAI-compatible /v1/chat endpoint"},
    "postgres": {"label": "Postgres 15 + pgvector", "description": "Shared DB: mlflow, ray, inference"},
    "redis": {"label": "Redis 7", "description": "Session cache, pub/sub, rate limiting"},
    "global_prometheus": {"label": "Prometheus (global)", "description": "Metrics scraper"},
    "unified_grafana": {"label": "Grafana (unified)", "description": "All dashboards"},
    "pushgateway": {"label": "Pushgateway", "description": "Batch job metrics sink"},
    "alertmanager": {"label": "Alertmanager", "description": "Alert routing → Telegram"},
    "homer": {"label": "Homer Dashboard", "description": "Platform service index"},
    "gitlab": {"label": "GitLab CE", "description": "Internal git + CI/CD"},
    "gitlab_runner": {"label": "GitLab Runner", "description": "CI/CD runner"},
    "code_server": {"label": "Code Server", "description": "VS Code in browser"},
    "nessie": {"label": "Project Nessie (Iceberg)", "description": "Git-for-data catalog"},
    "fiftyone": {"label": "FiftyOne", "description": "Dataset inspection & model eval UI"},
    "fiftyone_mongodb": {"label": "FiftyOne MongoDB", "description": "MongoDB for FiftyOne datasets"},
    "loki": {"label": "Loki", "description": "Log aggregation"},
    "tempo": {"label": "Tempo", "description": "Distributed tracing backend"},
    "postgres_backup": {"label": "Postgres Backup", "description": "Automated DB backups"},
    "sba_resource_portal": {"label": "SBA Resource Portal", "description": "Grant discovery UI"},
    "watchdog": {"label": "Watchdog", "description": "Self-healing container monitor"},
    "watchdog_admin": {"label": "Watchdog Admin", "description": "Watchdog web dashboard"},
    "docker_proxy": {"label": "Docker Proxy (read-only)", "description": "Restricted Docker API for sandboxes"},
    "coding_model_fallback": {"label": "coding-model-fallback", "description": "Fallback coding model"},
    "coding_manager": {"label": "Coding Manager", "description": "qwopus-coding lifecycle manager (GPU yield)"},
    "qwopus_coding": {"label": "Qwopus Coding", "description": "Qwen3.5 reasoning distill LLM"},
    "watchdog_llm": {"label": "Watchdog LLM", "description": "Qwen3-4B always-on watchdog triage (GPU 1)"},
    "embedding_service": {"label": "Embedding Service", "description": "Text embedding API"},
    "gpu_manager": {"label": "GPU Manager", "description": "GPU allocation orchestrator"},
    "gpu_control_proxy": {"label": "GPU Control Proxy", "description": "Docker proxy for GPU manager"},
    "openshell_gateway": {"label": "OpenShell Gateway (NemoClaw)", "description": "Code execution sandbox"},
    "nemoclaw_factory": {"label": "NemoClaw Factory", "description": "Sandbox container factory"},
    "mlflow_server": {"label": "MLflow Server", "description": "Experiment tracking / model registry"},
    "mlflow_nginx": {"label": "MLflow Nginx", "description": "Reverse proxy for MLflow"},
    "mlflow_api": {"label": "MLflow API", "description": "Enhanced MLflow REST API"},
    "mlflow_prometheus": {"label": "MLflow Prometheus", "description": "MLflow metrics scraper"},
    "ray_head": {"label": "Ray Head Node", "description": "Distributed training cluster head"},
    "ray_compute_api": {"label": "Ray Compute API", "description": "Job submission & GPU orchestration"},
    "ray_compute_ui": {"label": "Ray Compute UI", "description": "Web dashboard for Ray jobs"},
    "ray_prometheus": {"label": "Ray Prometheus", "description": "Ray metrics scraper"},
    "node_exporter": {"label": "Node Exporter", "description": "Host-level metrics (CPU, RAM, disk)"},
    "cadvisor": {"label": "cAdvisor", "description": "Container resource metrics"},
    "ml_slo_exporter": {"label": "ML SLO Exporter", "description": "ML service-level objective metrics"},
    "alertmanager_telegram": {"label": "Alertmanager Telegram", "description": "Telegram alert relay"},
    "feature_scheduler": {"label": "Feature Scheduler", "description": "Scheduled feature extraction jobs"},
    "nightly_test_runner": {"label": "Nightly Test Runner", "description": "Nightly test suite execution"},
    "webhook_deployer": {"label": "Webhook Deployer", "description": "Git webhook → auto-deploy"},
    "otel_collector": {"label": "OpenTelemetry Collector", "description": "Trace collection & export"},
    "promtail": {"label": "Promtail", "description": "Log shipping to Loki"},
    "dcgm_exporter": {"label": "DCGM Exporter", "description": "NVIDIA GPU metrics exporter"},
    "chat_ui": {"label": "Chat UI v2", "description": "React chat frontend"},
    "qwen3_vl_api": {"label": "Qwen3-VL API (GPU 1)", "description": "Vision/multimodal model, RTX 2070"},
    "z_image_api": {"label": "Z-Image API (GPU 0)", "description": "Image generation, RTX 3090"},
    "inference_gateway": {"label": "Inference Gateway", "description": "Queue, rate limit, chat history"},
    "pii_blur_api": {"label": "PII Blur API", "description": "PII detection & face blurring"},
    "pii_ui": {"label": "PII Blur UI", "description": "PII blur web interface"},
    "audio_copyright_api": {"label": "Audio Copyright API", "description": "Audio copyright detection"},
    "shl_nano": {"label": "SHL Nano", "description": "Lightweight inference service"},
}

# Services not in any compose file
EXTRA_SERVICES: list[tuple[str, str, str, str]] = [
    ("obsidian_vault", "Obsidian Vault (local)", "tooling", "docs/obsidian-vault/ — decisions, models, experiments"),
    ("obsidian_mcp", "MCP: obsidian-vault", "tooling", "Filesystem MCP server exposing vault to AI agents"),
    ("platform_mcp", "MCP: shml-platform", "tooling", "HTTP MCP server at /api/agent/mcp"),
    ("git_mcp", "MCP: git", "tooling", "npx @modelcontextprotocol/server-git"),
    ("skill_evolution", "skill_evolution.py (GEPA)", "inference", "Nightly skill evolution engine"),
    ("autoresearch", "autoresearch_face.py", "training", "YOLO autoresearch loop (Ray job)"),
    ("hermes_gepa", "libs/hermes-self-evolution", "tooling", "NousResearch GEPA datasets"),
    ("obsidian_watcher", "Obsidian Watcher", "tooling", "daemon thread; auto-ingests research/*.md"),
    ("hermes_gateway", "Hermes Gateway (systemd)", "inference", "AI gateway API on :8642 — systemd user service"),
    ("hermes_workspace", "Hermes Workspace (systemd)", "tooling", "Vite dev UI on :3000 — systemd user service"),
    # OpenClaw Gateway — not deployed yet; uncomment when deployed
    # ("openclaw_gateway", "OpenClaw Gateway (systemd)", "inference", "OpenClaw gateway — systemd user service"),
]

# Connections that can't be discovered from compose files
EXTRA_CONNECTIONS: list[tuple[str, str, str, str]] = [
    ("oauth2_proxy", "fusionauth", "OIDC/OAuth2 token verify", "connected"),
    ("oauth2_proxy", "role_auth", "role header injection", "connected"),
    ("agent_service", "platform_mcp", "self: /api/agent/mcp", "connected"),
    ("agent_service", "obsidian_mcp", "MCP filesystem server", "configured"),
    ("agent_service", "git_mcp", "MCP git server", "configured"),
    ("agent_service", "skill_evolution", "nightly GEPA job", "connected"),
    ("agent_service", "obsidian_watcher", "daemon thread in process", "connected"),
    ("agent_service", "docker_proxy", "sandbox container ops", "connected"),
    ("ray_head", "mlflow_server", "experiment logging", "connected"),
    ("ray_head", "pushgateway", "batch metrics", "connected"),
    ("autoresearch", "ray_head", "runs as Ray job", "connected"),
    ("autoresearch", "mlflow_server", "automlflow logging", "connected"),
    ("fiftyone", "agent_service", "eval trigger (T2.6)", "planned"),
    ("skill_evolution", "obsidian_vault", "writes skill ADRs", "planned"),
    ("autoresearch", "obsidian_vault", "writes experiment notes", "planned"),
    ("gitlab", "agent_service", "webhook triggers", "planned"),
    ("agent_service", "coding_model_fallback", "cloud failover (T5.1)", "disconnected"),
    ("obsidian_watcher", "obsidian_vault", "writes ingested notes", "connected"),
    ("obsidian_mcp", "obsidian_vault", "reads vault files", "connected"),
    ("hermes_gepa", "skill_evolution", "datasets + evolution/", "configured"),
    ("global_prometheus", "traefik", "scrapes /metrics", "connected"),
    ("global_prometheus", "agent_service", "scrapes /metrics", "connected"),
    ("global_prometheus", "ray_head", "scrapes ray metrics", "connected"),
    ("global_prometheus", "mlflow_server", "scrapes mlflow metrics", "connected"),
    ("global_prometheus", "cadvisor", "container metrics", "connected"),
    ("global_prometheus", "node_exporter", "host metrics", "connected"),
    ("pushgateway", "global_prometheus", "batch job sink", "connected"),
    ("alertmanager", "global_prometheus", "alert rules", "connected"),
    ("unified_grafana", "global_prometheus", "datasource", "connected"),
    ("unified_grafana", "loki", "log datasource", "configured"),
    ("unified_grafana", "tempo", "trace datasource", "configured"),
    ("gitlab_runner", "gitlab", "CI pipeline jobs", "connected"),
    ("hermes_gateway", "qwopus_coding", "LLM completions via vLLM", "connected"),
    ("hermes_gateway", "agent_service", "skill dispatch", "connected"),
    ("hermes_workspace", "hermes_gateway", "API calls", "connected"),
    ("watchdog", "hermes_gateway", "host probe :8642/health", "connected"),
    ("watchdog", "hermes_workspace", "host probe :3000/", "connected"),
]

# Override auto-discovered connection labels
CONNECTION_LABEL_OVERRIDES: dict[tuple[str, str], str] = {
    ("traefik", "agent_service"): "/api/agent/*",
    ("traefik", "chat_api"): "/chat/*",
    ("traefik", "unified_grafana"): "/grafana/*",
    ("traefik", "homer"): "/homer/*",
    ("traefik", "fiftyone"): "/fiftyone/*",
    ("traefik", "nessie"): "/nessie/*",
    ("traefik", "fusionauth"): "/auth/*",
    ("traefik", "watchdog_admin"): "/watchdog/*",
    ("traefik", "openshell_gateway"): "/nemoclaw/*",
}


# ═══════════════════════════════════════════════════════════════════════════
# MERGE
# ═══════════════════════════════════════════════════════════════════════════


def build_registry() -> tuple[list[tuple], list[tuple]]:
    """Merge auto-discovered data with manual supplements → (services, connections)."""
    discovered_svcs, discovered_conns = scan_compose_files()

    # Apply metadata overrides to discovered services
    services: list[tuple] = []
    for svc_id, label, layer, desc in discovered_svcs.values():
        meta = SERVICE_META.get(svc_id, {})
        services.append((
            svc_id,
            meta.get("label", label),
            meta.get("layer", layer),
            meta.get("description", desc),
        ))

    # Add non-Docker extra services
    existing_ids = {s[0] for s in services}
    for svc in EXTRA_SERVICES:
        if svc[0] not in existing_ids:
            services.append(svc)

    # Merge connections: auto-discovered + extras (dedup by src,dst)
    seen: set[tuple[str, str]] = set()
    connections: list[tuple] = []
    for src, dst, label, status in discovered_conns:
        label = CONNECTION_LABEL_OVERRIDES.get((src, dst), label)
        key = (src, dst)
        if key not in seen:
            connections.append((src, dst, label, status))
            seen.add(key)
    for src, dst, label, status in EXTRA_CONNECTIONS:
        key = (src, dst)
        if key not in seen:
            connections.append((src, dst, label, status))
            seen.add(key)

    return services, connections


# ═══════════════════════════════════════════════════════════════════════════
# RENDERING
# ═══════════════════════════════════════════════════════════════════════════


def generate_mermaid(services: list[tuple], connections: list[tuple]) -> str:
    svc_lookup = {s[0]: s for s in services}
    lines = ["```mermaid", "graph LR"]

    layers: dict[str, list] = {}
    for sid, label, layer, _ in services:
        layers.setdefault(layer, []).append((sid, label))

    layer_order = [
        "gateway", "auth", "inference", "training",
        "data", "storage", "monitoring", "tooling",
    ]
    for layer in layer_order:
        if layer not in layers:
            continue
        lines.append(f'\n    subgraph {layer.upper()}["{layer.upper()}"]')
        for sid, label in layers[layer]:
            escaped = label.replace('"', "'")
            lines.append(f'        {_safe_mermaid(sid)}["{escaped}"]')
        lines.append("    end")

    lines.append("")
    for sid, label, layer, _ in services:
        style = LAYER_COLOR.get(layer, "fill:#222,color:#ddd")
        lines.append(f"    style {_safe_mermaid(sid)} {style}")

    lines.append("")
    link_styles = []
    idx = 0
    for src, dst, label, status in connections:
        if src not in svc_lookup or dst not in svc_lookup:
            continue
        escaped_label = label.replace('"', "'")[:25]
        lines.append(
            f'    {_safe_mermaid(src)} -->|"{escaped_label}"| {_safe_mermaid(dst)}'
        )
        link_styles.append(f"    linkStyle {idx} {STATUS_MERMAID_STYLE[status]}")
        idx += 1

    lines.extend(link_styles)
    lines.append("```")
    return "\n".join(lines)


def generate_status_table(services: list[tuple], connections: list[tuple]) -> str:
    svc_lookup = {s[0]: s for s in services}
    rows = []
    for src, dst, label, status in connections:
        src_name = svc_lookup[src][1] if src in svc_lookup else src
        dst_name = svc_lookup[dst][1] if dst in svc_lookup else dst
        rows.append(
            f"| {STATUS_EMOJI[status]} {status.upper()} "
            f"| {src_name} → {dst_name} "
            f"| {label} |"
        )
    header = (
        "| Status | Connection | Description |\n"
        "|--------|------------|-------------|"
    )
    return header + "\n" + "\n".join(rows)


def generate_gap_analysis(connections: list[tuple], services: list[tuple]) -> str:
    svc_lookup = {s[0]: s for s in services}

    def name(sid: str) -> str:
        return svc_lookup[sid][1] if sid in svc_lookup else sid

    planned = [(s, d, l) for s, d, l, st in connections if st == "planned"]
    disconnected = [(s, d, l) for s, d, l, st in connections if st == "disconnected"]
    configured = [(s, d, l) for s, d, l, st in connections if st == "configured"]

    lines = ["## Gap Analysis\n"]

    if disconnected:
        lines.append("### 🔴 Disconnected (configured in code, not active)\n")
        for s, d, l in disconnected:
            lines.append(f"- **{name(s)} → {name(d)}**: {l}")
        lines.append("")

    if planned:
        lines.append("### ⚪ Planned (not yet implemented)\n")
        for s, d, l in planned:
            lines.append(f"- **{name(s)} → {name(d)}**: {l}")
        lines.append("")

    if configured:
        lines.append("### 🟡 Configured but unverified runtime state\n")
        for s, d, l in configured[:20]:
            lines.append(f"- **{name(s)} → {name(d)}**: {l}")
        if len(configured) > 20:
            lines.append(f"- ... and {len(configured) - 20} more")
        lines.append("")

    return "\n".join(lines)


def generate_service_inventory(services: list[tuple]) -> str:
    lines = ["## Service Inventory\n"]
    lines.append("| Layer | Service | Description |")
    lines.append("|-------|---------|-------------|")

    layer_order = [
        "gateway", "auth", "inference", "training",
        "data", "storage", "monitoring", "tooling",
    ]
    for layer in layer_order:
        for sid, label, slayer, desc in services:
            if slayer == layer:
                lines.append(f"| {layer} | **{label}** | {desc} |")
    return "\n".join(lines)


def generate_stats(services: list[tuple], connections: list[tuple]) -> str:
    counts: dict[str, int] = {}
    for _, _, _, status in connections:
        counts[status] = counts.get(status, 0) + 1
    total = sum(counts.values())
    return (
        f"- **Total connections mapped:** {total}\n"
        f"- {STATUS_EMOJI['connected']} Connected: {counts.get('connected', 0)}\n"
        f"- {STATUS_EMOJI['configured']} Configured (unverified): {counts.get('configured', 0)}\n"
        f"- {STATUS_EMOJI['disconnected']} Disconnected (needs key/fix): {counts.get('disconnected', 0)}\n"
        f"- {STATUS_EMOJI['planned']} Planned (not built): {counts.get('planned', 0)}\n"
        f"- **Total services inventoried:** {len(services)}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# DRIFT DETECTION
# ═══════════════════════════════════════════════════════════════════════════


def detect_drift(services: list[tuple]) -> list[str]:
    """Compare auto-discovered services vs running containers (docker ps)."""
    issues: list[str] = []
    known_ids = {s[0] for s in services}

    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return ["⚠️  Could not run 'docker ps' — drift check skipped"]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ["⚠️  Docker not available — drift check skipped"]

    running = set()
    for name in result.stdout.strip().splitlines():
        running.add(_make_id(name.strip()))

    # Services running but not in our registry
    unknown = running - known_ids
    if unknown:
        issues.append("### 🆕 Running containers not in connection map\n")
        for uid in sorted(unknown):
            issues.append(f"- `{uid}` — add to compose or EXTRA_SERVICES")
        issues.append("")

    # Services in registry but not running (only check compose-discovered ones)
    discovered_svcs, _ = scan_compose_files()
    expected = set(discovered_svcs.keys())
    missing = expected - running
    if missing:
        issues.append("### 🔻 Expected containers not running\n")
        for mid in sorted(missing):
            issues.append(f"- `{mid}` — expected from compose files")
        issues.append("")

    return issues


def generate_drift_section(services: list[tuple]) -> str:
    issues = detect_drift(services)
    lines = ["## Drift Report\n"]
    lines.append(
        "> Auto-detected by comparing docker-compose definitions vs `docker ps`.\n"
    )
    if issues:
        lines.extend(issues)
    else:
        lines.append("✅ No drift detected — all compose-defined services accounted for.\n")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════


def main() -> None:
    drift_only = "--drift" in sys.argv

    services, connections = build_registry()

    if drift_only:
        issues = detect_drift(services)
        # Only exit 1 for unknown running containers (real drift)
        # Expected-but-not-running is normal for optional/on-demand services
        has_unknown = any("not in connection map" in line for line in issues)
        if has_unknown:
            print("DRIFT DETECTED — unknown containers running:")
            for line in issues:
                if "not in connection map" in line or line.startswith("- "):
                    print(line)
            sys.exit(1)
        else:
            print("OK: All running containers are in the connection map")
            sys.exit(0)

    today = date.today().isoformat()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    compose_files = _find_compose_files()
    compose_list = "\n".join(
        f"  - `{f.relative_to(REPO_ROOT)}`" for f in compose_files
    )

    doc = dedent(f"""\
    ---
    title: "Platform Connection Map"
    updated: {today}
    tags: [architecture, lineage, connections, gap-analysis, auto-discovered]
    ---

    # Platform Connection Map

    > Auto-generated {today} by `scripts/generate_connection_map.py`
    > **Auto-discovery** scans {len(compose_files)} docker-compose files + Traefik labels + depends_on.
    > Manual supplements add non-Docker services and planned connections.
    > Re-run any time: `python scripts/generate_connection_map.py`

    ## Data Sources
    Compose files scanned:
    {compose_list}

    ## Legend
    | Symbol | Meaning |
    |--------|---------|
    | 🟢 CONNECTED | Verified working in current deployment |
    | 🟡 CONFIGURED | Wired in code; runtime not confirmed or conditional |
    | 🔴 DISCONNECTED | Explicitly disabled or missing required secret/key |
    | ⚪ PLANNED | Intended but not yet implemented |

    ## Summary Stats
    {generate_stats(services, connections)}

    ---

    ## Architecture Diagram

    > Tip: Install the **Mermaid** Obsidian plugin to render this inline.
    > Or open in GitHub — it renders natively.

    {generate_mermaid(services, connections)}

    ---

    {generate_service_inventory(services)}

    ---

    ## Connection Status

    {generate_status_table(services, connections)}

    ---

    {generate_gap_analysis(connections, services)}

    ---

    {generate_drift_section(services)}

    ---

    ## Backlinks
    - [[HOME]]
    - [[20-Decisions/INDEX]]
    """)

    OUT_PATH.write_text(doc, encoding="utf-8")
    print(f"✓ Connection map written to {OUT_PATH.relative_to(REPO_ROOT)}")
    print(f"  {len(services)} services, {len(connections)} connections mapped")
    print(f"  {len(compose_files)} compose files scanned")


if __name__ == "__main__":
    main()
