-- Audit Schema Migration
-- Creates the audit schema and api_audit_log table with monthly partitioning

-- Create audit schema
CREATE SCHEMA IF NOT EXISTS audit;

-- Grant usage to ray_compute user
GRANT USAGE ON SCHEMA audit TO ray_compute;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA audit TO ray_compute;
ALTER DEFAULT PRIVILEGES IN SCHEMA audit GRANT ALL ON TABLES TO ray_compute;

-- Create the audit log table (parent table for partitioning)
-- Note: Primary key must include partition column (timestamp)
CREATE TABLE IF NOT EXISTS audit.api_audit_log (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Action details
    action VARCHAR(100) NOT NULL,

    -- User tracking (who made the request vs who the action is "as")
    actual_user_id UUID,
    actual_user_email VARCHAR(255),
    effective_user_id UUID,
    effective_user_email VARCHAR(255),

    -- Authentication method
    auth_method VARCHAR(50) NOT NULL,
    api_key_id UUID,

    -- Resource affected
    resource_type VARCHAR(50),
    resource_id VARCHAR(255),

    -- Request metadata
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    request_path VARCHAR(500),
    request_method VARCHAR(10),

    -- Additional context
    details JSONB,

    -- Outcome
    success VARCHAR(10) NOT NULL DEFAULT 'true',
    error_message TEXT,

    -- Composite primary key including partition column
    PRIMARY KEY (id, timestamp)
) PARTITION BY RANGE (timestamp);

-- Create indexes on parent table (inherited by partitions)
CREATE INDEX IF NOT EXISTS ix_audit_timestamp ON audit.api_audit_log (timestamp);
CREATE INDEX IF NOT EXISTS ix_audit_actual_user ON audit.api_audit_log (actual_user_id);
CREATE INDEX IF NOT EXISTS ix_audit_effective_user ON audit.api_audit_log (effective_user_id);
CREATE INDEX IF NOT EXISTS ix_audit_action ON audit.api_audit_log (action);
CREATE INDEX IF NOT EXISTS ix_audit_resource ON audit.api_audit_log (resource_type, resource_id);
CREATE INDEX IF NOT EXISTS ix_audit_api_key ON audit.api_audit_log (api_key_id) WHERE api_key_id IS NOT NULL;

-- Create initial partitions (current month + next 3 months)
DO $$
DECLARE
    start_date DATE;
    end_date DATE;
    partition_name TEXT;
    i INT;
BEGIN
    FOR i IN 0..3 LOOP
        start_date := DATE_TRUNC('month', CURRENT_DATE + (i || ' months')::INTERVAL);
        end_date := DATE_TRUNC('month', CURRENT_DATE + ((i + 1) || ' months')::INTERVAL);
        partition_name := 'api_audit_log_' || TO_CHAR(start_date, 'YYYY_MM');

        -- Check if partition exists
        IF NOT EXISTS (
            SELECT 1 FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'audit' AND c.relname = partition_name
        ) THEN
            EXECUTE format(
                'CREATE TABLE audit.%I PARTITION OF audit.api_audit_log
                FOR VALUES FROM (%L) TO (%L)',
                partition_name, start_date, end_date
            );
            RAISE NOTICE 'Created partition: audit.%', partition_name;
        END IF;
    END LOOP;
END $$;

-- Function to create new partitions automatically (run monthly via cron or pg_cron)
CREATE OR REPLACE FUNCTION audit.create_monthly_partition()
RETURNS void AS $$
DECLARE
    start_date DATE;
    end_date DATE;
    partition_name TEXT;
BEGIN
    -- Create partition for next month
    start_date := DATE_TRUNC('month', CURRENT_DATE + INTERVAL '1 month');
    end_date := DATE_TRUNC('month', CURRENT_DATE + INTERVAL '2 months');
    partition_name := 'api_audit_log_' || TO_CHAR(start_date, 'YYYY_MM');

    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'audit' AND c.relname = partition_name
    ) THEN
        EXECUTE format(
            'CREATE TABLE audit.%I PARTITION OF audit.api_audit_log
            FOR VALUES FROM (%L) TO (%L)',
            partition_name, start_date, end_date
        );
        RAISE NOTICE 'Created partition: audit.%', partition_name;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function to archive old partitions (move to cold storage schema)
