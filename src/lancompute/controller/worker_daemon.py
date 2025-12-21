#!/usr/bin/env python3
"""Worker daemon for LANCompute Controller.

This daemon runs on compute workers (e.g., GPU worker VM) and:
1. Registers with the controller database
2. Polls for pending jobs
3. Executes jobs and reports status
4. Sends heartbeats to maintain online status
"""

import argparse
import logging
import os
import platform
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .db import Database, Job, JobState, Worker
from .notifications import GotifyNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_hostname() -> str:
    """Get the current hostname."""
    return socket.gethostname()


def get_ip_address() -> str:
    """Get the primary IP address."""
    try:
        # Create a socket to determine the IP used for outbound connections
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def detect_capabilities() -> Dict[str, Any]:
    """Detect worker capabilities (CPU, memory, GPU)."""
    import psutil

    caps = {
        "platform": platform.system(),
        "architecture": platform.machine(),
        "cpu_count": psutil.cpu_count(),
        "memory_gb": round(psutil.virtual_memory().total / (1024**3), 1),
        "python_version": platform.python_version(),
    }

    # Check for NVIDIA GPU
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            gpus = []
            for line in lines:
                parts = line.split(",")
                if len(parts) >= 2:
                    gpus.append({
                        "name": parts[0].strip(),
                        "memory_mb": int(parts[1].strip()),
                    })
            if gpus:
                caps["gpu"] = True
                caps["gpus"] = gpus
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Check for Apple Silicon GPU
    if platform.machine() == "arm64" and platform.system() == "Darwin":
        caps["gpu"] = True
        caps["gpu_type"] = "apple_silicon"

    return caps


class WorkerDaemon:
    """Worker daemon that polls for and executes jobs."""

    def __init__(
        self,
        worker_id: str,
        db: Database,
        notifier: Optional[GotifyNotifier] = None,
        heartbeat_interval: int = 30,
        poll_interval: int = 5,
        max_concurrent_jobs: int = 1,
    ):
        self.worker_id = worker_id
        self.db = db
        self.notifier = notifier or GotifyNotifier()
        self.heartbeat_interval = heartbeat_interval
        self.poll_interval = poll_interval
        self.max_concurrent_jobs = max_concurrent_jobs

        self.hostname = get_hostname()
        self.address = get_ip_address()
        self.capabilities = detect_capabilities()

        self.running = False
        self.current_jobs: Dict[str, threading.Thread] = {}
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the worker daemon."""
        logger.info(f"Starting worker daemon: {self.worker_id}")
        logger.info(f"Hostname: {self.hostname}, Address: {self.address}")
        logger.info(f"Capabilities: {self.capabilities}")

        self.running = True

        # Register with database
        self._register()

        # Start heartbeat thread
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

        # Start job polling thread
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

        # Notify that worker is online
        self.notifier.worker_online(self.worker_id, self.hostname)

        logger.info("Worker daemon started")

    def stop(self) -> None:
        """Stop the worker daemon."""
        logger.info("Stopping worker daemon...")
        self.running = False

        # Wait for threads to finish
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)
        if self._poll_thread:
            self._poll_thread.join(timeout=5)

        # Wait for running jobs
        for job_id, thread in list(self.current_jobs.items()):
            logger.info(f"Waiting for job {job_id} to finish...")
            thread.join(timeout=30)

        logger.info("Worker daemon stopped")

    def _register(self) -> None:
        """Register worker with the database."""
        worker = self.db.register_worker(
            worker_id=self.worker_id,
            hostname=self.hostname,
            address=self.address,
            port=8080,
            tags=self._get_tags(),
            capabilities=self.capabilities,
        )
        logger.info(f"Registered as worker: {worker.id}")

    def _get_tags(self) -> list:
        """Get worker tags based on capabilities."""
        tags = []
        if self.capabilities.get("gpu"):
            tags.append("gpu")
            for gpu in self.capabilities.get("gpus", []):
                tags.append(f"gpu:{gpu['name'].lower().replace(' ', '-')}")
        if self.capabilities.get("platform"):
            tags.append(f"os:{self.capabilities['platform'].lower()}")
        return tags

    def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats."""
        while self.running:
            try:
                self.db.update_worker_heartbeat(self.worker_id)
                logger.debug("Heartbeat sent")
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")

            time.sleep(self.heartbeat_interval)

    def _poll_loop(self) -> None:
        """Poll for and execute jobs."""
        while self.running:
            try:
                with self._lock:
                    active_jobs = len(self.current_jobs)

                if active_jobs < self.max_concurrent_jobs:
                    self._check_for_jobs()

            except Exception as e:
                logger.error(f"Poll loop error: {e}")

            time.sleep(self.poll_interval)

    def _check_for_jobs(self) -> None:
        """Check for pending jobs and start execution."""
        worker = Worker(
            id=self.worker_id,
            hostname=self.hostname,
            address=self.address,
            capabilities=self.capabilities,
        )

        job = self.db.get_next_pending_job(worker)
        if job:
            logger.info(f"Starting job: {job.name} ({job.id})")
            self._start_job(job)

    def _start_job(self, job: Job) -> None:
        """Start executing a job in a separate thread."""
        thread = threading.Thread(
            target=self._execute_job,
            args=(job,),
            daemon=True,
        )

        with self._lock:
            self.current_jobs[job.id] = thread

        thread.start()

    def _execute_job(self, job: Job) -> None:
        """Execute a job and report results."""
        start_time = time.time()

        try:
            # Update state to running
            self.db.update_job_state(
                job.id,
                JobState.RUNNING.value,
                worker_id=self.worker_id,
            )

            # Notify job started
            self.notifier.job_started(job.name, self.worker_id)

            # Create log directory if needed
            if job.log_path:
                log_path = Path(job.log_path)
                log_path.parent.mkdir(parents=True, exist_ok=True)

            # Execute the entrypoint
            logger.info(f"Executing: {job.entrypoint}")
            self.db.add_job_log(job.id, f"Starting execution: {job.entrypoint}")

            # Prepare environment
            env = os.environ.copy()
            env["LANCOMPUTE_JOB_ID"] = job.id
            env["LANCOMPUTE_JOB_NAME"] = job.name
            if job.project_id:
                env["LANCOMPUTE_PROJECT_ID"] = job.project_id

            # Add params to environment as JSON
            if job.params:
                import json
                env["LANCOMPUTE_PARAMS"] = json.dumps(job.params)

            # Run the command
            with open(job.log_path, "w") if job.log_path else open(os.devnull, "w") as log_file:
                process = subprocess.Popen(
                    job.entrypoint,
                    shell=True,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=env,
                    cwd=f"/mnt/business/numinate/projects/{job.project_id}" if job.project_id else None,
                )

                # Wait for completion
                returncode = process.wait()

            duration = time.time() - start_time

            if returncode == 0:
                # Job succeeded
                self.db.update_job_state(
                    job.id,
                    JobState.SUCCEEDED.value,
                    progress=1.0,
                    result={"returncode": 0, "duration": duration},
                )
                self.db.add_job_log(job.id, f"Job completed successfully in {duration:.1f}s")
                self.notifier.job_completed(job.name, duration)
                logger.info(f"Job completed: {job.name}")
            else:
                # Job failed
                error_msg = f"Process exited with code {returncode}"
                self.db.update_job_state(
                    job.id,
                    JobState.FAILED.value,
                    error=error_msg,
                    result={"returncode": returncode, "duration": duration},
                )
                self.db.add_job_log(job.id, f"Job failed: {error_msg}", level="ERROR")
                self.notifier.job_failed(job.name, error_msg)
                logger.error(f"Job failed: {job.name} - {error_msg}")

        except Exception as e:
            # Unexpected error
            error_msg = str(e)
            self.db.update_job_state(
                job.id,
                JobState.FAILED.value,
                error=error_msg,
            )
            self.db.add_job_log(job.id, f"Job error: {error_msg}", level="ERROR")
            self.notifier.job_failed(job.name, error_msg)
            logger.exception(f"Job execution error: {job.name}")

        finally:
            # Remove from current jobs
            with self._lock:
                self.current_jobs.pop(job.id, None)


