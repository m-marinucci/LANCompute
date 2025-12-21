"""Command-line interface for LANCompute Benchmarks."""

import logging
import os
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click

from .cifar10 import run_cifar10_benchmark
from .db import BenchmarkDB
from ..controller.notifications import GotifyNotifier

logger = logging.getLogger(__name__)


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


def get_db() -> BenchmarkDB:
    """Get database connection."""
    return BenchmarkDB(password=get_db_password())


def get_worker_id() -> str:
    """Get worker ID from environment or hostname."""
    return os.environ.get("LANCOMPUTE_WORKER_ID", f"{socket.gethostname()}-worker")


@click.group()
@click.option("--debug/--no-debug", default=False, help="Enable debug output")
def cli(debug: bool) -> None:
    """LANCompute Benchmark - GPU performance regression testing."""
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO, format="%(message)s")


@cli.command()
@click.option("--epochs", "-e", default=5, help="Number of training epochs")
@click.option("--batch-size", "-b", default=128, help="Batch size")
@click.option("--device", default="auto", help="Device (cuda, mps, cpu, auto)")
@click.option("--worker-id", help="Worker ID (default: hostname-worker)")
@click.option("--set-baseline", is_flag=True, help="Set this run as the new baseline")
@click.option("--threshold", default=10.0, help="Regression threshold percentage")
@click.option("--notify/--no-notify", default=True, help="Send notifications")
def run(
    epochs: int,
    batch_size: int,
    device: str,
    worker_id: Optional[str],
    set_baseline: bool,
    threshold: float,
    notify: bool,
) -> None:
    """Run CIFAR-10 benchmark and store results."""
    worker_id = worker_id or get_worker_id()
    notifier = GotifyNotifier() if notify else None

    click.echo(f"Starting CIFAR-10 benchmark on worker: {worker_id}")
    click.echo(f"Configuration: epochs={epochs}, batch_size={batch_size}, device={device}")

    try:
        # Import torch to check availability
        import torch
    except ImportError:
        click.echo("Error: PyTorch not installed. Install with: uv pip install torch torchvision", err=True)
        sys.exit(1)

    try:
        with get_db() as db:
            # Get GPU info first
            from .cifar10 import get_gpu_info
            gpu_info = get_gpu_info()

            # Start benchmark run in DB
            run_id = db.start_benchmark_run(
                worker_id=worker_id,
                benchmark_type="cifar10",
                gpu_info=gpu_info,
            )
            click.echo(f"Benchmark run ID: {run_id}")

            try:
                # Run benchmark
                result = run_cifar10_benchmark(
                    epochs=epochs,
                    batch_size=batch_size,
                    device=device,
                )

                # Store results
                db.complete_benchmark_run(
                    run_id=run_id,
                    accuracy=result.accuracy,
                    samples_per_second=result.samples_per_second,
                    training_time_seconds=result.training_time_seconds,
                    epochs=result.epochs,
                    batch_size=result.batch_size,
                    results=result.details,
                )

                # Check for regression
                is_regression = db.check_regression(run_id, threshold)
                run_record = db.get_run(run_id)

                # Display results
                click.echo("\n" + "=" * 50)
                click.secho("BENCHMARK RESULTS", fg="green", bold=True)
                click.echo("=" * 50)
                click.echo(f"GPU: {gpu_info.get('name', 'N/A')}")
                click.echo(f"CUDA: {gpu_info.get('cuda_version', 'N/A')}")
                click.echo("-" * 50)
                click.echo(f"Test Accuracy: {result.accuracy:.2f}%")
                click.echo(f"Throughput: {result.samples_per_second:.0f} samples/sec")
                click.echo(f"Training Time: {result.training_time_seconds:.1f}s")

                if run_record and run_record.baseline_accuracy:
                    click.echo("-" * 50)
                    click.echo(f"Baseline Accuracy: {run_record.baseline_accuracy:.2f}%")
                    click.echo(f"Baseline Throughput: {run_record.baseline_samples_per_second:.0f} samples/sec")
                    delta_acc = run_record.accuracy_delta_percent or 0
                    delta_thr = run_record.throughput_delta_percent or 0
                    acc_color = "red" if delta_acc < -threshold else "green" if delta_acc > 0 else "white"
                    thr_color = "red" if delta_thr < -threshold else "green" if delta_thr > 0 else "white"
                    click.secho(f"Accuracy Delta: {delta_acc:+.1f}%", fg=acc_color)
                    click.secho(f"Throughput Delta: {delta_thr:+.1f}%", fg=thr_color)

                if is_regression:
                    click.echo("-" * 50)
                    click.secho("REGRESSION DETECTED!", fg="red", bold=True)
                    if run_record and run_record.regression_reason:
                        click.echo(run_record.regression_reason)

                    if notifier:
                        notifier.send(
                            title="GPU Benchmark Regression",
                            message=f"Worker {worker_id}: {run_record.regression_reason if run_record else 'Performance degraded'}",
                            priority=8,
                        )
                else:
                    if notifier:
                        notifier.send(
                            title="GPU Benchmark Complete",
                            message=f"Worker {worker_id}: {result.accuracy:.1f}% accuracy, {result.samples_per_second:.0f} samples/sec",
                            priority=3,
                        )

                click.echo("=" * 50)

                # Set as baseline if requested
                if set_baseline:
                    db.set_baseline(
                        worker_id=worker_id,
                        accuracy=result.accuracy,
                        samples_per_second=result.samples_per_second,
                        run_id=run_id,
                        notes=f"Set from run {run_id} on {datetime.now().isoformat()}",
                    )
                    click.secho("Baseline updated.", fg="green")

            except Exception as e:
                db.fail_benchmark_run(run_id, str(e))
                if notifier:
                    notifier.send(
                        title="GPU Benchmark Failed",
                        message=f"Worker {worker_id}: {str(e)[:100]}",
                        priority=8,
                    )
                raise

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("list")
@click.option("--worker-id", help="Filter by worker ID")
@click.option("--limit", "-n", default=10, help="Number of results")
def list_runs(worker_id: Optional[str], limit: int) -> None:
    """List recent benchmark runs."""
    try:
        with get_db() as db:
            runs = db.get_latest_runs(worker_id=worker_id, limit=limit)

            if not runs:
                click.echo("No benchmark runs found.")
                return

            click.echo(f"{'ID':<6} {'WORKER':<20} {'STATUS':<10} {'ACCURACY':<10} {'THROUGHPUT':<12} {'REGR':<5} {'DATE':<12}")
            click.echo("-" * 85)

            for run in runs:
                date_str = run.started_at.strftime("%Y-%m-%d") if run.started_at else "-"
                acc_str = f"{run.accuracy:.1f}%" if run.accuracy else "-"
                thr_str = f"{run.samples_per_second:.0f}/s" if run.samples_per_second else "-"
                regr_str = "YES" if run.is_regression else "-"

                status_color = {
                    "completed": "green",
                    "failed": "red",
                    "running": "yellow",
                }.get(run.status, "white")

                click.echo(f"{run.id:<6} {run.worker_id[:20]:<20} ", nl=False)
                click.secho(f"{run.status:<10}", fg=status_color, nl=False)
                click.echo(f" {acc_str:<10} {thr_str:<12} ", nl=False)
                if run.is_regression:
                    click.secho(f"{regr_str:<5}", fg="red", nl=False)
                else:
                    click.echo(f"{regr_str:<5}", nl=False)
                click.echo(f" {date_str}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--worker-id", help="Filter by worker ID")
