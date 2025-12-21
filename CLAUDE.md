# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LANCompute is a distributed computing platform for local networks with specialized support for LLM workloads and macOS unified memory architecture. It uses a master-worker architecture where workers register with a central master service that distributes tasks based on node capabilities.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Master Service │◄────│  Worker Service │     │  Worker Service │
│   (coordinator) │────►│   (executor)    │     │   (executor)    │
│                 │     │                 │     │                 │
│  - TaskQueue    │     │  - TaskExecutor │     │  - TaskExecutor │
│  - NodeManager  │     │  - Platform     │     │  - Platform     │
│  - Scheduler    │     │    Detector     │     │    Detector     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### Core Modules

| Module | Purpose |
|--------|---------|
| `master_service.py` | HTTP server coordinating task distribution, node registration, heartbeats |
| `worker_service.py` | Executes tasks, reports capabilities, sends heartbeats to master |
| `network_scanner.py` | Discovers LLM services and screen sharing endpoints on LAN |
| `mdns_discovery.py` | mDNS/Bonjour discovery for macOS screen sharing services |
| `mac_optimizer.py` | Detects Apple Silicon capabilities (unified memory, GPU cores, Neural Engine) |

### Task Flow

1. Worker registers with master (`POST /node/register`) including capabilities
2. Worker sends heartbeats (`POST /node/heartbeat`); master may assign tasks in response
3. Worker executes task via `TaskExecutor`, reports status (`POST /task/update`)
4. Master's `TaskQueue` matches task requirements to node capabilities

## Development Commands

```bash
# Install with dev dependencies
uv pip install -e ".[dev,test]"

# Run all tests with coverage
uv run pytest

# Run single test file
uv run pytest tests/test_network_scanner.py -v

# Run single test
uv run pytest tests/test_network_scanner.py::test_scan_port_open_no_banner_returns_open -v

# Skip integration tests (faster)
uv run pytest -m "not integration"

# Type checking
uv run mypy src/

# Formatting
uv run black src/ tests/
uv run isort src/ tests/

# Linting
uv run flake8 src/ tests/

# Version management
uv run scripts/bump_version.py          # Show current version
uv run scripts/bump_version.py patch    # Bump patch version
```

### Running Services

```bash
# Network scanner - discover LLM services
python -m lancompute.network_scanner

# mDNS discovery for screen sharing
python -m lancompute.network_scanner --discover

# Diagnose connectivity to specific host
python -m lancompute.network_scanner --diagnose <hostname-or-ip>

# Master service
python -m lancompute.master_service --port 8080

# Worker service
python -m lancompute.worker_service --master-url http://localhost:8080

# macOS capabilities
python -m lancompute.mac_optimizer
```

## Key Implementation Details

### Master Service (master_service.py)

- `TaskQueue`: Priority queue with `_node_meets_requirements()` for capability matching
- `NodeManager`: Tracks node health via heartbeat timeout (default 30s)
- `TaskScheduler`: Background thread that assigns pending tasks to available nodes
- HTTP endpoints use `http.server.BaseHTTPRequestHandler` (no framework)

### Worker Service (worker_service.py)

- `PlatformDetector.get_capabilities()`: Returns dict with CPU, memory, GPU, package availability
- `TaskExecutor`: Uses ThreadPoolExecutor/ProcessPoolExecutor based on config
- Task types: `compute`, `data_processing`, `ml_inference`, `test`
- Heartbeat loop runs in background thread, handles task assignment responses

### Network Scanner (network_scanner.py)

- Default ports: 1234 (LMStudio), 11434 (Ollama), 7860 (Gradio), 5900 (VNC), 3283 (ARD)
- `scan_host()`: Ping check + port scan with banner grabbing
- `diagnose_host()`: Returns `DiagnosticReport` TypedDict with ping, port checks, recommendations
- `_identify_services()`: Classifies open ports as VNC, ARD, LMStudio, Ollama, Gradio

### mDNS Discovery (mdns_discovery.py)

- Uses `zeroconf` library to discover `_rfb._tcp.local.` and `_screensharing._tcp.local.`
- `ScreenSharingListener`: Collects discovered services in thread-safe list
- `discover_screen_sharing_services()`: Blocking call with configurable timeout

### macOS Optimizer (mac_optimizer.py)

- Detects Apple Silicon via `platform.machine() == "arm64"` or `sysctl hw.optional.arm64`
- Queries unified memory, P/E core counts, GPU cores, Neural Engine via `sysctl` and `system_profiler`
- `get_optimization_recommendations()`: Returns platform-specific tuning suggestions

## Dependencies

Core: `psutil`, `requests`, `pyyaml`, `zeroconf`

Version is defined in `src/lancompute/__init__.py` and read dynamically by hatchling.

## Controller Module

The `controller` module provides PostgreSQL-backed job orchestration for distributed compute:

### Core Components

| Module | Purpose |
|--------|---------|
| `controller/db.py` | PostgreSQL database operations for jobs and workers |
| `controller/cli.py` | Click-based CLI for job submission and monitoring |
| `controller/notifications.py` | Gotify push notification integration |
| `controller/worker_daemon.py` | Worker agent that polls and executes jobs |

### CLI Commands

```bash
# Install with controller dependencies
uv pip install -e ".[controller]"

# Initialize database schema (first time only)
lancompute init-db

# Submit a job
lancompute submit --name "my-job" --script "python train.py" --gpu-required

# Check job status
lancompute status my-job

# List jobs
lancompute list --state running

# View job logs
lancompute logs my-job

# Cancel a job
lancompute cancel my-job

# List workers
lancompute workers

# Show statistics
lancompute stats
```

### Worker Daemon

Run on GPU worker or Mac workers to execute jobs:

```bash
# Start worker daemon
lancompute-worker --id gpu-worker-01 --max-jobs 1
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LANCOMPUTE_DB_HOST` | 192.168.1.134 | PostgreSQL host |
| `LANCOMPUTE_DB_PORT` | 5432 | PostgreSQL port |
| `LANCOMPUTE_DB_NAME` | postgres | Database name |
| `LANCOMPUTE_DB_USER` | mmarinucci@numinate.com | Database user |
| `LANCOMPUTE_DB_PASSWORD` | - | Database password (or use keychain) |
| `GOTIFY_URL` | http://192.168.1.134:30215 | Gotify server URL |
| `GOTIFY_TOKEN` | - | Gotify app token for notifications |

### Database Schema

Schema is in `sql/init_schema.sql`. Tables:
- `lancompute.jobs` - Job queue with state machine
- `lancompute.workers` - Registered compute workers
- `lancompute.job_logs` - Execution log entries
- `lancompute.notifications` - Notification audit log

## Specifications

Feature and chore specs are in `specs/` directory:
- `feature-gpu-compute-support.md` - Planned CUDA/Metal GPU support
- `feature-screen-sharing-discovery.md` - Implemented mDNS discovery