def get_db_password() -> str:
    """Get database password from environment or keychain."""
    password = os.environ.get("LANCOMPUTE_DB_PASSWORD")
    if not password:
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-s", "TrueNAS-PostgreSQL-Password", "-w"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                password = result.stdout.strip()
        except Exception:
            pass
    return password or ""


def main() -> None:
    """Main entry point for worker daemon."""
    parser = argparse.ArgumentParser(description="LANCompute Worker Daemon")
    parser.add_argument(
        "--id",
        default=None,
        help="Worker ID (default: hostname)",
    )
    parser.add_argument(
        "--heartbeat",
        type=int,
        default=30,
        help="Heartbeat interval in seconds",
    )
    parser.add_argument(
        "--poll",
        type=int,
        default=5,
        help="Job poll interval in seconds",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=1,
        help="Maximum concurrent jobs",
    )
    parser.add_argument(
        "--db-host",
        default="192.168.1.134",
        help="Database host",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    # Configure logging
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Determine worker ID
    worker_id = args.id or f"{get_hostname()}-worker"

    # Create database connection
    db = Database(
        host=args.db_host,
        password=get_db_password(),
    )

    # Create notifier
    notifier = GotifyNotifier()

    # Create and start daemon
    daemon = WorkerDaemon(
        worker_id=worker_id,
        db=db,
        notifier=notifier,
        heartbeat_interval=args.heartbeat,
        poll_interval=args.poll,
        max_concurrent_jobs=args.max_jobs,
    )

    # Handle shutdown signals
    def shutdown_handler(signum, frame):
        logger.info("Received shutdown signal")
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        daemon.start()
        # Keep main thread alive
        while daemon.running:
            time.sleep(1)
    except KeyboardInterrupt:
        daemon.stop()


if __name__ == "__main__":
    main()
