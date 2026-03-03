# SHML Platform — Agent Runtime Context

## Critical Agent Rules
1. **Always use exec tool** — never describe steps; execute them directly.
2. **Check status before modifying** — run `docker ps` before restarting containers.
3. **Preserve OAuth** — every Traefik-exposed route needs `oauth2-errors,oauth2-auth` middleware.
4. **No secrets in output** — never print API keys, tokens, or .env contents.
5. **Absolute paths** — always use `/home/axelofwar/Projects/shml-platform/` for platform files.

## OpenClaw Governance

- Policy file: `/home/axelofwar/Projects/shml-platform/.openclaw/governance.policy.yaml`
- Operator controls: `/home/axelofwar/Projects/shml-platform/scripts/openclaw/openclaw_governor.sh`
- Skill: `/home/axelofwar/Projects/shml-platform/skills/openclaw-governor/SKILL.md`

### Control Objectives
- Route low-complexity work to local-first model tier.
- Escalate to hosted tiers only when complexity/failure thresholds are met.
- Require reasoned overrides and keep audit logs for every override/cancel action.
- Capture outcomes into `.openclaw/workspace-state.json` and weekly context compaction.

## Architecture

### Hardware
- **RTX 3090 Ti** (GPU 0, 24GB): Nemotron-3-Nano-30B coding model
- **RTX 2070** (GPU 1, 8GB): Available for inference
- **CPU**: Ryzen 9 3900X (12C/24T)
- **OS**: Ubuntu 24.04.4 LTS

### Network
- Tailscale: `shml-platform.tail38b60a.ts.net` (100.66.26.115)
- Tailscale Funnel enabled for HTTPS
- Traefik reverse proxy on ports 80/443 with Let's Encrypt

### Docker Compose Stacks
| File | Services |
|------|----------|
| `docker-compose.yml` | Core: Traefik, MLflow, Ray, Chat-UI, Nemotron, OAuth2-Proxy, FusionAuth |
| `docker-compose.infra.yml` | Monitoring: Prometheus, Grafana, Pushgateway |
| `docker-compose.dev.yml` | Dev: Code-Server, agents |
| `docker-compose.logging.yml` | Logging: Loki, Promtail |
| `docker-compose.tracing.yml` | Tracing: Tempo, OTLP Collector |

### Key Service Ports
| Service | Port | Route |
|---------|------|-------|
| Nemotron Coding | 8010 | /api/coding |
| Nemotron Manager | 8011 | /api/coding-manager |
| Embedding | 8012 | /api/embed |
| MLflow | 5555 | /mlflow |
| Grafana | 3000 | /grafana |
| Prometheus | 9090 | /prometheus |
| Ray | 8265 | /ray |
| Chat-UI | 3001 | /chat |
| Code-Server | 8443 | /code |

### Quick Commands
```bash
# Health check
docker ps --filter "health=unhealthy" --format "{{.Names}}: {{.Status}}"

# GPU status
nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader

# Service count
echo "Running: $(docker ps -q | wc -l) | Healthy: $(docker ps --filter health=healthy -q | wc -l)"

# Full platform check
cd /home/axelofwar/Projects/shml-platform && bash check_platform_status.sh

# Restart a service
cd /home/axelofwar/Projects/shml-platform && docker compose restart <service>
```

## Enhancement Priorities
See `/home/axelofwar/Projects/openclaw/research/STRATEGIC_PLAN.md` for full plan.
1. Resource manager service improvements
2. Monitoring dashboard enhancements
3. Chat-UI v2 / agent orchestration
4. PII compliance pipeline (pii-pro)
5. Automated testing and CI/CD
