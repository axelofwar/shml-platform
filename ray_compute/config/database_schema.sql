-- Ray Compute Enhanced Database Schema
-- Supports OAuth, user management, quotas, job tracking

-- Users table
CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'premium', 'user')),
    oauth_sub VARCHAR(255) UNIQUE,  -- OAuth subject ID from Authentik
    api_key_hash VARCHAR(255),      -- Fallback API key (hashed)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE,
    is_suspended BOOLEAN DEFAULT FALSE,
    suspension_reason TEXT,
    suspended_at TIMESTAMP WITH TIME ZONE,
    suspended_by UUID REFERENCES users(user_id)
);

-- User quotas table
CREATE TABLE IF NOT EXISTS user_quotas (
    user_id UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    max_concurrent_jobs INTEGER NOT NULL DEFAULT 3,
    max_gpu_hours_per_day DECIMAL(10, 2) NOT NULL DEFAULT 24.0,
    max_cpu_hours_per_day DECIMAL(10, 2) NOT NULL DEFAULT 100.0,
    max_storage_gb INTEGER NOT NULL DEFAULT 50,
    max_artifact_size_gb INTEGER NOT NULL DEFAULT 50,
    max_job_timeout_hours INTEGER NOT NULL DEFAULT 48,
    priority_weight INTEGER NOT NULL DEFAULT 1,  -- For weighted fair scheduling
    can_use_custom_docker BOOLEAN DEFAULT FALSE,
    can_skip_validation BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Jobs table (enhanced)
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
    
    -- Resources
    cpu_requested INTEGER NOT NULL,
    memory_gb_requested INTEGER NOT NULL,
    gpu_requested DECIMAL(3, 2) NOT NULL DEFAULT 0.00,  -- Fractional GPU support
    timeout_hours INTEGER NOT NULL,
    
    -- Actual usage (populated during/after execution)
    cpu_used_hours DECIMAL(10, 2),
    gpu_used_hours DECIMAL(10, 2),
    memory_peak_gb DECIMAL(10, 2),
    disk_used_gb DECIMAL(10, 2),
    
    -- Docker configuration
    base_image VARCHAR(255),
    dockerfile_hash VARCHAR(64),  -- SHA256 of Dockerfile for caching
    custom_dockerfile BOOLEAN DEFAULT FALSE,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    queued_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE,
    ended_at TIMESTAMP WITH TIME ZONE,
    
    -- Output
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
    depends_on VARCHAR(255)[],  -- Array of job_ids
    
    -- Error handling
    error_message TEXT,
    error_traceback TEXT,
    exit_code INTEGER,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    
    -- Audit
    cancelled_by UUID REFERENCES users(user_id),
    cancelled_at TIMESTAMP WITH TIME ZONE,
    cancellation_reason TEXT
);

-- Job queue table (for scheduling)
CREATE TABLE IF NOT EXISTS job_queue (
    queue_id SERIAL PRIMARY KEY,
    job_id VARCHAR(255) UNIQUE NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id),
    priority_score DECIMAL(10, 2) NOT NULL,  -- Calculated: role weight + user priority + age
    estimated_vram_gb DECIMAL(5, 2),
    estimated_runtime_minutes INTEGER,
    can_backfill BOOLEAN DEFAULT FALSE,  -- Small jobs that can jump queue
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    attempts INTEGER DEFAULT 0,
    last_attempt_at TIMESTAMP WITH TIME ZONE
);

-- Artifact versions table
CREATE TABLE IF NOT EXISTS artifact_versions (
    version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id VARCHAR(255) NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    artifact_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    compressed_size_bytes BIGINT,
    compression_algorithm VARCHAR(50) DEFAULT 'zstd',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    accessed_at TIMESTAMP WITH TIME ZONE,
    access_count INTEGER DEFAULT 0,
    is_latest BOOLEAN DEFAULT TRUE,
    UNIQUE(job_id, version_number)
);