CREATE SCHEMA IF NOT EXISTS audit_archive;
GRANT USAGE ON SCHEMA audit_archive TO ray_compute;

CREATE OR REPLACE FUNCTION audit.archive_old_partitions(months_to_keep INT DEFAULT 12)
RETURNS TABLE(archived_partition TEXT, row_count BIGINT) AS $$
DECLARE
    partition_rec RECORD;
    cutoff_date DATE;
    archive_name TEXT;
    count BIGINT;
BEGIN
    cutoff_date := DATE_TRUNC('month', CURRENT_DATE - (months_to_keep || ' months')::INTERVAL);

    FOR partition_rec IN
        SELECT c.relname as partition_name,
               pg_get_expr(c.relpartbound, c.oid) as bounds
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_inherits i ON i.inhrelid = c.oid
        JOIN pg_class parent ON parent.oid = i.inhparent
        WHERE n.nspname = 'audit'
          AND parent.relname = 'api_audit_log'
          AND c.relname ~ '^api_audit_log_[0-9]{4}_[0-9]{2}$'
    LOOP
        -- Extract date from partition name
        IF (SUBSTRING(partition_rec.partition_name FROM 'api_audit_log_([0-9]{4}_[0-9]{2})')::DATE) < cutoff_date THEN
            archive_name := partition_rec.partition_name;

            -- Get row count before archiving
            EXECUTE format('SELECT COUNT(*) FROM audit.%I', partition_rec.partition_name) INTO count;

            -- Detach partition from parent
            EXECUTE format('ALTER TABLE audit.api_audit_log DETACH PARTITION audit.%I', partition_rec.partition_name);

            -- Move to archive schema
            EXECUTE format('ALTER TABLE audit.%I SET SCHEMA audit_archive', partition_rec.partition_name);

            archived_partition := archive_name;
            row_count := count;
            RETURN NEXT;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- API Keys table for managing user and service account keys
CREATE TABLE IF NOT EXISTS public.api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Key identification
    name VARCHAR(100) NOT NULL,
    key_hash VARCHAR(255) NOT NULL,  -- SHA-256 hash of the actual key
    key_prefix VARCHAR(10) NOT NULL,  -- First 8 chars for identification (e.g., "shml_abc...")

    -- Ownership
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    service_account_type VARCHAR(50),  -- admin, elevated_developer, developer, viewer (for service account keys)

    -- Permissions
    scopes TEXT[] DEFAULT ARRAY['jobs:submit', 'jobs:read'],  -- What this key can do

    -- Lifecycle
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,  -- NULL = never expires
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    revoked_by UUID REFERENCES users(user_id),

    -- Rotation support (24h grace period)
    previous_key_hash VARCHAR(255),  -- Previous key hash during rotation
    previous_key_valid_until TIMESTAMPTZ,  -- When previous key stops working

    -- Metadata
    description TEXT,
    created_by UUID REFERENCES users(user_id),

    CONSTRAINT unique_key_hash UNIQUE (key_hash),
    CONSTRAINT unique_key_name_per_user UNIQUE (user_id, name)
);

CREATE INDEX IF NOT EXISTS ix_api_keys_user ON public.api_keys (user_id);
CREATE INDEX IF NOT EXISTS ix_api_keys_prefix ON public.api_keys (key_prefix);
CREATE INDEX IF NOT EXISTS ix_api_keys_service_account ON public.api_keys (service_account_type) WHERE service_account_type IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_api_keys_active ON public.api_keys (key_hash) WHERE revoked_at IS NULL;

-- Grant permissions
GRANT ALL ON public.api_keys TO ray_compute;

-- Insert default service account keys (using existing FUSIONAUTH_CICD_* keys)
-- These will be inserted by the application on startup if they don't exist

DO $$ BEGIN RAISE NOTICE 'Audit schema migration complete'; END $$;
