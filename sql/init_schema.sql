-- LANCompute Controller Database Schema
-- Purpose: Job queue and worker registration for distributed compute orchestration
-- Issue: TRUENAS #8 - Implement LANCompute Controller

-- Create lancompute schema
CREATE SCHEMA IF NOT EXISTS lancompute;

-- Workers table: registered compute nodes
CREATE TABLE IF NOT EXISTS lancompute.workers (
    id VARCHAR(64) PRIMARY KEY,
    hostname VARCHAR(255) NOT NULL,
    address VARCHAR(255) NOT NULL,
    port INTEGER NOT NULL DEFAULT 8080,
    tags TEXT[] DEFAULT '{}',
    capabilities JSONB DEFAULT '{}',
    status VARCHAR(20) NOT NULL DEFAULT 'offline',
    last_heartbeat TIMESTAMP WITH TIME ZONE,
    total_completed INTEGER DEFAULT 0,
    total_failed INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Jobs table: submitted compute jobs
CREATE TABLE IF NOT EXISTS lancompute.jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL DEFAULT 'batch',
    project_id VARCHAR(255),
    entrypoint TEXT NOT NULL,
    params JSONB DEFAULT '{}',
    requirements JSONB DEFAULT '{}',
    priority VARCHAR(20) DEFAULT 'normal',
    state VARCHAR(20) NOT NULL DEFAULT 'pending',
    worker_id VARCHAR(64) REFERENCES lancompute.workers(id) ON DELETE SET NULL,
    log_path TEXT,
    progress REAL DEFAULT 0.0,
    result JSONB,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Job states enum values: pending, queued, assigned, running, succeeded, failed, cancelled

-- Index for efficient job queue queries
CREATE INDEX IF NOT EXISTS idx_jobs_state ON lancompute.jobs(state);
CREATE INDEX IF NOT EXISTS idx_jobs_worker_id ON lancompute.jobs(worker_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON lancompute.jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_priority_state ON lancompute.jobs(priority, state) WHERE state = 'pending';

-- Index for worker heartbeat queries
CREATE INDEX IF NOT EXISTS idx_workers_status ON lancompute.workers(status);
CREATE INDEX IF NOT EXISTS idx_workers_last_heartbeat ON lancompute.workers(last_heartbeat);

-- Job logs table for capturing execution output
CREATE TABLE IF NOT EXISTS lancompute.job_logs (
    id SERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES lancompute.jobs(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    level VARCHAR(10) DEFAULT 'INFO',
    message TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_logs_job_id ON lancompute.job_logs(job_id);

-- Notifications table for tracking sent notifications
CREATE TABLE IF NOT EXISTS lancompute.notifications (
    id SERIAL PRIMARY KEY,
    job_id UUID REFERENCES lancompute.jobs(id) ON DELETE CASCADE,
    notification_type VARCHAR(50) NOT NULL,
    sent_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    success BOOLEAN DEFAULT TRUE,
    error TEXT
);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION lancompute.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers for auto-updating updated_at
DROP TRIGGER IF EXISTS workers_updated_at ON lancompute.workers;
CREATE TRIGGER workers_updated_at
    BEFORE UPDATE ON lancompute.workers
    FOR EACH ROW EXECUTE FUNCTION lancompute.update_updated_at();

DROP TRIGGER IF EXISTS jobs_updated_at ON lancompute.jobs;
CREATE TRIGGER jobs_updated_at
    BEFORE UPDATE ON lancompute.jobs
    FOR EACH ROW EXECUTE FUNCTION lancompute.update_updated_at();

-- View for active jobs with worker info
CREATE OR REPLACE VIEW lancompute.active_jobs AS
SELECT
    j.id,
    j.name,
    j.type,
    j.project_id,
    j.entrypoint,
    j.state,
    j.priority,
    j.progress,
    j.created_at,
    j.started_at,
    w.id AS worker_id,
    w.hostname AS worker_hostname,
    w.address AS worker_address
FROM lancompute.jobs j
LEFT JOIN lancompute.workers w ON j.worker_id = w.id
WHERE j.state IN ('pending', 'queued', 'assigned', 'running');

-- View for worker status summary
CREATE OR REPLACE VIEW lancompute.worker_status AS
SELECT
    w.id,
    w.hostname,
    w.address,
    w.status,
    w.last_heartbeat,
    w.total_completed,
    w.total_failed,
    COUNT(j.id) FILTER (WHERE j.state = 'running') AS active_jobs,
    w.capabilities
FROM lancompute.workers w
LEFT JOIN lancompute.jobs j ON w.id = j.worker_id AND j.state = 'running'
GROUP BY w.id;

COMMENT ON SCHEMA lancompute IS 'LANCompute distributed job orchestration system';
COMMENT ON TABLE lancompute.jobs IS 'Job queue for compute tasks';
COMMENT ON TABLE lancompute.workers IS 'Registered compute workers';
COMMENT ON TABLE lancompute.job_logs IS 'Execution logs for jobs';