-- Resource usage tracking (for billing/analytics)
CREATE TABLE IF NOT EXISTS resource_usage_daily (
    usage_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id),
    date DATE NOT NULL,
    cpu_hours DECIMAL(10, 2) DEFAULT 0,
    gpu_hours DECIMAL(10, 2) DEFAULT 0,
    storage_gb_hours DECIMAL(10, 2) DEFAULT 0,  -- For billing
    jobs_submitted INTEGER DEFAULT 0,
    jobs_completed INTEGER DEFAULT 0,
    jobs_failed INTEGER DEFAULT 0,
    UNIQUE(user_id, date)
);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    user_id UUID REFERENCES users(user_id),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id VARCHAR(255),
    details JSONB,
    ip_address INET,
    user_agent TEXT
);

-- System alerts table
CREATE TABLE IF NOT EXISTS system_alerts (
    alert_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by UUID REFERENCES users(user_id),
    notified_users UUID[]
);

-- Indexes for performance
CREATE INDEX idx_jobs_user_id ON jobs(user_id);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_created_at ON jobs(created_at DESC);
CREATE INDEX idx_jobs_user_status ON jobs(user_id, status);
CREATE INDEX idx_job_queue_priority ON job_queue(priority_score DESC, added_at ASC);
CREATE INDEX idx_artifact_versions_job_id ON artifact_versions(job_id);
CREATE INDEX idx_resource_usage_user_date ON resource_usage_daily(user_id, date);
CREATE INDEX idx_audit_log_user_timestamp ON audit_log(user_id, timestamp DESC);
CREATE INDEX idx_audit_log_action ON audit_log(action);

-- Triggers for updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_quotas_updated_at BEFORE UPDATE ON user_quotas
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Function to calculate queue priority
CREATE OR REPLACE FUNCTION calculate_queue_priority(
    p_user_role VARCHAR,
    p_job_priority VARCHAR,
    p_priority_weight INTEGER,
    p_queue_age_minutes INTEGER
)
RETURNS DECIMAL(10, 2) AS $$
DECLARE
    role_multiplier DECIMAL(5, 2);
    priority_multiplier DECIMAL(5, 2);
    age_bonus DECIMAL(5, 2);
BEGIN
    -- Role multiplier (admin highest, user lowest)
    role_multiplier := CASE p_user_role
        WHEN 'admin' THEN 10.0
        WHEN 'premium' THEN 5.0
        ELSE 1.0
    END;
    
    -- Job priority multiplier
    priority_multiplier := CASE p_job_priority
        WHEN 'critical' THEN 3.0
        WHEN 'high' THEN 2.0
        WHEN 'normal' THEN 1.0
        ELSE 0.5
    END;
    
    -- Age bonus (0.1 points per hour waiting, up to max 50)
    age_bonus := LEAST(p_queue_age_minutes / 600.0, 50.0);
    
    RETURN (role_multiplier * priority_multiplier * p_priority_weight) + age_bonus;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function to check user quota compliance
CREATE OR REPLACE FUNCTION check_user_quota(p_user_id UUID)
RETURNS TABLE(
    can_submit BOOLEAN,
    reason TEXT,
    current_jobs INTEGER,
    gpu_hours_today DECIMAL,
    cpu_hours_today DECIMAL
) AS $$
DECLARE
    v_quota RECORD;
    v_current_jobs INTEGER;
    v_gpu_hours_today DECIMAL;
    v_cpu_hours_today DECIMAL;
BEGIN
    -- Get user quota
    SELECT * INTO v_quota FROM user_quotas WHERE user_id = p_user_id;
    
    -- Count running jobs
    SELECT COUNT(*) INTO v_current_jobs
    FROM jobs
    WHERE user_id = p_user_id
      AND status IN ('PENDING', 'RUNNING');
    
    -- Get usage today
    SELECT
        COALESCE(gpu_hours, 0),
        COALESCE(cpu_hours, 0)
    INTO v_gpu_hours_today, v_cpu_hours_today
    FROM resource_usage_daily
    WHERE user_id = p_user_id
      AND date = CURRENT_DATE;
    
    -- Check quotas
    IF v_current_jobs >= v_quota.max_concurrent_jobs THEN
        RETURN QUERY SELECT FALSE, 'Max concurrent jobs exceeded', v_current_jobs, v_gpu_hours_today, v_cpu_hours_today;
    ELSIF v_gpu_hours_today >= v_quota.max_gpu_hours_per_day THEN
        RETURN QUERY SELECT FALSE, 'GPU hours quota exceeded for today', v_current_jobs, v_gpu_hours_today, v_cpu_hours_today;
    ELSIF v_cpu_hours_today >= v_quota.max_cpu_hours_per_day THEN
        RETURN QUERY SELECT FALSE, 'CPU hours quota exceeded for today', v_current_jobs, v_gpu_hours_today, v_cpu_hours_today;
    ELSE
        RETURN QUERY SELECT TRUE, 'OK', v_current_jobs, v_gpu_hours_today, v_cpu_hours_today;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Insert default admin user (change credentials!)
