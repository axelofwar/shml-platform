-- Ray Compute Database Migration Script
-- Run this to migrate from UUID-based PKs to SERIAL-based PKs (SQLAlchemy compatibility)
-- Idempotent - safe to run multiple times

-- ============================================================================
-- Migration: audit_log table
-- ============================================================================
DO $$
BEGIN
    -- Check if audit_log needs migration (has UUID log_id)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'audit_log'
        AND column_name = 'log_id'
        AND data_type = 'uuid'
    ) THEN
        RAISE NOTICE 'Migrating audit_log table from UUID to SERIAL primary key...';

        -- Drop and recreate
        DROP TABLE IF EXISTS audit_log CASCADE;

        CREATE TABLE audit_log (
            log_id SERIAL PRIMARY KEY,
            user_id UUID REFERENCES users(user_id),
            action VARCHAR(100) NOT NULL,
            resource_type VARCHAR(50),
            resource_id VARCHAR(255),
            details TEXT,
            ip_address INET,
            user_agent TEXT,
            timestamp TIMESTAMPTZ DEFAULT NOW(),
            success BOOLEAN DEFAULT TRUE
        );

        CREATE INDEX IF NOT EXISTS idx_audit_log_user_timestamp ON audit_log(user_id, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);

        RAISE NOTICE 'audit_log migration complete';
    ELSE
        -- Check if success column exists
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'audit_log'
            AND column_name = 'success'
        ) THEN
            ALTER TABLE audit_log ADD COLUMN success BOOLEAN DEFAULT TRUE;
            RAISE NOTICE 'Added success column to audit_log';
        END IF;
        RAISE NOTICE 'audit_log already migrated or compatible';
    END IF;
END $$;

-- ============================================================================
-- Migration: artifact_versions table
-- ============================================================================
DO $$
BEGIN
    -- Check if artifact_versions needs migration
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'artifact_versions'
        AND column_name = 'version_id'
    ) THEN
        RAISE NOTICE 'Migrating artifact_versions table...';

        DROP TABLE IF EXISTS artifact_versions CASCADE;

        CREATE TABLE artifact_versions (
            artifact_id SERIAL PRIMARY KEY,
            job_id VARCHAR(255) NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            version INTEGER NOT NULL DEFAULT 1,
            artifact_path TEXT NOT NULL,
            size_bytes BIGINT NOT NULL,
            checksum VARCHAR(64),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            expires_at TIMESTAMPTZ,
            downloaded_count INTEGER DEFAULT 0,
            last_accessed TIMESTAMPTZ,
            is_deleted BOOLEAN DEFAULT FALSE
        );

        RAISE NOTICE 'artifact_versions migration complete';
    ELSE
        RAISE NOTICE 'artifact_versions already migrated or compatible';
    END IF;
END $$;

-- ============================================================================
-- Migration: resource_usage_daily table
-- ============================================================================
DO $$
BEGIN
    -- Check if resource_usage_daily needs migration
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'resource_usage_daily'
        AND column_name = 'usage_id'
        AND data_type = 'uuid'
    ) THEN
        RAISE NOTICE 'Migrating resource_usage_daily table...';

        DROP TABLE IF EXISTS resource_usage_daily CASCADE;

        CREATE TABLE resource_usage_daily (
            usage_id SERIAL PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(user_id),
            usage_date TIMESTAMPTZ NOT NULL,
            cpu_hours DECIMAL(10, 2) DEFAULT 0,
            gpu_hours DECIMAL(10, 2) DEFAULT 0,
            storage_gb DECIMAL(10, 2) DEFAULT 0,
            jobs_completed INTEGER DEFAULT 0,
            jobs_failed INTEGER DEFAULT 0
        );

        RAISE NOTICE 'resource_usage_daily migration complete';
    ELSE
        RAISE NOTICE 'resource_usage_daily already migrated or compatible';
    END IF;
END $$;

