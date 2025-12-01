-- Ray Compute Platform - Initial Database Schema
-- Migration: 001_initial_schema.sql
-- Created: 2025-11-23
-- Description: Initial database schema with users, jobs, quotas, and audit logging

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- USERS AND AUTHENTICATION
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(255) UNIQUE,
    email VARCHAR(255) UNIQUE,
    role VARCHAR(50) NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'premium', 'user')),
    oauth_sub VARCHAR(255) UNIQUE,  -- Authentik OAuth subject
    api_key_hash VARCHAR(255),

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP WITH TIME ZONE,

    is_active BOOLEAN DEFAULT TRUE,
    is_suspended BOOLEAN DEFAULT FALSE,
    suspension_reason TEXT,
    suspended_at TIMESTAMP WITH TIME ZONE,
    suspended_by UUID REFERENCES users(user_id)
);

-- Indexes for users table
CREATE INDEX IF NOT EXISTS idx_users_oauth_sub ON users(oauth_sub);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);

-- =============================================================================
-- USER QUOTAS AND RESOURCE LIMITS
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_quotas (
    user_id UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    max_concurrent_jobs INTEGER NOT NULL DEFAULT 3,
    max_gpu_hours_per_day NUMERIC(10, 2) NOT NULL DEFAULT 24.0,
    max_cpu_hours_per_day NUMERIC(10, 2) NOT NULL DEFAULT 100.0,
    max_storage_gb INTEGER NOT NULL DEFAULT 50,
    max_artifact_size_gb INTEGER NOT NULL DEFAULT 50,
    max_job_timeout_hours INTEGER NOT NULL DEFAULT 48,
    priority_weight INTEGER NOT NULL DEFAULT 1,
    can_use_custom_docker BOOLEAN DEFAULT FALSE,
    can_skip_validation BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- JOBS
-- =============================================================================

CREATE TABLE IF NOT EXISTS jobs (
    job_id VARCHAR(255) PRIMARY KEY,
    ray_job_id VARCHAR(255) UNIQUE,
    user_id UUID NOT NULL REFERENCES users(user_id),

    name VARCHAR(255) NOT NULL,
    description TEXT,
    job_type VARCHAR(50) NOT NULL,
    language VARCHAR(50) NOT NULL DEFAULT 'python',
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    priority VARCHAR(50) NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'critical')),

    -- Resource requests
    cpu_requested INTEGER NOT NULL,
    memory_gb_requested INTEGER NOT NULL,
    gpu_requested NUMERIC(3, 2) NOT NULL DEFAULT 0.00,
    timeout_hours INTEGER NOT NULL,

    -- Actual resource usage
    cpu_used_hours NUMERIC(10, 2),
    gpu_used_hours NUMERIC(10, 2),
    memory_peak_gb NUMERIC(10, 2),
    disk_used_gb NUMERIC(10, 2),

    -- Docker configuration
    base_image VARCHAR(255),
    dockerfile_hash VARCHAR(64),
    custom_dockerfile BOOLEAN DEFAULT FALSE,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    queued_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE,
    ended_at TIMESTAMP WITH TIME ZONE,

    -- Artifacts and outputs
    output_mode VARCHAR(50) DEFAULT 'artifacts',
    artifact_path TEXT,
    artifact_size_bytes BIGINT,
    artifact_retention_days INTEGER DEFAULT 90,
    artifact_downloaded_at TIMESTAMP WITH TIME ZONE,
    mlflow_experiment VARCHAR(255),
    mlflow_run_id VARCHAR(255),

    -- Metadata
    tags TEXT[],
    cost_center VARCHAR(255),
    depends_on VARCHAR(255)[],

    -- Error handling
    error_message TEXT,
    error_traceback TEXT,
    exit_code INTEGER,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,

    -- Audit trail
    cancelled_by UUID REFERENCES users(user_id),
    cancelled_at TIMESTAMP WITH TIME ZONE,
    cancellation_reason TEXT
);

-- Indexes for jobs table
CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_priority ON jobs(priority);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_ray_job_id ON jobs(ray_job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_mlflow_run_id ON jobs(mlflow_run_id);

-- =============================================================================
-- JOB QUEUE
-- =============================================================================

CREATE TABLE IF NOT EXISTS job_queue (
    queue_id SERIAL PRIMARY KEY,
    job_id VARCHAR(255) NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id),
    priority_score NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    enqueued_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    estimated_start_time TIMESTAMP WITH TIME ZONE,
    position_in_queue INTEGER
);