INSERT INTO users (username, email, role, is_active)
VALUES ('admin', 'admin@raycompute.local', 'admin', TRUE)
ON CONFLICT (username) DO NOTHING;

-- Set admin quotas (unlimited)
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
    999,      -- Unlimited concurrent jobs
    99999.0,  -- Unlimited GPU hours
    99999.0,  -- Unlimited CPU hours
    99999,    -- Unlimited storage
    99999,    -- Unlimited artifact size
    168,      -- 7 days max timeout
    10,       -- Highest priority weight
    TRUE,     -- Can use custom Docker
    TRUE      -- Can skip validation
FROM users
WHERE role = 'admin'
ON CONFLICT (user_id) DO NOTHING;

-- Default quotas for premium users
CREATE OR REPLACE FUNCTION set_default_quotas()
RETURNS TRIGGER AS $$
BEGIN
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
    VALUES (
        NEW.user_id,
        CASE NEW.role
            WHEN 'admin' THEN 999
            WHEN 'premium' THEN 10
            ELSE 3
        END,
        CASE NEW.role
            WHEN 'admin' THEN 99999.0
            WHEN 'premium' THEN 100.0
            ELSE 24.0
        END,
        CASE NEW.role
            WHEN 'admin' THEN 99999.0
            WHEN 'premium' THEN 500.0
            ELSE 100.0
        END,
        CASE NEW.role
            WHEN 'admin' THEN 99999
            WHEN 'premium' THEN 200
            ELSE 50
        END,
        CASE NEW.role
            WHEN 'admin' THEN 99999
            WHEN 'premium' THEN 100
            ELSE 50
        END,
        CASE NEW.role
            WHEN 'admin' THEN 168
            WHEN 'premium' THEN 72
            ELSE 48
        END,
        CASE NEW.role
            WHEN 'admin' THEN 10
            WHEN 'premium' THEN 5
            ELSE 1
        END,
        CASE NEW.role
            WHEN 'admin' THEN TRUE
            WHEN 'premium' THEN TRUE
            ELSE FALSE
        END,
        CASE NEW.role
            WHEN 'admin' THEN TRUE
            ELSE FALSE
        END
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_user_default_quotas
    AFTER INSERT ON users
    FOR EACH ROW
    EXECUTE FUNCTION set_default_quotas();

-- View for admin dashboard
CREATE OR REPLACE VIEW admin_job_summary AS
SELECT
    j.job_id,
    j.name,
    u.username,
    u.role AS user_role,
    j.status,
    j.job_type,
    j.priority,
    j.cpu_requested,
    j.memory_gb_requested,
    j.gpu_requested,
    j.created_at,
    j.started_at,
    j.ended_at,
    EXTRACT(EPOCH FROM (COALESCE(j.ended_at, NOW()) - j.started_at)) / 3600 AS runtime_hours,
    j.artifact_size_bytes / 1024.0 / 1024.0 / 1024.0 AS artifact_size_gb,
    j.cpu_used_hours,
    j.gpu_used_hours
FROM jobs j
JOIN users u ON j.user_id = u.user_id
ORDER BY j.created_at DESC;

COMMENT ON TABLE users IS 'User accounts with OAuth integration';
COMMENT ON TABLE user_quotas IS 'Resource quotas per user role';
COMMENT ON TABLE jobs IS 'Job execution tracking with enhanced metadata';
COMMENT ON TABLE job_queue IS 'Priority queue for job scheduling';
COMMENT ON TABLE artifact_versions IS 'Versioned artifact storage';
COMMENT ON TABLE resource_usage_daily IS 'Daily resource usage for billing';
COMMENT ON TABLE audit_log IS 'Complete audit trail of all actions';
COMMENT ON TABLE system_alerts IS 'System-wide alerts and notifications';
