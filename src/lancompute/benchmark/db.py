"""Database operations for benchmark results."""

import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkRun:
    """Represents a benchmark run result."""

    id: int
    worker_id: str
    benchmark_type: str
    status: str
    gpu_name: Optional[str] = None
    gpu_memory_mb: Optional[int] = None
    cuda_version: Optional[str] = None
    pytorch_version: Optional[str] = None
    accuracy: Optional[float] = None
    samples_per_second: Optional[float] = None
    training_time_seconds: Optional[float] = None
    epochs: Optional[int] = None
    batch_size: Optional[int] = None
    is_regression: bool = False
    regression_reason: Optional[str] = None
    accuracy_delta_percent: Optional[float] = None
    throughput_delta_percent: Optional[float] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "BenchmarkRun":
        return cls(
            id=row["id"],
            worker_id=row.get("worker_id", ""),
            benchmark_type=row.get("benchmark_type", "cifar10"),
            status=row.get("status", "unknown"),
            gpu_name=row.get("gpu_name"),
            gpu_memory_mb=row.get("gpu_memory_mb"),
            cuda_version=row.get("cuda_version"),
            pytorch_version=row.get("pytorch_version"),
            accuracy=row.get("accuracy"),
            samples_per_second=row.get("samples_per_second"),
            training_time_seconds=row.get("training_time_seconds"),
            epochs=row.get("epochs"),
            batch_size=row.get("batch_size"),
            is_regression=row.get("is_regression", False),
            regression_reason=row.get("regression_reason"),
            accuracy_delta_percent=row.get("accuracy_delta_percent"),
            throughput_delta_percent=row.get("throughput_delta_percent"),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            error=row.get("error"),
        )


@dataclass
class BenchmarkBaseline:
    """Represents a benchmark baseline."""

    worker_id: str
    benchmark_type: str
    accuracy: float
    samples_per_second: float
    set_at: Optional[datetime] = None


