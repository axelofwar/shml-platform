# Database Migrations Guide

## Overview

This guide explains the database migration system for the ML Platform. All three databases (MLflow, Ray Compute, Authentik) use persistent Docker volumes and have proper initialization and backup systems.

## Architecture

### PostgreSQL Instances

1. **MLflow Database** (`mlflow-postgres`)
   - Database: `mlflow_db`
   - User: `mlflow`
   - Volume: `mlflow-postgres-data`
   - Backup Dir: `./mlflow-server/backups/postgres`

2. **Ray Compute Database** (`ray-compute-db`)
   - Database: `ray_compute`
   - User: `ray_compute`
   - Volume: `ray-postgres-data`
   - Init Scripts: `./ray_compute/schemas` (mounted to `/docker-entrypoint-initdb.d`)
   - Backup Dir: `./ray_compute/backups/postgres`

3. **Authentik Database** (`authentik-postgres`)
   - Database: `authentik`
   - User: `authentik`
   - Volume: `authentik-postgres-data`
   - Backup Dir: `./authentik/backups/postgres`

### Auto-Initialization

PostgreSQL containers automatically execute scripts in `/docker-entrypoint-initdb.d` **only on first startup** when the data directory is empty. This means:

- ✅ First startup: All `.sql` scripts run automatically in alphabetical order
- ✅ Subsequent startups: Scripts are ignored (database already initialized)
- ✅ Volume persistence: Data survives container restarts
- ✅ Schema versioning: `schema_migrations` table tracks applied migrations

## Migration Workflow

### Directory Structure

```
ray_compute/
├── schemas/
│   ├── 001_initial_schema.sql      # Initial database schema
│   ├── 002_add_field.sql            # Example: Add new field
│   ├── 003_create_index.sql         # Example: Performance improvement
│   └── README.md                    # Migration documentation
└── backups/
    └── postgres/
        ├── ray_compute_20231123_120000.sql.gz
        └── ray_compute_20231123_140000.sql.gz
```

### Creating a New Migration

1. **Create Migration File**
   ```bash
   cd /home/axelofwar/Desktop/Projects/ml-platform/ray_compute/schemas
   nano 002_add_priority_boost.sql
   ```

2. **Migration File Template**
   ```sql
   -- Migration: 002_add_priority_boost.sql
   -- Description: Add priority boost field to users
   -- Author: Your Name
   -- Date: 2023-11-23
   
   -- Check if migration already applied
   DO $$
   BEGIN
       IF EXISTS (
           SELECT 1 FROM schema_migrations 
           WHERE migration_name = '002_add_priority_boost.sql'
       ) THEN
           RAISE NOTICE 'Migration already applied, skipping';
           RETURN;
       END IF;
   
       -- Your migration code here
       ALTER TABLE users ADD COLUMN priority_boost INTEGER DEFAULT 0;
       CREATE INDEX idx_users_priority_boost ON users(priority_boost);
   
       -- Record migration
       INSERT INTO schema_migrations (migration_name, success) 
       VALUES ('002_add_priority_boost.sql', TRUE);
       
       RAISE NOTICE 'Migration 002_add_priority_boost.sql applied successfully';
   END $$;
   ```

3. **Apply Migration**

   **Option A: On Fresh Install (auto-initialization)**
   - Stop all services: `./stop_all.sh`
   - Remove volume: `docker volume rm ml-platform_ray-postgres-data`
   - Start services: `./start_all.sh`
   - All migrations run automatically in order

   **Option B: On Existing Database (manual)**
   ```bash
   # Copy migration to container
   docker cp ray_compute/schemas/002_add_priority_boost.sql ray-compute-db:/tmp/
   
   # Execute migration
   docker exec -i ray-compute-db psql -U ray_compute -d ray_compute < /tmp/002_add_priority_boost.sql
   
   # Verify
   docker exec -it ray-compute-db psql -U ray_compute -d ray_compute -c "SELECT * FROM schema_migrations;"
   ```

### Testing Migrations

1. **Create Test Migration**
   ```sql
   -- test_migration.sql
   SELECT 'Testing migration system' AS status;
   
   -- Check current migrations
   SELECT migration_name, applied_at, success 
   FROM schema_migrations 
   ORDER BY applied_at DESC;
   ```

2. **Test on Development**
   ```bash
   docker exec -i ray-compute-db psql -U ray_compute -d ray_compute < test_migration.sql
   ```

## Backup and Restore

### Automated Backups

**Create Backup**
```bash
cd /home/axelofwar/Desktop/Projects/ml-platform
./scripts/backup_databases.sh
```

This creates timestamped backups:
- Compresses with gzip
- Keeps last 10 backups automatically
- Backs up all three databases

**Backup Output**
```
mlflow-server/backups/postgres/mlflow_db_20231123_120000.sql.gz
ray_compute/backups/postgres/ray_compute_20231123_120000.sql.gz
authentik/backups/postgres/authentik_20231123_120000.sql.gz
```

### Restore from Backup

**Interactive Restore**
```bash
./scripts/restore_databases.sh
```

Follow the prompts:
1. Select database (1-3)
2. Choose backup from list
3. Confirm restore (type `yes`)

**Manual Restore**
```bash
# Decompress backup
gunzip -c ray_compute/backups/postgres/ray_compute_20231123_120000.sql.gz > /tmp/restore.sql

# Drop and recreate database
docker exec -it ray-compute-db psql -U ray_compute -d postgres -c "DROP DATABASE ray_compute;"
docker exec -it ray-compute-db psql -U ray_compute -d postgres -c "CREATE DATABASE ray_compute;"

# Restore
docker exec -i ray-compute-db psql -U ray_compute -d ray_compute < /tmp/restore.sql
```