def stats(worker_id: Optional[str]) -> None:
    """Show benchmark statistics."""
    try:
        with get_db() as db:
            s = db.get_stats(worker_id=worker_id)

            click.echo("=== Benchmark Statistics ===")
            click.echo(f"  Completed: {s.get('completed', 0)}")
            click.echo(f"  Failed:    {s.get('failed', 0)}")
            click.echo(f"  Running:   {s.get('running', 0)}")
            click.secho(f"  Regressions: {s.get('regressions', 0)}", fg="red" if s.get('regressions', 0) > 0 else "white")
            click.echo()
            if s.get("avg_accuracy"):
                click.echo(f"  Avg Accuracy: {s['avg_accuracy']:.2f}%")
                click.echo(f"  Best Accuracy: {s.get('best_accuracy', 0):.2f}%")
                click.echo(f"  Avg Throughput: {s.get('avg_throughput', 0):.0f} samples/sec")
                click.echo(f"  Best Throughput: {s.get('best_throughput', 0):.0f} samples/sec")
            click.echo(f"  Workers: {s.get('worker_count', 0)}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("worker_id")
@click.option("--accuracy", "-a", type=float, help="Baseline accuracy percentage")
@click.option("--throughput", "-t", type=float, help="Baseline throughput (samples/sec)")
@click.option("--from-run", type=int, help="Set baseline from existing run ID")
def baseline(
    worker_id: str,
    accuracy: Optional[float],
    throughput: Optional[float],
    from_run: Optional[int],
) -> None:
    """Set or view baseline for a worker."""
    try:
        with get_db() as db:
            if from_run:
                # Set from existing run
                run = db.get_run(from_run)
                if not run:
                    click.echo(f"Run {from_run} not found.", err=True)
                    sys.exit(1)
                if run.status != "completed":
                    click.echo(f"Run {from_run} is not completed (status: {run.status}).", err=True)
                    sys.exit(1)

                db.set_baseline(
                    worker_id=worker_id,
                    accuracy=run.accuracy,
                    samples_per_second=run.samples_per_second,
                    run_id=from_run,
                    notes=f"Set from run {from_run}",
                )
                click.echo(f"Baseline set from run {from_run}:")
                click.echo(f"  Accuracy: {run.accuracy:.2f}%")
                click.echo(f"  Throughput: {run.samples_per_second:.0f} samples/sec")

            elif accuracy and throughput:
                # Set manually
                db.set_baseline(
                    worker_id=worker_id,
                    accuracy=accuracy,
                    samples_per_second=throughput,
                    notes="Set manually via CLI",
                )
                click.echo(f"Baseline set for {worker_id}:")
                click.echo(f"  Accuracy: {accuracy:.2f}%")
                click.echo(f"  Throughput: {throughput:.0f} samples/sec")

            else:
                # View current baseline
                bl = db.get_baseline(worker_id)
                if bl:
                    click.echo(f"Baseline for {worker_id}:")
                    click.echo(f"  Accuracy: {bl.accuracy:.2f}%")
                    click.echo(f"  Throughput: {bl.samples_per_second:.0f} samples/sec")
                    if bl.set_at:
                        click.echo(f"  Set at: {bl.set_at}")
                else:
                    click.echo(f"No baseline set for {worker_id}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--days", "-d", default=7, help="Look back period in days")
def regressions(days: int) -> None:
    """List recent regressions."""
    try:
        with get_db() as db:
            runs = db.get_regressions(days=days)

            if not runs:
                click.secho(f"No regressions in the last {days} days.", fg="green")
                return

            click.secho(f"Regressions in the last {days} days:", fg="red", bold=True)
            click.echo()

            for run in runs:
                date_str = run.started_at.strftime("%Y-%m-%d %H:%M") if run.started_at else "-"
                click.echo(f"Run #{run.id} - {date_str}")
                click.echo(f"  Worker: {run.worker_id}")
                click.echo(f"  Accuracy: {run.accuracy:.2f}% (delta: {run.accuracy_delta_percent:+.1f}%)")
                click.echo(f"  Throughput: {run.samples_per_second:.0f}/s (delta: {run.throughput_delta_percent:+.1f}%)")
                if run.regression_reason:
                    click.secho(f"  Reason: {run.regression_reason}", fg="red")
                click.echo()

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
def init_db(force: bool) -> None:
    """Initialize benchmark database schema."""
    if not force:
        if not click.confirm("This will create the benchmark schema. Continue?"):
            return

    sql_file = Path(__file__).parent.parent.parent.parent / "sql" / "benchmark_schema.sql"
    if not sql_file.exists():
        click.echo(f"Schema file not found: {sql_file}", err=True)
        sys.exit(1)

    try:
        with get_db() as db:
            with db._cursor() as cur:
                cur.execute(sql_file.read_text())
                db._conn.commit()
            click.echo("Benchmark schema initialized successfully.")
    except Exception as e:
        click.echo(f"Error initializing database: {e}", err=True)
        sys.exit(1)


def main() -> None:
    """Entry point for CLI."""
    cli()


if __name__ == "__main__":
    main()
