-- LANCompute Benchmark Schema
-- Purpose: Store GPU benchmark results for regression tracking
-- Issue: TRUENAS #9 - Automate GPU benchmark regression testing

-- Benchmark runs table
CREATE TABLE IF NOT EXISTS lancompute.benchmark_runs (
    id SERIAL PRIMARY KEY,
    worker_id VARCHAR(64) REFERENCES lancompute.workers(id) ON DELETE SET NULL,
    benchmark_type VARCHAR(50) NOT NULL DEFAULT 'cifar10',
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) NOT NULL DEFAULT 'running',

    -- Hardware info captured at runtime
    gpu_name VARCHAR(255),
    gpu_memory_mb INTEGER,
    cuda_version VARCHAR(50),
    pytorch_version VARCHAR(50),
    driver_version VARCHAR(50),

    -- Results
    accuracy REAL,
    samples_per_second REAL,
    training_time_seconds REAL,
    epochs INTEGER,
    batch_size INTEGER,

    -- Regression detection
    baseline_accuracy REAL,
    baseline_samples_per_second REAL,
    accuracy_delta_percent REAL,
    throughput_delta_percent REAL,
    is_regression BOOLEAN DEFAULT FALSE,
    regression_reason TEXT,

    -- Full results JSON
    results JSONB,
    error TEXT,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for efficient queries
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_worker ON lancompute.benchmark_runs(worker_id);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_type ON lancompute.benchmark_runs(benchmark_type);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_started ON lancompute.benchmark_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_regression ON lancompute.benchmark_runs(is_regression) WHERE is_regression = TRUE;

-- Baseline configuration table
CREATE TABLE IF NOT EXISTS lancompute.benchmark_baselines (
    id SERIAL PRIMARY KEY,
    worker_id VARCHAR(64) NOT NULL,
    benchmark_type VARCHAR(50) NOT NULL DEFAULT 'cifar10',
    accuracy REAL NOT NULL,
    samples_per_second REAL NOT NULL,
    set_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    run_id INTEGER REFERENCES lancompute.benchmark_runs(id),
    notes TEXT,

    UNIQUE(worker_id, benchmark_type)
);

-- View for latest benchmark per worker
CREATE OR REPLACE VIEW lancompute.latest_benchmarks AS
SELECT DISTINCT ON (worker_id, benchmark_type)
    br.*,
    w.hostname AS worker_hostname
FROM lancompute.benchmark_runs br
LEFT JOIN lancompute.workers w ON br.worker_id = w.id
WHERE br.status = 'completed'
ORDER BY worker_id, benchmark_type, started_at DESC;

-- View for benchmark trends (last 30 days)
CREATE OR REPLACE VIEW lancompute.benchmark_trends AS
SELECT
    worker_id,
    benchmark_type,
    DATE(started_at) AS run_date,
    AVG(accuracy) AS avg_accuracy,
    AVG(samples_per_second) AS avg_throughput,
    COUNT(*) AS run_count,
    SUM(CASE WHEN is_regression THEN 1 ELSE 0 END) AS regression_count
FROM lancompute.benchmark_runs
WHERE started_at > NOW() - INTERVAL '30 days'
  AND status = 'completed'
GROUP BY worker_id, benchmark_type, DATE(started_at)
ORDER BY run_date DESC;

-- Function to check for regression
CREATE OR REPLACE FUNCTION lancompute.check_benchmark_regression(
    p_run_id INTEGER,
    p_threshold_percent REAL DEFAULT 10.0
) RETURNS BOOLEAN AS $$
DECLARE
    v_run RECORD;
    v_baseline RECORD;
    v_accuracy_delta REAL;
    v_throughput_delta REAL;
    v_is_regression BOOLEAN := FALSE;
    v_reason TEXT := '';
BEGIN
    -- Get the run
    SELECT * INTO v_run FROM lancompute.benchmark_runs WHERE id = p_run_id;
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Get baseline
    SELECT * INTO v_baseline
    FROM lancompute.benchmark_baselines
    WHERE worker_id = v_run.worker_id
      AND benchmark_type = v_run.benchmark_type;

    IF NOT FOUND THEN
        -- No baseline, can't detect regression
        RETURN FALSE;
    END IF;

    -- Calculate deltas
    v_accuracy_delta := ((v_run.accuracy - v_baseline.accuracy) / v_baseline.accuracy) * 100;
    v_throughput_delta := ((v_run.samples_per_second - v_baseline.samples_per_second) / v_baseline.samples_per_second) * 100;

    -- Check for regression (negative delta beyond threshold)
    IF v_accuracy_delta < -p_threshold_percent THEN
        v_is_regression := TRUE;
        v_reason := v_reason || 'Accuracy dropped ' || round(-v_accuracy_delta::numeric, 1) || '% (threshold: ' || round(p_threshold_percent::numeric, 1) || '%). ';
    END IF;

    IF v_throughput_delta < -p_threshold_percent THEN
        v_is_regression := TRUE;
        v_reason := v_reason || 'Throughput dropped ' || round(-v_throughput_delta::numeric, 1) || '% (threshold: ' || round(p_threshold_percent::numeric, 1) || '%). ';
    END IF;

    -- Update the run record
    UPDATE lancompute.benchmark_runs SET
        baseline_accuracy = v_baseline.accuracy,
        baseline_samples_per_second = v_baseline.samples_per_second,
        accuracy_delta_percent = v_accuracy_delta,
        throughput_delta_percent = v_throughput_delta,
        is_regression = v_is_regression,
        regression_reason = NULLIF(TRIM(v_reason), '')
    WHERE id = p_run_id;

    RETURN v_is_regression;
END;
$$ LANGUAGE plpgsql;

COMMENT ON TABLE lancompute.benchmark_runs IS 'GPU benchmark execution results';
COMMENT ON TABLE lancompute.benchmark_baselines IS 'Baseline performance for regression detection';
COMMENT ON FUNCTION lancompute.check_benchmark_regression IS 'Check if a benchmark run shows regression vs baseline';