-- ============================================================================
-- Migration: system_alerts table
-- ============================================================================
DO $$
BEGIN
    -- Check if system_alerts needs migration
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'system_alerts'
        AND column_name = 'alert_id'
        AND data_type = 'uuid'
    ) THEN
        RAISE NOTICE 'Migrating system_alerts table...';

        DROP TABLE IF EXISTS system_alerts CASCADE;

        CREATE TABLE system_alerts (
            alert_id SERIAL PRIMARY KEY,
            severity VARCHAR(50) NOT NULL CHECK (severity IN ('info', 'warning', 'error', 'critical')),
            alert_type VARCHAR(100) NOT NULL,
            message TEXT NOT NULL,
            details TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            resolved_at TIMESTAMPTZ,
            resolved_by UUID REFERENCES users(user_id),
            is_acknowledged BOOLEAN DEFAULT FALSE,
            acknowledged_by UUID REFERENCES users(user_id),
            acknowledged_at TIMESTAMPTZ
        );

        RAISE NOTICE 'system_alerts migration complete';
    ELSE
        RAISE NOTICE 'system_alerts already migrated or compatible';
    END IF;
END $$;

-- ============================================================================
-- Migration: job_queue table (update columns to match model)
-- ============================================================================
DO $$
BEGIN
    -- Check if job_queue has old columns
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'job_queue'
        AND column_name = 'added_at'
    ) THEN
        RAISE NOTICE 'Migrating job_queue table...';

        DROP TABLE IF EXISTS job_queue CASCADE;

        CREATE TABLE job_queue (
            queue_id SERIAL PRIMARY KEY,
            job_id VARCHAR(255) NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(user_id),
            priority_score DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
            enqueued_at TIMESTAMPTZ DEFAULT NOW(),
            estimated_start_time TIMESTAMPTZ,
            position_in_queue INTEGER
        );

        RAISE NOTICE 'job_queue migration complete';
    ELSE
        RAISE NOTICE 'job_queue already migrated or compatible';
    END IF;
END $$;

-- ============================================================================
-- Seed Data: Ensure admin user exists with FusionAuth link
-- ============================================================================
DO $$
BEGIN
    -- Check if admin user exists
    IF NOT EXISTS (SELECT 1 FROM users WHERE email = 'admin@ml-platform.local') THEN
        INSERT INTO users (username, email, role, is_active)
        VALUES ('admin', 'admin@ml-platform.local', 'admin', true);
        RAISE NOTICE 'Created admin user';
    END IF;

    -- Ensure admin has quota
    IF NOT EXISTS (SELECT 1 FROM user_quotas uq
                   JOIN users u ON uq.user_id = u.user_id
                   WHERE u.email = 'admin@ml-platform.local') THEN
        INSERT INTO user_quotas (
            user_id,
            max_concurrent_jobs,
            max_gpu_hours_per_day,
            max_cpu_hours_per_day,
            max_storage_gb,
            max_artifact_size_gb,
            max_job_timeout_hours,
            priority_weight,
            can_use_custom_docker,
            can_skip_validation
        )
        SELECT
            user_id,
            100,    -- max_concurrent_jobs
            1000.0, -- max_gpu_hours_per_day
            10000.0, -- max_cpu_hours_per_day
            1000,   -- max_storage_gb
            100,    -- max_artifact_size_gb
            168,    -- max_job_timeout_hours (1 week)
            100,    -- priority_weight
            true,   -- can_use_custom_docker
            true    -- can_skip_validation
        FROM users WHERE email = 'admin@ml-platform.local';
        RAISE NOTICE 'Created admin quota';
    END IF;
END $$;

-- ============================================================================
-- Grant Permissions
-- ============================================================================
DO $$
BEGIN
    -- Grant permissions to ray_compute user on all tables and sequences
    EXECUTE 'GRANT ALL ON ALL TABLES IN SCHEMA public TO ray_compute';
    EXECUTE 'GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO ray_compute';
    RAISE NOTICE 'Permissions granted to ray_compute user';
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Could not grant permissions (user may not exist): %', SQLERRM;
END $$;

SELECT 'Migration complete!' AS status;
