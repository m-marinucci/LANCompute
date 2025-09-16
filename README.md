# LANCompute - Distributed Computing Platform for Local Networks

LANCompute is a distributed computing platform that enables you to leverage all available compute resources across your local area network (LAN). It features specialized support for macOS unified memory architecture and heterogeneous compute environments.

## Features

- **Automatic Node Discovery**: Finds available compute resources on your LAN
- **Heterogeneous Computing**: Supports mixed architectures (Apple Silicon, x86, ARM)
- **Unified Memory Optimization**: Special optimizations for Apple Silicon Macs
- **Task Distribution**: Intelligent task scheduling based on node capabilities
- **Platform Detection**: Automatic detection of hardware capabilities
- **Fault Tolerance**: Handles node failures gracefully
- **REST API**: Simple HTTP API for task submission and monitoring

## Architecture

LANCompute uses a master-worker architecture:

- **Master Service**: Central coordinator for task distribution and node management
- **Worker Services**: Execute tasks on compute nodes
- **Task Queue**: Priority-based queue with requirement matching
- **Node Manager**: Tracks node health and capabilities

### Specialized Agents

The system includes AI agent personas for different aspects:
- `distributed-systems-architect`: Overall system design
- `task-scheduler`: Task distribution algorithms
- `node-manager`: Node lifecycle management
- `protocol-designer`: Communication protocols
- `compute-optimizer`: Performance optimization

## Quick Start

### 1. Start the Master Service

```bash
python master_service.py --port 8080
```

### 2. Start Worker Services

On each compute node:

```bash
python worker_service.py --master-url http://<master-ip>:8080
```

### 3. Submit a Task

```bash
curl -X POST http://localhost:8080/task \
  -H "Content-Type: application/json" \
  -d '{
    "type": "compute",
    "payload": {"operation": "matrix_multiply", "size": 1000},
    "priority": 10,
    "requirements": {"min_memory_gb": 4}
  }'
```

## Platform-Specific Features

### macOS Unified Memory

On Apple Silicon Macs, LANCompute automatically:
- Detects unified memory architecture
- Optimizes for zero-copy data sharing
- Utilizes performance and efficiency cores
- Supports Metal compute shaders
- Leverages Neural Engine when available

Run the optimizer to see your system capabilities:

```bash
python mac_optimizer.py
```

### x86 Architecture

For Intel-based systems:
- AVX instruction set utilization
- NUMA awareness
- Discrete GPU support
- Traditional memory hierarchy optimization

## API Reference

### Master Service Endpoints

- `GET /status` - Service status
- `GET /tasks` - List all tasks
- `GET /nodes` - List all nodes
- `GET /task/{id}` - Get task details
- `POST /task` - Submit new task
- `POST /node/register` - Register node
- `POST /node/heartbeat` - Node heartbeat
- `POST /task/update` - Update task status

### Task Types

1. **compute** - General computation tasks
2. **data_processing** - Data transformation tasks
3. **ml_inference** - Machine learning inference
4. **test** - Testing and benchmarking

## Configuration

Edit `config.yaml` to customize:
- Network settings
- Security options
- Resource limits
- Task priorities
- Platform-specific optimizations

## Requirements

- Python 3.7+
- psutil
- requests

Optional for enhanced features:
- numpy (for numerical computations)
- PyTorch/TensorFlow (for ML tasks)

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd LANCompute

# Install dependencies
pip install psutil requests

# Start services
python master_service.py &
python worker_service.py --master-url http://localhost:8080
```

## Development

The project includes comprehensive agent documentation in `.claude/agents/` for AI-assisted development. Each agent specializes in different aspects of distributed systems.

## Examples

### Find LLM Services on Network

```bash
python network_scanner.py
```

### Submit High-Priority ML Task

```python
import requests

task = {
    "type": "ml_inference",
    "payload": {"model": "sentiment_analysis", "text": "Great product!"},
    "priority": 50,
    "requirements": {
        "gpu_available": True,
        "min_memory_gb": 8
    }
}

response = requests.post("http://localhost:8080/task", json=task)
print(f"Task ID: {response.json()['task_id']}")
```

### Monitor Cluster Status

```python
import requests

# Get all nodes
nodes = requests.get("http://localhost:8080/nodes").json()
for node in nodes['nodes']:
    print(f"Node {node['id']}: {node['status']} - "
          f"{len(node['current_tasks'])} tasks")

# Get task summary
tasks = requests.get("http://localhost:8080/tasks").json()
status_counts = {}
for task in tasks['tasks']:
    status = task['status']
    status_counts[status] = status_counts.get(status, 0) + 1
print(f"Task summary: {status_counts}")
```

## Troubleshooting

### Worker Not Connecting
- Check firewall settings
- Verify master URL is correct
- Ensure master service is running

### Tasks Not Executing
- Check node capabilities match requirements
- Verify worker has available capacity
- Check logs for errors

### Performance Issues
- Adjust `max_concurrent_tasks` in worker
- Tune thread/process pool size
- Check network bandwidth

## Contributing

See agent documentation for architecture guidelines:
- `.claude/agents/distributed-systems-architect.md`
- `.claude/agents/protocol-designer.md`
- `.claude/agents/compute-optimizer.md`

## License

[Add your license here]

## Roadmap

- [ ] GPU compute support (CUDA, Metal)
- [ ] Distributed storage system
- [ ] Web dashboard
- [ ] Container-based task execution
- [ ] Multi-language task support
- [ ] Advanced scheduling algorithms