-- Indexes for job_queue table
CREATE INDEX IF NOT EXISTS idx_job_queue_priority_score ON job_queue(priority_score DESC);
CREATE INDEX IF NOT EXISTS idx_job_queue_enqueued_at ON job_queue(enqueued_at);
CREATE INDEX IF NOT EXISTS idx_job_queue_user_id ON job_queue(user_id);

-- =============================================================================
-- ARTIFACT VERSIONING
-- =============================================================================

CREATE TABLE IF NOT EXISTS artifact_versions (
    artifact_id SERIAL PRIMARY KEY,
    job_id VARCHAR(255) NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1,
    artifact_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    checksum VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE,
    downloaded_count INTEGER DEFAULT 0,
    last_accessed TIMESTAMP WITH TIME ZONE,
    is_deleted BOOLEAN DEFAULT FALSE
);

-- Indexes for artifact_versions table
CREATE INDEX IF NOT EXISTS idx_artifact_versions_job_id ON artifact_versions(job_id);
CREATE INDEX IF NOT EXISTS idx_artifact_versions_expires_at ON artifact_versions(expires_at);
CREATE INDEX IF NOT EXISTS idx_artifact_versions_is_deleted ON artifact_versions(is_deleted);

-- =============================================================================
-- RESOURCE USAGE TRACKING
-- =============================================================================

CREATE TABLE IF NOT EXISTS resource_usage_daily (
    usage_id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id),
    usage_date TIMESTAMP WITH TIME ZONE NOT NULL,
    cpu_hours NUMERIC(10, 2) DEFAULT 0.00,
    gpu_hours NUMERIC(10, 2) DEFAULT 0.00,
    storage_gb NUMERIC(10, 2) DEFAULT 0.00,
    jobs_completed INTEGER DEFAULT 0,
    jobs_failed INTEGER DEFAULT 0,

    UNIQUE(user_id, usage_date)
);

-- Indexes for resource_usage_daily table
CREATE INDEX IF NOT EXISTS idx_resource_usage_user_date ON resource_usage_daily(user_id, usage_date DESC);
CREATE INDEX IF NOT EXISTS idx_resource_usage_date ON resource_usage_daily(usage_date DESC);

-- =============================================================================
-- AUDIT LOGGING
-- =============================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    log_id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(user_id),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id VARCHAR(255),
    details TEXT,
    ip_address VARCHAR(45),
    user_agent TEXT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN DEFAULT TRUE
);

-- Indexes for audit_log table
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_resource_type ON audit_log(resource_type);

-- =============================================================================
-- SYSTEM ALERTS
-- =============================================================================

CREATE TABLE IF NOT EXISTS system_alerts (
    alert_id SERIAL PRIMARY KEY,
    severity VARCHAR(50) NOT NULL CHECK (severity IN ('info', 'warning', 'error', 'critical')),
    alert_type VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    details TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by UUID REFERENCES users(user_id),
    is_acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by UUID REFERENCES users(user_id),
    acknowledged_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for system_alerts table
CREATE INDEX IF NOT EXISTS idx_system_alerts_severity ON system_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_system_alerts_created_at ON system_alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_system_alerts_resolved ON system_alerts(resolved_at) WHERE resolved_at IS NULL;

-- =============================================================================
-- SCHEMA MIGRATIONS TRACKING
-- =============================================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id SERIAL PRIMARY KEY,
    migration_name VARCHAR(255) UNIQUE NOT NULL,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT
);

-- Record this migration
INSERT INTO schema_migrations (migration_name, success)
VALUES ('001_initial_schema.sql', TRUE)
ON CONFLICT (migration_name) DO NOTHING;

-- =============================================================================
-- FUNCTIONS AND TRIGGERS
-- =============================================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger for users table
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Trigger for user_quotas table
DROP TRIGGER IF EXISTS update_user_quotas_updated_at ON user_quotas;
CREATE TRIGGER update_user_quotas_updated_at
    BEFORE UPDATE ON user_quotas
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- DEFAULT DATA
-- =============================================================================

-- Create default admin user (if not exists)
-- Password should be set via OAuth or API
INSERT INTO users (user_id, username, email, role, is_active)
VALUES (
    gen_random_uuid(),
    'admin',
    'admin@raycompute.local',
    'admin',
    TRUE
)
ON CONFLICT (username) DO NOTHING;

-- Grant schema permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ray_compute;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ray_compute;

-- Complete
SELECT 'Schema migration 001_initial_schema.sql completed successfully' AS status;
