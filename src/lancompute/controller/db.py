"""PostgreSQL database backend for LANCompute Controller."""

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

logger = logging.getLogger(__name__)


class JobState(Enum):
    """Job execution states."""

    PENDING = "pending"
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Priority(Enum):
    """Job priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


@dataclass
class Job:
    """Represents a compute job."""

    id: str
    name: str
    entrypoint: str
    type: str = "batch"
    project_id: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    requirements: Dict[str, Any] = field(default_factory=dict)
    priority: str = "normal"
    state: str = "pending"
    worker_id: Optional[str] = None
    log_path: Optional[str] = None
    progress: float = 0.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Job":
        """Create Job from database row."""
        return cls(
            id=str(row["id"]),
            name=row["name"],
            entrypoint=row["entrypoint"],
            type=row.get("type", "batch"),
            project_id=row.get("project_id"),
            params=row.get("params") or {},
            requirements=row.get("requirements") or {},
            priority=row.get("priority", "normal"),
            state=row.get("state", "pending"),
            worker_id=row.get("worker_id"),
            log_path=row.get("log_path"),
            progress=row.get("progress", 0.0),
            result=row.get("result"),
            error=row.get("error"),
            created_at=row.get("created_at"),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
        )


@dataclass
class Worker:
    """Represents a compute worker."""

    id: str
    hostname: str
    address: str
    port: int = 8080
    tags: List[str] = field(default_factory=list)
    capabilities: Dict[str, Any] = field(default_factory=dict)
    status: str = "offline"
    last_heartbeat: Optional[datetime] = None
    total_completed: int = 0
    total_failed: int = 0
    created_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Worker":
        """Create Worker from database row."""
        return cls(
            id=row["id"],
            hostname=row["hostname"],
            address=row["address"],
            port=row.get("port", 8080),
            tags=row.get("tags") or [],
            capabilities=row.get("capabilities") or {},
            status=row.get("status", "offline"),
            last_heartbeat=row.get("last_heartbeat"),
            total_completed=row.get("total_completed", 0),
            total_failed=row.get("total_failed", 0),
            created_at=row.get("created_at"),
        )


class Database:
    """PostgreSQL database interface for LANCompute Controller."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        """Initialize database connection.

        Connection parameters can be provided directly or via environment variables:
        - LANCOMPUTE_DB_HOST
        - LANCOMPUTE_DB_PORT
        - LANCOMPUTE_DB_NAME
        - LANCOMPUTE_DB_USER
        - LANCOMPUTE_DB_PASSWORD
        """
        if psycopg2 is None:
            raise ImportError("psycopg2 is required for PostgreSQL support")

        self.host = host or os.environ.get("LANCOMPUTE_DB_HOST", "192.168.1.134")
        self.port = port or int(os.environ.get("LANCOMPUTE_DB_PORT", "5432"))
        self.database = database or os.environ.get("LANCOMPUTE_DB_NAME", "postgres")
        self.user = user or os.environ.get("LANCOMPUTE_DB_USER", "mmarinucci@numinate.com")
        self.password = password or os.environ.get("LANCOMPUTE_DB_PASSWORD", "")
        self._conn = None

    def connect(self) -> None:
        """Establish database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.database,
                user=self.user,
                password=self.password,
            )
            self._conn.autocommit = False
            logger.info(f"Connected to PostgreSQL at {self.host}:{self.port}")

    def close(self) -> None:
        """Close database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()
            logger.info("Database connection closed")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _cursor(self):
        """Get a cursor with dict factory."""
        self.connect()
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Job operations

    def create_job(
        self,
        name: str,
        entrypoint: str,
        job_type: str = "batch",
        project_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        requirements: Optional[Dict[str, Any]] = None,
        priority: str = "normal",
        gpu_required: bool = False,
    ) -> Job:
        """Create a new job and add to queue."""
        job_id = str(uuid.uuid4())
        log_path = f"/mnt/tank/scripts/logs/jobs/{job_id}.log"

        # Add GPU requirement if specified
        if requirements is None:
            requirements = {}
        if gpu_required:
            requirements["gpu"] = True

        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO lancompute.jobs
                    (id, name, type, project_id, entrypoint, params, requirements, priority, log_path)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    job_id,
                    name,
                    job_type,
                    project_id,
                    entrypoint,
                    psycopg2.extras.Json(params or {}),
                    psycopg2.extras.Json(requirements),
                    priority,
                    log_path,
                ),
            )
            row = cur.fetchone()
            self._conn.commit()
            logger.info(f"Created job {job_id}: {name}")
            return Job.from_row(row)

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID."""
        # Validate UUID format before querying
        try:
            uuid.UUID(job_id)
        except ValueError:
            return None  # Not a valid UUID

        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM lancompute.jobs WHERE id = %s",
                (job_id,),
            )
            row = cur.fetchone()
            return Job.from_row(row) if row else None

    def get_job_by_name(self, name: str) -> Optional[Job]:
        """Get most recent job by name."""
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT * FROM lancompute.jobs
                WHERE name = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (name,),
            )
            row = cur.fetchone()
            return Job.from_row(row) if row else None

    def list_jobs(
        self,
        state: Optional[str] = None,
        worker_id: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Job]:
        """List jobs with optional filters."""
        conditions = []
        params = []

        if state:
            conditions.append("state = %s")
            params.append(state)
        if worker_id:
            conditions.append("worker_id = %s")
            params.append(worker_id)
        if project_id:
            conditions.append("project_id = %s")
            params.append(project_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        with self._cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM lancompute.jobs
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                params,
            )
            return [Job.from_row(row) for row in cur.fetchall()]

    def update_job_state(
        self,
        job_id: str,
        state: str,
        worker_id: Optional[str] = None,
        progress: Optional[float] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> bool:
        """Update job state and related fields."""
        updates = ["state = %s"]
        params = [state]

        if worker_id is not None:
            updates.append("worker_id = %s")
            params.append(worker_id)

        if progress is not None:
            updates.append("progress = %s")
            params.append(progress)

        if result is not None:
            updates.append("result = %s")
            params.append(psycopg2.extras.Json(result))

        if error is not None:
            updates.append("error = %s")
            params.append(error)

        # Update timestamps based on state
        if state == JobState.RUNNING.value:
            updates.append("started_at = NOW()")
        elif state in (JobState.SUCCEEDED.value, JobState.FAILED.value, JobState.CANCELLED.value):
            updates.append("completed_at = NOW()")

        params.append(job_id)

        with self._cursor() as cur:
            cur.execute(
                f"""
                UPDATE lancompute.jobs
                SET {', '.join(updates)}
                WHERE id = %s
                """,
                params,
            )
            self._conn.commit()
            return cur.rowcount > 0

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a pending or running job."""
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE lancompute.jobs
                SET state = %s, completed_at = NOW()
                WHERE id = %s AND state IN (%s, %s, %s, %s)
                """,
                (
                    JobState.CANCELLED.value,
                    job_id,
                    JobState.PENDING.value,
                    JobState.QUEUED.value,
                    JobState.ASSIGNED.value,
                    JobState.RUNNING.value,
                ),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def get_next_pending_job(self, worker: Worker) -> Optional[Job]:
        """Get next pending job that matches worker capabilities."""
        # For MVP, simple FIFO with priority ordering
        # TODO: Add capability matching
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT * FROM lancompute.jobs
                WHERE state = %s
                ORDER BY
                    CASE priority
                        WHEN 'high' THEN 1
                        WHEN 'normal' THEN 2
                        WHEN 'low' THEN 3
                    END,
                    created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                (JobState.PENDING.value,),
            )
            row = cur.fetchone()
            if row:
                # Assign to worker
                cur.execute(
                    """
                    UPDATE lancompute.jobs
                    SET state = %s, worker_id = %s
                    WHERE id = %s
                    """,
                    (JobState.ASSIGNED.value, worker.id, row["id"]),
                )
                self._conn.commit()
                return Job.from_row(row)
            return None

    # Worker operations

    def register_worker(
        self,
        worker_id: str,
        hostname: str,
        address: str,
        port: int = 8080,
        tags: Optional[List[str]] = None,
        capabilities: Optional[Dict[str, Any]] = None,
    ) -> Worker:
        """Register or update a worker."""
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO lancompute.workers
                    (id, hostname, address, port, tags, capabilities, status, last_heartbeat)
                VALUES
                    (%s, %s, %s, %s, %s, %s, 'online', NOW())
                ON CONFLICT (id) DO UPDATE SET
                    hostname = EXCLUDED.hostname,
                    address = EXCLUDED.address,
                    port = EXCLUDED.port,
                    tags = EXCLUDED.tags,
                    capabilities = EXCLUDED.capabilities,
                    status = 'online',
                    last_heartbeat = NOW()
                RETURNING *
                """,
                (
                    worker_id,
                    hostname,
                    address,
                    port,
                    tags or [],
                    psycopg2.extras.Json(capabilities or {}),
                ),
            )
            row = cur.fetchone()
            self._conn.commit()
            logger.info(f"Registered worker {worker_id} at {address}:{port}")
            return Worker.from_row(row)

    def update_worker_heartbeat(self, worker_id: str) -> bool:
        """Update worker heartbeat timestamp."""
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE lancompute.workers
                SET last_heartbeat = NOW(), status = 'online'
                WHERE id = %s
                """,
                (worker_id,),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def get_worker(self, worker_id: str) -> Optional[Worker]:
        """Get worker by ID."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM lancompute.workers WHERE id = %s",
                (worker_id,),
            )
            row = cur.fetchone()
            return Worker.from_row(row) if row else None

    def list_workers(self, status: Optional[str] = None) -> List[Worker]:
        """List all workers with optional status filter."""
        with self._cursor() as cur:
            if status:
                cur.execute(
                    "SELECT * FROM lancompute.workers WHERE status = %s ORDER BY hostname",
                    (status,),
                )
            else:
                cur.execute("SELECT * FROM lancompute.workers ORDER BY hostname")
            return [Worker.from_row(row) for row in cur.fetchall()]

    def mark_offline_workers(self, timeout_seconds: int = 60) -> int:
        """Mark workers as offline if heartbeat is stale."""
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE lancompute.workers
                SET status = 'offline'
                WHERE status = 'online'
                AND last_heartbeat < NOW() - INTERVAL '%s seconds'
                """,
                (timeout_seconds,),
            )
            self._conn.commit()
            return cur.rowcount

    # Job logs

    def add_job_log(self, job_id: str, message: str, level: str = "INFO") -> None:
        """Add a log entry for a job."""
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO lancompute.job_logs (job_id, level, message)
                VALUES (%s, %s, %s)
                """,
                (job_id, level, message),
            )
            self._conn.commit()

    def get_job_logs(self, job_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get log entries for a job."""
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT timestamp, level, message
                FROM lancompute.job_logs
                WHERE job_id = %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (job_id, limit),
            )
            return [dict(row) for row in cur.fetchall()]

    # Statistics

    def get_stats(self) -> Dict[str, Any]:
        """Get job queue statistics."""
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE state = 'pending') AS pending,
                    COUNT(*) FILTER (WHERE state = 'running') AS running,
                    COUNT(*) FILTER (WHERE state = 'succeeded') AS succeeded,
                    COUNT(*) FILTER (WHERE state = 'failed') AS failed,
                    COUNT(*) FILTER (WHERE state = 'cancelled') AS cancelled,
                    COUNT(*) AS total
                FROM lancompute.jobs
                """
            )
            jobs_row = cur.fetchone()

            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'online') AS online,
                    COUNT(*) FILTER (WHERE status = 'offline') AS offline,
                    COUNT(*) AS total
                FROM lancompute.workers
                """
            )
            workers_row = cur.fetchone()

            return {
                "jobs": dict(jobs_row),
                "workers": dict(workers_row),
            }
