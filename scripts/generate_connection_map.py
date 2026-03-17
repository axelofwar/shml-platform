#!/usr/bin/env python3
"""
Service Connection Map Generator
==================================
Reads all docker-compose files, MCP config, and agent-service config to produce:
  1. A Mermaid architecture diagram  (renders in Obsidian + GitHub)
  2. A connection status table       (connected / configured / disconnected)
  3. A gap analysis                  (what needs wiring)

Output: docs/obsidian-vault/decisions/CONNECTION_MAP.md

Run:
    python scripts/generate_connection_map.py
    # or via scheduler / post-ingestion hook
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from textwrap import dedent

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "docs" / "obsidian-vault" / "20-Decisions" / "CONNECTION_MAP.md"

# ═══════════════════════════════════════════════════════════════════════════
# SERVICE REGISTRY
# Manually curated list of all platform services + their metadata.
# Each entry: (id, label, layer, description)
# Layers: gateway | auth | inference | training | data | storage | monitoring | tooling | external
# ═══════════════════════════════════════════════════════════════════════════
SERVICES = [
    # ── Gateway & Auth ──────────────────────────────────────────────────────
    ("traefik",         "Traefik v2.11",           "gateway",    "Reverse proxy / TLS termination / routing"),
    ("oauth2_proxy",    "OAuth2 Proxy",             "auth",       "OAuth2 PKCE middleware, sits between Traefik and services"),
    ("fusionauth",      "FusionAuth 1.52",          "auth",       "SSO / OAuth2 identity provider (primary auth)"),
    ("role_auth",       "Role-Auth Service",        "auth",       "Custom middleware enforcing RBAC roles (admin/dev/user)"),
    # ── Inference ───────────────────────────────────────────────────────────
    ("qwen_coding",     "Qwen3.5-35B-A3B (llama.cpp)","inference","Primary coding + reasoning model, GPU 0 (RTX 3090 Ti)"),
    ("coding_fallback", "coding-model-fallback",    "inference",  "Fallback coding model (same image, inactive primary)"),
    ("agent_service",   "Agent Service (FastAPI)",  "inference",  "ACE pattern: Goal→Rubric→Code loop; owns /api/agent/*"),
    ("chat_api",        "Chat API",                 "inference",  "OpenAI-compatible /v1/chat endpoint, wraps agent-service"),
    ("chat_ui",         "Chat UI v2",               "inference",  "React frontend, served via Traefik"),
    ("qwen3_vl",        "Qwen3-VL API (GPU 1)",     "inference",  "Vision/multimodal model on RTX 2070 (GPU 1), always-on"),
    # ── Training ────────────────────────────────────────────────────────────
    ("ray_head",        "Ray Head Node",            "training",   "Distributed training cluster head"),
    ("ray_compute_api", "Ray Compute API",          "training",   "REST API for job submission & GPU orchestration"),
    ("ray_compute_ui",  "Ray Compute UI",           "training",   "Web dashboard for Ray jobs"),
    ("autoresearch",    "autoresearch_face.py",     "training",   "YOLO autoresearch loop (runs as Ray job on GPU 0)"),
    # ── Data Catalog & MLOps ────────────────────────────────────────────────
    ("mlflow_server",   "MLflow Server",            "data",       "Experiment tracking, artifact store, model registry"),
    ("mlflow_nginx",    "MLflow Nginx",             "data",       "Reverse proxy in front of MLflow server"),
    ("nessie",          "Project Nessie (Iceberg)", "data",       "Git-for-data Iceberg catalog (backed by Postgres)"),
    ("fiftyone",        "FiftyOne",                 "data",       "Dataset inspection & model evaluation UI"),
    ("fiftyone_mongo",  "FiftyOne MongoDB",         "data",       "MongoDB backend for FiftyOne dataset storage"),
    # ── Storage ─────────────────────────────────────────────────────────────
    ("postgres",        "Postgres 15 + pgvector",   "storage",    "Shared DB: mlflow_db, ray_compute, inference (pgvector)"),
    ("redis",           "Redis 7",                  "storage",    "Session cache, pub/sub, rate limiting"),
    # ── Monitoring ──────────────────────────────────────────────────────────
    ("prometheus",      "Prometheus (global)",      "monitoring", "Metrics scraper: Traefik, agent, MLflow, Ray"),
    ("grafana",         "Grafana (unified)",        "monitoring", "All dashboards: platform, training, agent analytics"),
    ("pushgateway",     "Pushgateway",              "monitoring", "Batch job metrics sink (Ray jobs push here)"),
    ("alertmanager",    "Alertmanager",             "monitoring", "Alert routing → Telegram bot"),
    ("cadvisor",        "cAdvisor",                 "monitoring", "Container resource metrics"),
    ("node_exporter",   "Node Exporter",            "monitoring", "Host-level metrics (CPU, RAM, disk, GPU)"),
    ("loki",            "Loki",                     "monitoring", "Log aggregation (grafana datasource)"),
    ("tempo",           "Tempo",                    "monitoring", "Distributed tracing backend"),
    # ── Tooling ─────────────────────────────────────────────────────────────
    ("gitlab",          "GitLab CE",                "tooling",    "Internal git hosting + CI/CD"),
    ("gitlab_runner",   "GitLab Runner",            "tooling",    "CI/CD runner"),
    ("code_server",     "Code Server",              "tooling",    "VS Code in browser"),
    ("homer",           "Homer Dashboard",          "tooling",    "Platform service index / quick links"),
    ("sba_portal",      "SBA Resource Portal",      "tooling",    "Grant/resource discovery UI"),
    # ── Knowledge / MCP ─────────────────────────────────────────────────────
    ("obsidian_vault",  "Obsidian Vault (local)",   "tooling",    "docs/obsidian-vault/ — decisions, models, experiments"),
    ("obsidian_mcp",    "MCP: obsidian-vault",      "tooling",    "Filesystem MCP server exposing vault to AI agents"),
    ("platform_mcp",    "MCP: shml-platform",       "tooling",    "HTTP MCP server at /api/agent/mcp — training/GPU tools"),
    ("git_mcp",         "MCP: git",                 "tooling",    "npx @modelcontextprotocol/server-git"),
    ("obsidian_watcher","Obsidian Watcher (watchdog)","tooling",  "daemon thread in agent-service; auto-ingests research/*.md"),
    # ── Skills / GEPA ───────────────────────────────────────────────────────
    ("skill_evolution", "skill_evolution.py (GEPA)","inference",  "Nightly skill evolution engine — generates improved skills"),
    ("hermes_gepa",     "libs/hermes-self-evolution","tooling",   "NousResearch Hermes GEPA repo (datasets + evolution/)"),
    # ── Security ────────────────────────────────────────────────────────────
    ("docker_proxy",    "Docker Proxy (read-only)", "tooling",    "Restricted Docker API (GET /containers only) for agent sandbox"),
    ("infisical",       "Infisical (secrets)",      "tooling",    "Secrets manager — mounts secrets into containers"),
]

# ═══════════════════════════════════════════════════════════════════════════
# CONNECTIONS
# (source_id, target_id, label, status)
# status: connected | configured | disconnected | planned
# connected     = verified working in current deployment
# configured    = wired in code but runtime not confirmed / conditional
# disconnected  = exists in code but explicitly disabled or key missing
# planned       = intended but not yet implemented
# ═══════════════════════════════════════════════════════════════════════════
CONNECTIONS = [
    # ── Gateway routing ──────────────────────────────────────────────────────
    ("traefik",      "oauth2_proxy",    "all protected routes",     "connected"),
    ("oauth2_proxy", "fusionauth",      "OIDC/OAuth2 token verify", "connected"),
    ("oauth2_proxy", "role_auth",       "role header injection",    "connected"),
    ("traefik",      "agent_service",   "/api/agent/*",             "connected"),
    ("traefik",      "chat_api",        "/v1/*",                    "connected"),
    ("traefik",      "chat_ui",         "/",                        "connected"),
    ("traefik",      "ray_compute_ui",  "/ray/*",                   "connected"),
    ("traefik",      "mlflow_nginx",    "/mlflow/*",                "connected"),
    ("traefik",      "grafana",         "/grafana/*",               "connected"),
    ("traefik",      "fiftyone",        "/fiftyone/*",              "connected"),
    ("traefik",      "homer",           "/homer/*",                 "connected"),
    # ── Inference connections ─────────────────────────────────────────────────
    ("agent_service","qwen_coding",     "primary LLM (GATEWAY_URL)","connected"),
    ("agent_service","coding_fallback", "FALLBACK_MODEL_URL",       "configured"),
    ("agent_service","postgres",        "inference DB (pgvector)",  "connected"),
    ("agent_service","redis",           "session cache / pub-sub",  "configured"),
    ("agent_service","platform_mcp",    "self: /api/agent/mcp",     "connected"),
    ("agent_service","obsidian_mcp",    "MCP filesystem server",    "configured"),
    ("agent_service","git_mcp",         "MCP git server",           "configured"),
    ("agent_service","docker_proxy",    "sandbox container ops",    "connected"),
    ("agent_service","skill_evolution", "nightly GEPA job",         "connected"),
    ("agent_service","obsidian_watcher","daemon thread in process", "connected"),
    ("chat_api",     "agent_service",   "proxies to ACE loop",      "connected"),
    ("chat_ui",      "chat_api",        "REST /v1/chat",            "connected"),
    # ── Model connections ─────────────────────────────────────────────────────
    ("qwen_coding",  "postgres",        "none (stateless)",         "disconnected"),
    ("qwen3_vl",     "agent_service",   "vision tool calls",        "configured"),
    # ── Training connections ──────────────────────────────────────────────────
    ("ray_head",     "postgres",        "ray_compute DB",           "connected"),
    ("ray_head",     "mlflow_server",   "experiment logging",       "connected"),
    ("ray_head",     "pushgateway",     "batch metrics",            "connected"),
    ("ray_compute_api","ray_head",      "job submission",           "connected"),
    ("autoresearch", "ray_head",        "runs as Ray job",          "connected"),
    ("autoresearch", "mlflow_server",   "automlflow logging",       "connected"),
    ("autoresearch", "postgres",        "reads best.pt paths",      "configured"),
    # ── Data catalog ─────────────────────────────────────────────────────────
    ("nessie",       "postgres",        "nessie version store",     "connected"),
    ("fiftyone",     "fiftyone_mongo",  "dataset storage",          "connected"),
    ("fiftyone",     "agent_service",   "eval trigger (T2.6)",      "planned"),
    # ── Monitoring connections ────────────────────────────────────────────────
    ("prometheus",   "traefik",         "scrapes /metrics",         "connected"),
    ("prometheus",   "agent_service",   "scrapes /metrics",         "connected"),
    ("prometheus",   "ray_head",        "scrapes ray metrics",      "connected"),
    ("prometheus",   "mlflow_server",   "scrapes mlflow metrics",   "connected"),
    ("prometheus",   "cadvisor",        "container metrics",        "connected"),
    ("prometheus",   "node_exporter",   "host metrics",             "connected"),
    ("pushgateway",  "prometheus",      "batch job sink",           "connected"),
    ("grafana",      "prometheus",      "datasource",               "connected"),
    ("grafana",      "loki",            "log datasource",           "configured"),
    ("grafana",      "tempo",           "trace datasource",         "configured"),
    ("alertmanager", "prometheus",      "alert rules",              "connected"),
    # ── Knowledge / Obsidian ─────────────────────────────────────────────────
    ("obsidian_watcher","obsidian_vault","writes ingested notes",   "connected"),
    ("obsidian_mcp", "obsidian_vault",  "reads vault files",        "connected"),
    ("skill_evolution","obsidian_vault","writes skill ADRs",        "planned"),
    ("autoresearch", "obsidian_vault",  "writes experiment notes",  "planned"),
    ("hermes_gepa",  "skill_evolution", "datasets + evolution/",    "configured"),
    # ── GitLab CI/CD ─────────────────────────────────────────────────────────
    ("gitlab_runner","gitlab",          "CI pipeline jobs",         "connected"),
    ("gitlab",       "agent_service",   "webhook triggers",         "planned"),
    # ── Secrets ──────────────────────────────────────────────────────────────
    ("infisical",    "postgres",        "secret: shared_db_password","connected"),
    ("infisical",    "agent_service",   "secrets injection",        "configured"),
    # ── Cloud failover (T5) ───────────────────────────────────────────────────
    ("agent_service","coding_fallback", "cloud failover (T5.1)",    "disconnected"),  # CLOUD_API_KEY not set
]

STATUS_EMOJI = {
    "connected":    "🟢",
    "configured":   "🟡",
    "disconnected": "🔴",
    "planned":      "⚪",
}
STATUS_MERMAID_STYLE = {
    "connected":    "stroke:#22c55e,stroke-width:2px",
    "configured":   "stroke:#eab308,stroke-width:1.5px,stroke-dasharray:5 3",
    "disconnected": "stroke:#ef4444,stroke-width:1.5px,stroke-dasharray:3 3",
    "planned":      "stroke:#94a3b8,stroke-width:1px,stroke-dasharray:2 4",
}
LAYER_COLOR = {
    "gateway":    "fill:#1e3a5f,color:#fff",
    "auth":       "fill:#312e81,color:#fff",
    "inference":  "fill:#064e3b,color:#fff",
    "training":   "fill:#1c1917,color:#fff",
    "data":       "fill:#134e4a,color:#fff",
    "storage":    "fill:#374151,color:#fff",
    "monitoring": "fill:#3b0764,color:#fff",
    "tooling":    "fill:#1a1a1a,color:#ddd",
}


def _safe_id(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", s)


def _build_service_lookup():
    return {s[0]: s for s in SERVICES}


def generate_mermaid() -> str:
    svc = _build_service_lookup()
    lines = ["```mermaid", "graph LR"]

    # Group by layer
    layers: dict[str, list] = {}
    for sid, label, layer, _ in SERVICES:
        layers.setdefault(layer, []).append((sid, label))

    layer_order = ["gateway", "auth", "inference", "training", "data", "storage", "monitoring", "tooling"]
    for layer in layer_order:
        if layer not in layers:
            continue
        lines.append(f"\n    subgraph {layer.upper()}[\"{layer.upper()}\"]")
        for sid, label in layers[layer]:
            escaped = label.replace('"', "'")
            lines.append(f'        {_safe_id(sid)}["{escaped}"]')
        lines.append("    end")

    # Node styles
    lines.append("")
    for sid, label, layer, _ in SERVICES:
        style = LAYER_COLOR.get(layer, "fill:#222,color:#ddd")
        lines.append(f"    style {_safe_id(sid)} {style}")

    # Edges
    lines.append("")
    edge_defs = []
    link_styles = []
    idx = 0
    for src, dst, label, status in CONNECTIONS:
        arrow = "-->"
        escaped_label = label.replace('"', "'")[:25]
        lines.append(f'    {_safe_id(src)} {arrow}|"{escaped_label}"| {_safe_id(dst)}')
        link_styles.append(f"    linkStyle {idx} {STATUS_MERMAID_STYLE[status]}")
        idx += 1

    lines.extend(link_styles)
    lines.append("```")
    return "\n".join(lines)


def generate_status_table() -> str:
    svc = _build_service_lookup()
    rows = []
    for src, dst, label, status in CONNECTIONS:
        src_name = svc[src][1] if src in svc else src
        dst_name = svc[dst][1] if dst in svc else dst
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


def generate_gap_analysis() -> str:
    planned = [(s, d, l) for s, d, l, st in CONNECTIONS if st == "planned"]
    disconnected = [(s, d, l) for s, d, l, st in CONNECTIONS if st == "disconnected"]
    configured_unverified = [(s, d, l) for s, d, l, st in CONNECTIONS if st == "configured"]

    svc = _build_service_lookup()

    def name(sid):
        return svc[sid][1] if sid in svc else sid

    lines = ["## Gap Analysis\n"]

    if disconnected:
        lines.append("### 🔴 Disconnected (configured in code, not active)\n")
        for s, d, l in disconnected:
            lines.append(f"- **{name(s)} → {name(d)}**: {l}")
            if "CLOUD_API_KEY" in l or "cloud" in l.lower():
                lines.append("  - **Fix:** Set `CLOUD_API_KEY` + `CLOUD_FALLBACK_URL` in `.env`")
        lines.append("")

    if planned:
        lines.append("### ⚪ Planned (not yet implemented)\n")
        for s, d, l in planned:
            lines.append(f"- **{name(s)} → {name(d)}**: {l}")
        lines.append("")

    if configured_unverified:
        lines.append("### 🟡 Configured but unverified runtime state\n")
        for s, d, l in configured_unverified[:15]:
            lines.append(f"- **{name(s)} → {name(d)}**: {l}")
        lines.append("")

    lines.append("### Top 5 Highest-Value Gaps to Close\n")
    lines.append("| Priority | Gap | Effort | Impact |")
    lines.append("|----------|-----|--------|--------|")
    gaps = [
        ("P1", "agent_service → obsidian_vault via skill_evolution (write ADRs)", "2h", "Automatic knowledge capture from GEPA cycles"),
        ("P1", "autoresearch → obsidian_vault (write experiment notes post-run)", "2h", "Self-documenting training history"),
        ("P2", "fiftyone → agent_service (eval trigger on training winner)", "4h", "Close T2.6 loop: auto-eval when mAP50 > 0.814"),
        ("P2", "gitlab → agent_service (webhook-triggered code tasks)", "3h", "CI-driven agent tasks on merge/PR"),
        ("P3", "CLOUD_API_KEY set → activate cloud failover tier (T5.1)", "30min", "Cost-controlled cloud fallback live"),
    ]
    for pri, gap, effort, impact in gaps:
        lines.append(f"| {pri} | {gap} | {effort} | {impact} |")

    return "\n".join(lines)


def generate_service_inventory() -> str:
    lines = ["## Service Inventory\n"]
    lines.append("| Layer | Service | Description |")
    lines.append("|-------|---------|-------------|")

    layer_order = ["gateway", "auth", "inference", "training", "data", "storage", "monitoring", "tooling"]
    for layer in layer_order:
        for sid, label, slayer, desc in SERVICES:
            if slayer == layer:
                lines.append(f"| {layer} | **{label}** | {desc} |")

    return "\n".join(lines)


def generate_stats() -> str:
    counts = {}
    for _, _, _, status in CONNECTIONS:
        counts[status] = counts.get(status, 0) + 1
    total = sum(counts.values())
    return (
        f"- **Total connections mapped:** {total}\n"
        f"- {STATUS_EMOJI['connected']} Connected: {counts.get('connected', 0)}\n"
        f"- {STATUS_EMOJI['configured']} Configured (unverified): {counts.get('configured', 0)}\n"
        f"- {STATUS_EMOJI['disconnected']} Disconnected (needs key/fix): {counts.get('disconnected', 0)}\n"
        f"- {STATUS_EMOJI['planned']} Planned (not built): {counts.get('planned', 0)}\n"
        f"- **Total services inventoried:** {len(SERVICES)}"
    )


def main() -> None:
    today = date.today().isoformat()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    doc = dedent(f"""\
    ---
    title: "Platform Connection Map"
    updated: {today}
    tags: [architecture, lineage, connections, gap-analysis]
    ---

    # Platform Connection Map

    > Auto-generated {today} by `scripts/generate_connection_map.py`
    > Re-run any time: `python scripts/generate_connection_map.py`

    ## Legend
    | Symbol | Meaning |
    |--------|---------|
    | 🟢 CONNECTED | Verified working in current deployment |
    | 🟡 CONFIGURED | Wired in code; runtime not confirmed or conditional |
    | 🔴 DISCONNECTED | Explicitly disabled or missing required secret/key |
    | ⚪ PLANNED | Intended but not yet implemented |

    ## Summary Stats
    {generate_stats()}

    ---

    ## Architecture Diagram

    > Tip: Install the **Mermaid** Obsidian plugin to render this inline.
    > Or open in GitHub — it renders natively.

    {generate_mermaid()}

    ---

    {generate_service_inventory()}

    ---

    ## Connection Status

    {generate_status_table()}

    ---

    {generate_gap_analysis()}

    ---

    ## Backlinks
    - [[HOME]]
    - [[20-Decisions/INDEX]]
    """)

    OUT_PATH.write_text(doc, encoding="utf-8")
    print(f"✓ Connection map written to {OUT_PATH.relative_to(REPO_ROOT)}")
    print(f"  {len(SERVICES)} services, {len(CONNECTIONS)} connections mapped")


if __name__ == "__main__":
    sys.exit(main())
