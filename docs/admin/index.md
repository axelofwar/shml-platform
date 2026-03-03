# Administration

Guide for platform administrators — managing services, users, and infrastructure.

---

## What Admins Can Do

Admins have full access to every service and management tool on the platform:

| Capability | Tool | Access |
|-----------|------|--------|
| Start / stop services | `start_all_safe.sh` | SSH or Code Server |
| Create users & assign roles | FusionAuth Admin UI | `/auth/admin/` |
| View all dashboards | Grafana | `/grafana` |
| View raw metrics | Prometheus | `/prometheus` |
| View container logs | Dozzle | `/logs` |
| Edit code in browser | Code Server | `/ide` |
| Manage secrets | Infisical | `/secrets` |
| View Traefik routing | Traefik Dashboard | `:8090` |
| Database access | `psql` via `docker exec` | SSH |
| Manage API keys | Ray Compute API | `/api/ray/keys` |

---

## Key Admin Tools

### start_all_safe.sh

The primary service management script. See [Docker Compose Organization](../architecture/docker-compose.md) for details.

```bash
./start_all_safe.sh              # Full restart
./start_all_safe.sh status       # Health check all services
./start_all_safe.sh diagnose     # Verify auth middleware
./start_all_safe.sh fix-oauth    # Fix FusionAuth redirect URLs
```

### FusionAuth Admin

Access at `/auth/admin/` (or `localhost:9011/admin/`). Used to:

- Create and manage user accounts
- Assign roles to users (viewer, developer, admin)
- Configure OAuth applications
- View login audit logs

See [User Management](user-management.md) for detailed procedures.

### Grafana

Access at `/grafana`. Pre-provisioned dashboards include:

- **System Overview** — CPU, RAM, disk, network
- **Container Resources** — Per-container CPU/memory (cAdvisor)
- **Ray Cluster** — GPU utilization, tasks, actors, object store
- **MLflow Metrics** — Experiment counts, API latency
- **Training Cost** — GPU hours, cost per job, budget alerts

!!! info "Dashboard Source"
    Dashboards are provisioned from `monitoring/grafana/dashboards/` and are read-only in the UI. Edit the JSON files to make permanent changes.

---

## Admin Checklist

When setting up a fresh platform:

- [ ] Run `setup.sh` to generate secrets and `.env`
- [ ] Start services with `./start_all_safe.sh`
- [ ] Log into FusionAuth and complete initial setup
- [ ] Create OAuth2-Proxy application in FusionAuth
- [ ] Create user accounts and assign roles
- [ ] Verify all health checks pass (`./start_all_safe.sh status`)
- [ ] Confirm auth middleware is registered (`./start_all_safe.sh diagnose`)
- [ ] Review Grafana dashboards for baseline metrics

---

## Related Pages

- [User Management](user-management.md) — Creating users, assigning roles
- [Backup & Restore](backup-restore.md) — Database backups and recovery
- [Platform Operations](platform-operations.md) — Start/stop, health, logs
- [Secrets Management](secrets-management.md) — Secret files and rotation