class BenchmarkDB:
    """Database interface for benchmark results."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        if psycopg2 is None:
            raise ImportError("psycopg2 is required")

        self.host = host or os.environ.get("LANCOMPUTE_DB_HOST", "192.168.1.134")
        self.port = port or int(os.environ.get("LANCOMPUTE_DB_PORT", "5432"))
        self.database = database or os.environ.get("LANCOMPUTE_DB_NAME", "postgres")
        self.user = user or os.environ.get("LANCOMPUTE_DB_USER", "mmarinucci@numinate.com")
        self.password = password or os.environ.get("LANCOMPUTE_DB_PASSWORD", "")
        self._conn = None

    def connect(self) -> None:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.database,
                user=self.user,
                password=self.password,
            )
            self._conn.autocommit = False

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _cursor(self):
        self.connect()
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def start_benchmark_run(
        self,
        worker_id: str,
        benchmark_type: str = "cifar10",
        gpu_info: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Start a new benchmark run and return its ID."""
        gpu_info = gpu_info or {}

        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO lancompute.benchmark_runs
                    (worker_id, benchmark_type, status, gpu_name, gpu_memory_mb,
                     cuda_version, pytorch_version, driver_version)
                VALUES (%s, %s, 'running', %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    worker_id,
                    benchmark_type,
                    gpu_info.get("name"),
                    gpu_info.get("memory_mb"),
                    gpu_info.get("cuda_version"),
                    gpu_info.get("pytorch_version"),
                    gpu_info.get("driver_version"),
                ),
            )
            run_id = cur.fetchone()["id"]
            self._conn.commit()
            return run_id

    def complete_benchmark_run(
        self,
        run_id: int,
        accuracy: float,
        samples_per_second: float,
        training_time_seconds: float,
        epochs: int,
        batch_size: int,
        results: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Mark a benchmark run as completed with results."""
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE lancompute.benchmark_runs SET
                    status = 'completed',
                    completed_at = NOW(),
                    accuracy = %s,
                    samples_per_second = %s,
                    training_time_seconds = %s,
                    epochs = %s,
                    batch_size = %s,
                    results = %s
                WHERE id = %s
                """,
                (
                    accuracy,
                    samples_per_second,
                    training_time_seconds,
                    epochs,
                    batch_size,
                    psycopg2.extras.Json(results or {}),
                    run_id,
                ),
            )
            self._conn.commit()

    def fail_benchmark_run(self, run_id: int, error: str) -> None:
        """Mark a benchmark run as failed."""
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE lancompute.benchmark_runs SET
                    status = 'failed',
                    completed_at = NOW(),
                    error = %s
                WHERE id = %s
                """,
                (error, run_id),
            )
            self._conn.commit()

    def check_regression(self, run_id: int, threshold_percent: float = 10.0) -> bool:
        """Check if a benchmark run shows regression."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT lancompute.check_benchmark_regression(%s, %s)",
                (run_id, threshold_percent),
            )
            result = cur.fetchone()
            self._conn.commit()
            return result[0] if result else False

    def get_run(self, run_id: int) -> Optional[BenchmarkRun]:
        """Get a benchmark run by ID."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM lancompute.benchmark_runs WHERE id = %s",
                (run_id,),
            )
            row = cur.fetchone()
            return BenchmarkRun.from_row(row) if row else None

    def get_latest_runs(
        self,
        worker_id: Optional[str] = None,
        benchmark_type: str = "cifar10",
        limit: int = 10,
    ) -> List[BenchmarkRun]:
        """Get latest benchmark runs."""
        conditions = ["benchmark_type = %s"]
        params: List[Any] = [benchmark_type]

        if worker_id:
            conditions.append("worker_id = %s")
            params.append(worker_id)

        params.append(limit)

        with self._cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM lancompute.benchmark_runs
                WHERE {' AND '.join(conditions)}
                ORDER BY started_at DESC
                LIMIT %s
                """,
                params,
            )
            return [BenchmarkRun.from_row(row) for row in cur.fetchall()]

    def get_baseline(
        self,
        worker_id: str,
        benchmark_type: str = "cifar10",
    ) -> Optional[BenchmarkBaseline]:
        """Get baseline for a worker."""
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT * FROM lancompute.benchmark_baselines
                WHERE worker_id = %s AND benchmark_type = %s
                """,
                (worker_id, benchmark_type),
            )
            row = cur.fetchone()
            if row:
                return BenchmarkBaseline(
                    worker_id=row["worker_id"],
                    benchmark_type=row["benchmark_type"],
                    accuracy=row["accuracy"],
                    samples_per_second=row["samples_per_second"],
                    set_at=row.get("set_at"),
                )
            return None

    def set_baseline(
        self,
        worker_id: str,
        accuracy: float,
        samples_per_second: float,
        benchmark_type: str = "cifar10",
        run_id: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> None:
        """Set or update baseline for a worker."""
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO lancompute.benchmark_baselines
                    (worker_id, benchmark_type, accuracy, samples_per_second, run_id, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (worker_id, benchmark_type) DO UPDATE SET
                    accuracy = EXCLUDED.accuracy,
                    samples_per_second = EXCLUDED.samples_per_second,
                    set_at = NOW(),
                    run_id = EXCLUDED.run_id,
                    notes = EXCLUDED.notes
                """,
                (worker_id, benchmark_type, accuracy, samples_per_second, run_id, notes),
            )
            self._conn.commit()

    def get_regressions(
        self,
        days: int = 7,
        limit: int = 20,
    ) -> List[BenchmarkRun]:
        """Get recent regression runs."""
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT * FROM lancompute.benchmark_runs
                WHERE is_regression = TRUE
                  AND started_at > NOW() - INTERVAL '%s days'
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (days, limit),
            )
            return [BenchmarkRun.from_row(row) for row in cur.fetchall()]

    def get_stats(self, worker_id: Optional[str] = None) -> Dict[str, Any]:
        """Get benchmark statistics."""
        conditions = []
        params: List[Any] = []

        if worker_id:
            conditions.append("worker_id = %s")
            params.append(worker_id)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        with self._cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                    COUNT(*) FILTER (WHERE status = 'running') AS running,
                    COUNT(*) FILTER (WHERE is_regression = TRUE) AS regressions,
                    AVG(accuracy) FILTER (WHERE status = 'completed') AS avg_accuracy,
                    AVG(samples_per_second) FILTER (WHERE status = 'completed') AS avg_throughput,
                    MAX(accuracy) FILTER (WHERE status = 'completed') AS best_accuracy,
                    MAX(samples_per_second) FILTER (WHERE status = 'completed') AS best_throughput,
                    COUNT(DISTINCT worker_id) AS worker_count
                FROM lancompute.benchmark_runs
                {where}
                """,
                params,
            )
            row = cur.fetchone()
            return dict(row) if row else {}
