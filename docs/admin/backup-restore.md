# Backup & Restore

The platform automates PostgreSQL backups and supports full platform snapshots.

---

## PostgreSQL Backup (Automated)

The `postgres-backup` container runs scheduled backups of all databases.

### Schedule

| Setting | Default | Description |
|---------|---------|-------------|
| `BACKUP_SCHEDULE` | `0 */6 * * *` | Every 6 hours (00:00, 06:00, 12:00, 18:00) |
| `BACKUP_KEEP_DAYS` | `7` | Daily backups retained |
| `BACKUP_KEEP_WEEKS` | `4` | Weekly backups retained |
| `BACKUP_KEEP_MONTHS` | `6` | Monthly backups retained |

### Databases Backed Up

- `mlflow_db` — Experiment tracking, model registry
- `ray_compute` — Job metadata, API keys, audit logs
- `inference` — Chat history, agent sessions
- `fusionauth` — Users, roles, applications
- `chat_api` — Chat conversation data

### Backup Location

```
backups/postgres/
├── daily/
│   ├── mlflow_db-2026-02-28T060000.sql.gz
│   ├── ray_compute-2026-02-28T060000.sql.gz
│   └── ...
├── weekly/
└── monthly/
```

### Manual Backup

```bash
# Trigger an immediate backup
docker exec postgres-backup /backup.sh

# Or directly with pg_dump
docker exec shml-postgres pg_dump -U postgres -Fc mlflow_db > mlflow_backup.dump
```

---

## Restoring PostgreSQL

### Single Database

```bash
# Stop the service that uses this database
./start_all_safe.sh stop mlflow

# Restore from backup
docker exec -i shml-postgres pg_restore -U postgres -d mlflow_db --clean \
  < backups/postgres/daily/mlflow_db-2026-02-28T060000.sql.gz

# Restart
./start_all_safe.sh start mlflow
```

### From pg_dump format

```bash
docker exec -i shml-postgres psql -U postgres -d mlflow_db < backup.sql
```

!!! warning "FusionAuth Restore"
    Restoring the `fusionauth` database may invalidate active sessions. All users will need to re-authenticate after a restore.

---

## Platform Snapshots

Full platform backups are stored in `backups/platform/`.

### Creating a Snapshot

```bash
# The startup script creates automatic backups
ls backups/platform/
# repo_backup_20251212_003542/
```

A snapshot includes:

- All Docker Compose files
- Configuration files (`config/`, `monitoring/`)
- Scripts (`scripts/`, `*.sh`)
- Documentation

!!! note
    Snapshots do **not** include Docker volumes, secrets, or `.env`. Back these up separately.

### Full Backup Procedure

```bash
# 1. Stop all services
./start_all_safe.sh stop

# 2. Backup secrets
cp -r secrets/ /safe/location/secrets-$(date +%Y%m%d)/

# 3. Backup .env
cp .env /safe/location/env-$(date +%Y%m%d)

# 4. Backup PostgreSQL volumes
docker run --rm -v shml-postgres-data:/data -v $(pwd)/backups:/backup \
  alpine tar czf /backup/postgres-volume-$(date +%Y%m%d).tar.gz -C /data .

# 5. Backup MLflow artifacts
tar czf backups/mlflow-artifacts-$(date +%Y%m%d).tar.gz /mlflow/artifacts/

# 6. Restart
./start_all_safe.sh
```

---

## Restore Procedure (Full)

```bash
# 1. Restore secrets
cp -r /safe/location/secrets-20260228/ secrets/

# 2. Restore .env
cp /safe/location/env-20260228 .env

# 3. Restore PostgreSQL volume
docker volume create shml-postgres-data
docker run --rm -v shml-postgres-data:/data -v $(pwd)/backups:/backup \
  alpine tar xzf /backup/postgres-volume-20260228.tar.gz -C /data

# 4. Restore MLflow artifacts
tar xzf backups/mlflow-artifacts-20260228.tar.gz -C /

# 5. Start platform
./start_all_safe.sh
```

---

## Backup Verification

```bash
# Check backup container health
docker inspect postgres-backup --format='{{.State.Health.Status}}'

# List recent backups
ls -la backups/postgres/daily/ | tail -5

# Verify backup integrity
docker exec shml-postgres pg_restore --list \
  /backups/daily/mlflow_db-latest.sql.gz | head -20
```
