"""Command-line interface for LANCompute Controller."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click

from .db import Database, Job, JobState
from .notifications import GotifyNotifier


def get_db() -> Database:
    """Get database connection with credentials from environment or keychain."""
    password = os.environ.get("LANCOMPUTE_DB_PASSWORD")

    # Try to get password from macOS keychain if not in environment
    if not password:
        try:
            import subprocess

            result = subprocess.run(
                ["security", "find-generic-password", "-s", "TrueNAS-PostgreSQL-Password", "-w"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                password = result.stdout.strip()
        except Exception:
            pass

    return Database(password=password)


def format_duration(start: Optional[datetime], end: Optional[datetime]) -> str:
    """Format duration between two timestamps."""
    if not start:
        return "-"
    end = end or datetime.now(start.tzinfo)
    delta = end - start
    seconds = delta.total_seconds()
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


@click.group()
@click.option("--debug/--no-debug", default=False, help="Enable debug output")
@click.pass_context
def cli(ctx: click.Context, debug: bool) -> None:
    """LANCompute Controller - Distributed job orchestration."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    if debug:
        import logging

        logging.basicConfig(level=logging.DEBUG)


@cli.command()
@click.option("--name", "-n", required=True, help="Job name")
@click.option("--script", "-s", required=True, help="Script or command to run")
@click.option("--project", "-p", help="Project ID")
@click.option("--gpu-required", is_flag=True, help="Require GPU worker")
@click.option("--priority", type=click.Choice(["low", "normal", "high"]), default="normal")
@click.option("--notify/--no-notify", default=True, help="Send Gotify notification on submit")
@click.option("--params", help="JSON parameters to pass to script")
def submit(
    name: str,
    script: str,
    project: Optional[str],
    gpu_required: bool,
    priority: str,
    notify: bool,
    params: Optional[str],
) -> None:
    """Submit a job to the queue."""
    params_dict = {}
    if params:
        try:
            params_dict = json.loads(params)
        except json.JSONDecodeError as e:
            click.echo(f"Error: Invalid JSON params: {e}", err=True)
            sys.exit(1)

    try:
        with get_db() as db:
            job = db.create_job(
                name=name,
                entrypoint=script,
                project_id=project,
                params=params_dict,
                priority=priority,
                gpu_required=gpu_required,
            )
            click.echo(f"Job '{name}' submitted (ID: {job.id})")

            if notify:
                notifier = GotifyNotifier()
                notifier.job_submitted(name, job.id)

    except Exception as e:
        click.echo(f"Error submitting job: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("job_identifier")
def status(job_identifier: str) -> None:
    """Check status of a job (by name or ID)."""
    try:
        with get_db() as db:
            # Try to find by ID first, then by name
            job = db.get_job(job_identifier)
            if not job:
                job = db.get_job_by_name(job_identifier)

            if not job:
                click.echo(f"Job not found: {job_identifier}", err=True)
                sys.exit(1)

            # Format output
            state_colors = {
                "pending": "yellow",
                "queued": "yellow",
                "assigned": "cyan",
                "running": "blue",
                "succeeded": "green",
                "failed": "red",
                "cancelled": "white",
            }
            state_color = state_colors.get(job.state, "white")

            click.echo(f"Job: {job.name}")
            click.echo(f"ID: {job.id}")
            click.secho(f"State: {job.state.upper()}", fg=state_color)
            if job.worker_id:
                click.echo(f"Worker: {job.worker_id}")
            click.echo(f"Priority: {job.priority}")
            if job.progress > 0:
                click.echo(f"Progress: {job.progress*100:.1f}%")
            click.echo(f"Created: {job.created_at}")
            if job.started_at:
                click.echo(f"Started: {job.started_at}")
                click.echo(f"Duration: {format_duration(job.started_at, job.completed_at)}")
            if job.completed_at:
                click.echo(f"Completed: {job.completed_at}")
            if job.error:
                click.secho(f"Error: {job.error}", fg="red")
            click.echo(f"Entrypoint: {job.entrypoint}")
            if job.log_path:
                click.echo(f"Log: {job.log_path}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("list")
@click.option("--state", "-s", help="Filter by state (pending, running, succeeded, failed)")
@click.option("--project", "-p", help="Filter by project ID")
@click.option("--limit", "-n", default=20, help="Number of jobs to show")
@click.option("--all", "show_all", is_flag=True, help="Show all jobs (ignore limit)")
def list_jobs(state: Optional[str], project: Optional[str], limit: int, show_all: bool) -> None:
    """List jobs in the queue."""
    try:
        with get_db() as db:
            jobs = db.list_jobs(
                state=state,
                project_id=project,
                limit=1000 if show_all else limit,
            )

            if not jobs:
                click.echo("No jobs found.")
                return

            # Table header
            click.echo(f"{'ID':<10} {'NAME':<25} {'STATE':<12} {'PRIORITY':<8} {'CREATED':<20}")
            click.echo("-" * 80)

            state_colors = {
                "pending": "yellow",
                "queued": "yellow",
                "assigned": "cyan",
                "running": "blue",
                "succeeded": "green",
                "failed": "red",
                "cancelled": "white",
            }

            for job in jobs:
                created = job.created_at.strftime("%Y-%m-%d %H:%M") if job.created_at else "-"
                state_color = state_colors.get(job.state, "white")
                job_id_short = job.id[:8] + "..."

                # Use click.echo with styling
                click.echo(
                    f"{job_id_short:<10} {job.name:<25} ",
                    nl=False,
                )
                click.secho(f"{job.state:<12}", fg=state_color, nl=False)
                click.echo(f" {job.priority:<8} {created}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("job_identifier")
def cancel(job_identifier: str) -> None:
    """Cancel a pending or running job."""
    try:
        with get_db() as db:
            # Try to find by ID first, then by name
            job = db.get_job(job_identifier)
            if not job:
                job = db.get_job_by_name(job_identifier)

            if not job:
                click.echo(f"Job not found: {job_identifier}", err=True)
                sys.exit(1)

            if job.state in (JobState.SUCCEEDED.value, JobState.FAILED.value, JobState.CANCELLED.value):
                click.echo(f"Job already in final state: {job.state}")
                sys.exit(1)

            if db.cancel_job(job.id):
                click.echo(f"Job '{job.name}' cancelled")
            else:
                click.echo(f"Failed to cancel job '{job.name}'", err=True)
                sys.exit(1)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("job_identifier")
@click.option("--lines", "-n", default=50, help="Number of log lines to show")
@click.option("--follow", "-f", is_flag=True, help="Follow log output (not implemented)")
def logs(job_identifier: str, lines: int, follow: bool) -> None:
    """View logs for a job."""
    try:
        with get_db() as db:
            # Try to find by ID first, then by name
            job = db.get_job(job_identifier)
            if not job:
                job = db.get_job_by_name(job_identifier)

            if not job:
                click.echo(f"Job not found: {job_identifier}", err=True)
                sys.exit(1)

            # Try database logs first
            log_entries = db.get_job_logs(job.id, limit=lines)

            if log_entries:
                click.echo(f"=== Logs for job '{job.name}' ===")
                for entry in reversed(log_entries):
                    ts = entry["timestamp"].strftime("%H:%M:%S") if entry.get("timestamp") else ""
                    level = entry.get("level", "INFO")
                    msg = entry.get("message", "")
                    click.echo(f"[{ts}] {level}: {msg}")
            elif job.log_path and Path(job.log_path).exists():
                # Fall back to log file
                click.echo(f"=== Log file: {job.log_path} ===")
                with open(job.log_path) as f:
                    # Read last N lines
                    all_lines = f.readlines()
                    for line in all_lines[-lines:]:
                        click.echo(line.rstrip())
            else:
                click.echo(f"No logs available for job '{job.name}'")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
def workers() -> None:
    """List registered workers."""
    try:
        with get_db() as db:
            workers = db.list_workers()

            if not workers:
                click.echo("No workers registered.")
                return

            click.echo(f"{'ID':<20} {'HOSTNAME':<20} {'ADDRESS':<18} {'STATUS':<10} {'COMPLETED':<10}")
            click.echo("-" * 85)

            status_colors = {
                "online": "green",
                "offline": "red",
                "busy": "yellow",
            }

            for w in workers:
                status_color = status_colors.get(w.status, "white")
                click.echo(f"{w.id:<20} {w.hostname:<20} {w.address}:{w.port:<8} ", nl=False)
                click.secho(f"{w.status:<10}", fg=status_color, nl=False)
                click.echo(f" {w.total_completed:<10}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
def stats() -> None:
    """Show job queue statistics."""
    try:
        with get_db() as db:
            stats = db.get_stats()

            jobs = stats["jobs"]
            workers = stats["workers"]

            click.echo("=== Job Statistics ===")
            click.echo(f"  Total:     {jobs['total']}")
            click.secho(f"  Pending:   {jobs['pending']}", fg="yellow")
            click.secho(f"  Running:   {jobs['running']}", fg="blue")
            click.secho(f"  Succeeded: {jobs['succeeded']}", fg="green")
            click.secho(f"  Failed:    {jobs['failed']}", fg="red")
            click.echo(f"  Cancelled: {jobs['cancelled']}")

            click.echo()
            click.echo("=== Worker Statistics ===")
            click.echo(f"  Total:   {workers['total']}")
            click.secho(f"  Online:  {workers['online']}", fg="green")
            click.secho(f"  Offline: {workers['offline']}", fg="red")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
def init_db(force: bool) -> None:
    """Initialize the database schema."""
    if not force:
        if not click.confirm("This will create the lancompute schema. Continue?"):
            return

    # Find the SQL schema file
    sql_file = Path(__file__).parent.parent.parent.parent / "sql" / "init_schema.sql"
    if not sql_file.exists():
        click.echo(f"Schema file not found: {sql_file}", err=True)
        sys.exit(1)

    try:
        with get_db() as db:
            with db._cursor() as cur:
                cur.execute(sql_file.read_text())
                db._conn.commit()
            click.echo("Database schema initialized successfully.")
    except Exception as e:
        click.echo(f"Error initializing database: {e}", err=True)
        sys.exit(1)


def main() -> None:
    """Entry point for CLI."""
    cli()


if __name__ == "__main__":
    main()