## Database Schema

### Ray Compute Tables

1. **users** - User accounts and OAuth integration
2. **user_quotas** - Resource limits per user
3. **jobs** - Job tracking with full metadata
4. **job_queue** - Job scheduling queue
5. **artifact_versions** - Artifact versioning
6. **resource_usage_daily** - Daily usage aggregation
7. **audit_log** - Security audit trail
8. **system_alerts** - System notifications
9. **schema_migrations** - Migration tracking

### Key Features

- **UUID Primary Keys**: All users and references use UUIDs
- **Timestamps**: Created/updated timestamps on all tables
- **Soft Deletes**: Artifacts use `is_deleted` flag
- **Foreign Keys**: Proper relationships with CASCADE
- **Indexes**: Performance indexes on common queries
- **Triggers**: Auto-update `updated_at` timestamps

## Verification and Troubleshooting

### Check Database Status

```bash
# Check if database is initialized
docker exec -it ray-compute-db psql -U ray_compute -d ray_compute -c "\dt"

# Check migrations
docker exec -it ray-compute-db psql -U ray_compute -d ray_compute -c "SELECT * FROM schema_migrations;"

# Check row counts
docker exec -it ray-compute-db psql -U ray_compute -d ray_compute -c "
    SELECT 
        'users' as table_name, COUNT(*) as rows FROM users
    UNION ALL
    SELECT 'jobs', COUNT(*) FROM jobs
    UNION ALL
    SELECT 'user_quotas', COUNT(*) FROM user_quotas;
"
```

### Verify Volume Persistence

```bash
# Stop services
./stop_all.sh

# Check volume exists
docker volume ls | grep ray-postgres-data

# Restart services
./start_all.sh

# Verify data persists
docker exec -it ray-compute-db psql -U ray_compute -d ray_compute -c "SELECT COUNT(*) FROM users;"
```

### Reset Database (Development Only)

```bash
# Stop all services
./stop_all.sh

# Remove volume
docker volume rm ml-platform_ray-postgres-data

# Start services (auto-initializes)
./start_all.sh

# Verify initialization
docker exec -it ray-compute-db psql -U ray_compute -d ray_compute -c "
    SELECT migration_name, applied_at 
    FROM schema_migrations 
    ORDER BY applied_at;
"
```

### Common Issues

**Issue**: "relation does not exist"
```bash
# Solution: Database not initialized
docker volume rm ml-platform_ray-postgres-data
./start_all.sh
```

**Issue**: "column does not exist"
```bash
# Solution: Missing migration
# Apply the migration manually or reset database
```

**Issue**: "permission denied"
```bash
# Solution: Check file permissions
chmod -R 755 ray_compute/schemas
```

**Issue**: "database already exists"
```bash
# Solution: Volume already initialized
# Migrations only run on first startup
# Use manual migration for existing databases
```

## Production Recommendations

### Daily Automated Backups

Create cron job:
```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * /home/axelofwar/Desktop/Projects/ml-platform/scripts/backup_databases.sh >> /var/log/ml-platform-backup.log 2>&1
```

### Pre-Deployment Checklist

1. ✅ Create backup before deployment
2. ✅ Test migration on development copy
3. ✅ Review migration SQL for issues
4. ✅ Plan rollback strategy
5. ✅ Schedule maintenance window
6. ✅ Notify users of downtime
7. ✅ Monitor post-deployment

### Rollback Procedure

```bash
# If migration fails
./scripts/restore_databases.sh
# Select most recent backup before migration

# Restart services
./restart_all.sh

# Verify
docker exec -it ray-compute-db psql -U ray_compute -d ray_compute -c "\dt"
```

## Migration Examples

### Add New Column

```sql
-- 002_add_cost_field.sql
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name='jobs' AND column_name='estimated_cost'
    ) THEN
        ALTER TABLE jobs ADD COLUMN estimated_cost NUMERIC(10, 2);
        CREATE INDEX idx_jobs_estimated_cost ON jobs(estimated_cost);
        
        INSERT INTO schema_migrations (migration_name, success) 
        VALUES ('002_add_cost_field.sql', TRUE);
    END IF;
END $$;
```

### Create New Table

```sql
-- 003_add_teams.sql
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_migrations WHERE migration_name = '003_add_teams.sql') THEN
        CREATE TABLE teams (
            team_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255) UNIQUE NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        
        ALTER TABLE users ADD COLUMN team_id UUID REFERENCES teams(team_id);
        
        INSERT INTO schema_migrations (migration_name, success) 
        VALUES ('003_add_teams.sql', TRUE);
    END IF;
END $$;
```

### Add Index for Performance

```sql
-- 004_add_performance_indexes.sql
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_migrations WHERE migration_name = '004_add_performance_indexes.sql') THEN
        CREATE INDEX IF NOT EXISTS idx_jobs_user_status ON jobs(user_id, status);
        CREATE INDEX IF NOT EXISTS idx_jobs_created_status ON jobs(created_at DESC, status);
        
        INSERT INTO schema_migrations (migration_name, success) 
        VALUES ('004_add_performance_indexes.sql', TRUE);
    END IF;
END $$;
```

## Summary

- ✅ **Automatic initialization** on first container startup
- ✅ **Persistent storage** through Docker volumes
- ✅ **Version tracking** with `schema_migrations` table
- ✅ **Backup/restore** scripts included
- ✅ **Safe migrations** with idempotent checks
- ✅ **Easy rollback** with timestamped backups

For questions or issues, check the logs:
```bash
docker logs ray-compute-db
docker logs mlflow-postgres
docker logs authentik-postgres
```
