#!/usr/bin/env python3
"""
Worker Service for LANCompute Distributed Computing Platform
Executes tasks on compute nodes with platform-specific optimizations
"""

import asyncio
import json
import logging
import platform
import psutil
import requests
import signal
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from dataclasses import dataclass
from typing import Dict, Any, Optional, Callable
import os
import importlib.util

# Try to import mac_optimizer if on macOS
if platform.system() == 'Darwin':
    try:
        from mac_optimizer import MacOptimizer
    except ImportError:
        MacOptimizer = None
else:
    MacOptimizer = None


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class WorkerConfig:
    """Worker configuration"""
    node_id: str
    master_url: str
    max_concurrent_tasks: int = 2
    heartbeat_interval: float = 10.0
    executor_type: str = 'thread'  # 'thread' or 'process'
    max_workers: int = None


class PlatformDetector:
    """Detect platform capabilities"""
    
    @staticmethod
    def get_capabilities() -> Dict[str, Any]:
        """Get comprehensive platform capabilities"""
        capabilities = {
            'platform': platform.system(),
            'platform_version': platform.version(),
            'architecture': platform.machine(),
            'processor': platform.processor(),
            'python_version': platform.python_version(),
            'hostname': platform.node()
        }
        
        # CPU information
        capabilities['cpu_count'] = psutil.cpu_count(logical=False)
        capabilities['cpu_count_logical'] = psutil.cpu_count(logical=True)
        capabilities['cpu_freq_mhz'] = psutil.cpu_freq().current if psutil.cpu_freq() else 0
        
        # Memory information
        mem = psutil.virtual_memory()
        capabilities['memory_gb'] = mem.total / (1024**3)
        capabilities['memory_available_gb'] = mem.available / (1024**3)
        
        # macOS specific capabilities
        if platform.system() == 'Darwin' and MacOptimizer:
            try:
                optimizer = MacOptimizer()
                capabilities['apple_silicon'] = optimizer.is_apple_silicon
                capabilities['unified_memory'] = optimizer.unified_memory_info['has_unified_memory']
                capabilities['unified_memory_gb'] = optimizer.unified_memory_info['total_memory_gb']
                capabilities['gpu_cores'] = optimizer.gpu_info['gpu_cores']
                capabilities['metal_support'] = optimizer.gpu_info['metal_support']
                capabilities['neural_engine'] = optimizer.gpu_info['neural_engine_cores'] > 0
                
                # Core types for Apple Silicon
                if optimizer.is_apple_silicon:
                    capabilities['performance_cores'] = optimizer.cpu_info['performance_cores']
                    capabilities['efficiency_cores'] = optimizer.cpu_info['efficiency_cores']
            except Exception as e:
                logger.warning(f"Error getting macOS capabilities: {e}")
        
        # GPU detection for other platforms
        if platform.system() != 'Darwin':
            capabilities['gpu_available'] = PlatformDetector._detect_gpu()
        
        # Available Python packages for different workloads
        capabilities['numpy_available'] = PlatformDetector._check_package('numpy')
        capabilities['torch_available'] = PlatformDetector._check_package('torch')
        capabilities['tensorflow_available'] = PlatformDetector._check_package('tensorflow')
        
        return capabilities
    
    @staticmethod
    def _detect_gpu() -> bool:
        """Detect GPU availability on non-macOS systems"""
        # Check for NVIDIA GPU
        try:
            subprocess.run(['nvidia-smi'], capture_output=True, check=True)
            return True
        except:
            pass
        
        # Check for AMD GPU (Linux)
        if platform.system() == 'Linux':
            try:
                result = subprocess.run(['lspci'], capture_output=True, text=True)
                if 'VGA' in result.stdout and ('AMD' in result.stdout or 'ATI' in result.stdout):
                    return True
            except:
                pass
        
        return False
    
    @staticmethod
    def _check_package(package_name: str) -> bool:
        """Check if a Python package is available"""
        spec = importlib.util.find_spec(package_name)
        return spec is not None


class TaskExecutor:
    """Executes tasks with platform-specific optimizations"""
    
    def __init__(self, config: WorkerConfig, capabilities: Dict[str, Any]):
        self.config = config
        self.capabilities = capabilities
        self.executor = self._create_executor()
        self.running_tasks = {}
        self.lock = threading.Lock()
    
    def _create_executor(self):
        """Create appropriate executor based on configuration"""
        max_workers = self.config.max_workers
        if max_workers is None:
            max_workers = self.capabilities.get('cpu_count_logical', 4)
        
        if self.config.executor_type == 'process':
            return ProcessPoolExecutor(max_workers=max_workers)
        else:
            return ThreadPoolExecutor(max_workers=max_workers)
    
    def can_accept_task(self) -> bool:
        """Check if worker can accept more tasks"""
        with self.lock:
            return len(self.running_tasks) < self.config.max_concurrent_tasks
    
    def execute_task(self, task: Dict[str, Any]) -> None:
        """Execute a task asynchronously"""
        task_id = task['id']
        
        with self.lock:
            if task_id in self.running_tasks:
                logger.warning(f"Task {task_id} already running")
                return
            
            self.running_tasks[task_id] = {
                'task': task,
                'future': None,
                'start_time': time.time()
            }
        
        # Submit task to executor
        future = self.executor.submit(self._run_task, task)
        
        with self.lock:
            self.running_tasks[task_id]['future'] = future
        
        # Add callback for completion
        future.add_done_callback(lambda f: self._task_completed(task_id, f))
    
    def _run_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single task"""
        task_type = task.get('type', 'unknown')
        payload = task.get('payload', {})
        
        logger.info(f"Executing task {task['id']} of type {task_type}")
        
        try:
            # Route to appropriate handler based on task type
            if task_type == 'compute':
                result = self._handle_compute_task(payload)
            elif task_type == 'data_processing':
                result = self._handle_data_processing_task(payload)
            elif task_type == 'ml_inference':
                result = self._handle_ml_inference_task(payload)
            elif task_type == 'test':
                result = self._handle_test_task(payload)
            else:
                raise ValueError(f"Unknown task type: {task_type}")
            
            return {
                'status': 'completed',
                'result': result,
                'execution_time': time.time() - self.running_tasks[task['id']]['start_time']
            }
            
        except Exception as e:
            logger.error(f"Task {task['id']} failed: {e}")
            return {
                'status': 'failed',
                'error': str(e),
                'execution_time': time.time() - self.running_tasks[task['id']]['start_time']
            }
    
    def _handle_compute_task(self, payload: Dict[str, Any]) -> Any:
        """Handle generic compute tasks"""
        # Example: Matrix multiplication
        if 'operation' in payload:
            if payload['operation'] == 'matrix_multiply':
                # Simplified example
                size = payload.get('size', 100)
                import random
                result = sum(random.random() for _ in range(size * size))
                return {'result': result, 'size': size}
        
        return {'result': 'computed'}
    
    def _handle_data_processing_task(self, payload: Dict[str, Any]) -> Any:
        """Handle data processing tasks"""
        # Example: Process data with platform-specific optimizations
        data_size = payload.get('data_size', 1000)
        
        # Use unified memory optimization on Apple Silicon
        if self.capabilities.get('unified_memory'):
            return {'result': f'Processed {data_size} items using unified memory'}
        else:
            return {'result': f'Processed {data_size} items'}
    
    def _handle_ml_inference_task(self, payload: Dict[str, Any]) -> Any:
        """Handle ML inference tasks"""
        model_name = payload.get('model', 'unknown')
        
        # Check for ML framework availability
        if self.capabilities.get('torch_available'):
            return {'result': f'Inference completed using PyTorch for {model_name}'}
        elif self.capabilities.get('tensorflow_available'):
            return {'result': f'Inference completed using TensorFlow for {model_name}'}
        else:
            return {'result': f'Inference completed using CPU for {model_name}'}
    
    def _handle_test_task(self, payload: Dict[str, Any]) -> Any:
        """Handle test tasks"""
        duration = payload.get('duration', 1.0)
        time.sleep(duration)
        return {
            'result': 'test completed',
            'duration': duration,
            'node_id': self.config.node_id,
            'platform': self.capabilities.get('platform')
        }
    
    def _task_completed(self, task_id: str, future):
        """Handle task completion"""
        with self.lock:
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]
        
        try:
            result = future.result()
            logger.info(f"Task {task_id} completed with status: {result.get('status')}")
        except Exception as e:
            logger.error(f"Task {task_id} failed with exception: {e}")
    
    def shutdown(self):
        """Shutdown the executor"""
        self.executor.shutdown(wait=True)


class WorkerService:
    """Main worker service"""
    
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.capabilities = PlatformDetector.get_capabilities()
        self.executor = TaskExecutor(config, self.capabilities)
        self.running = False
        self.heartbeat_thread = None
        self.session = requests.Session()
    
    def start(self):
        """Start the worker service"""
        logger.info(f"Starting worker service with ID: {self.config.node_id}")
        logger.info(f"Platform: {self.capabilities.get('platform')} "
                   f"({self.capabilities.get('architecture')})")
        
        # Register with master
        if not self._register():
            logger.error("Failed to register with master")
            return
        
        self.running = True
        
        # Start heartbeat thread
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
        
        # Handle shutdown signals
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        
        logger.info("Worker service started successfully")
        
        # Keep main thread alive
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self._handle_shutdown(None, None)
    
    def _register(self) -> bool:
        """Register with master service"""
        try:
            # Get local IP address
            import socket
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            
            data = {
                'id': self.config.node_id,
                'address': local_ip,
                'port': 0,  # Not running a server
                'capabilities': self.capabilities
            }
            
            response = self.session.post(
                f"{self.config.master_url}/node/register",
                json=data,
                timeout=5
            )
            
            if response.status_code == 200:
                logger.info("Successfully registered with master")
                return True
            else:
                logger.error(f"Registration failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Registration error: {e}")
            return False
    
    def _heartbeat_loop(self):
        """Send periodic heartbeats to master"""
        consecutive_failures = 0
        
        while self.running:
            try:
                # Send heartbeat
                response = self.session.post(
                    f"{self.config.master_url}/node/heartbeat",
                    json={'node_id': self.config.node_id},
                    timeout=5
                )
                
                if response.status_code == 200:
                    consecutive_failures = 0
                    data = response.json()
                    
                    # Check if master assigned a task
                    if 'task' in data:
                        task = data['task']
                        if self.executor.can_accept_task():
                            self._accept_task(task)
                        else:
                            logger.warning("Cannot accept task - at capacity")
                else:
                    consecutive_failures += 1
                    logger.warning(f"Heartbeat failed: {response.status_code}")
                    
            except Exception as e:
                consecutive_failures += 1
                logger.error(f"Heartbeat error: {e}")
            
            # Back off on failures
            if consecutive_failures > 3:
                logger.error("Multiple heartbeat failures - backing off")
                time.sleep(30)
            else:
                time.sleep(self.config.heartbeat_interval)
    
    def _accept_task(self, task: Dict[str, Any]):
        """Accept and execute a task"""
        task_id = task['id']
        logger.info(f"Accepting task {task_id}")
        
        # Update task status to running
        self._update_task_status(task_id, 'running')
        
        # Execute task
        self.executor.execute_task(task)
        
        # Monitor task completion in background
        threading.Thread(
            target=self._monitor_task,
            args=(task_id,),
            daemon=True
        ).start()
    
    def _monitor_task(self, task_id: str):
        """Monitor task execution and report completion"""
        # Wait for task to complete
        while task_id in self.executor.running_tasks:
            time.sleep(1)
        
        # Task completed - need to get result from executor
        # In a real implementation, we'd store results properly
        self._update_task_status(task_id, 'completed', result={'status': 'done'})
    
    def _update_task_status(self, task_id: str, status: str, 
                           result: Any = None, error: str = None):
        """Update task status with master"""
        try:
            data = {
                'task_id': task_id,
                'status': status,
                'node_id': self.config.node_id
            }
            
            if result is not None:
                data['result'] = result
            if error is not None:
                data['error'] = error
            
            response = self.session.post(
                f"{self.config.master_url}/task/update",
                json=data,
                timeout=5
            )
            
            if response.status_code == 200:
                logger.info(f"Task {task_id} status updated to {status}")
            else:
                logger.error(f"Failed to update task status: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error updating task status: {e}")
    
    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signal"""
        logger.info("Shutting down worker service...")
        self.running = False
        self.executor.shutdown()
        sys.exit(0)


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='LANCompute Worker Service')
    parser.add_argument('--master-url', required=True, 
                       help='Master service URL (e.g., http://192.168.1.100:8080)')
    parser.add_argument('--node-id', default=None,
                       help='Unique node ID (auto-generated if not provided)')
    parser.add_argument('--max-tasks', type=int, default=2,
                       help='Maximum concurrent tasks')
    parser.add_argument('--heartbeat-interval', type=float, default=10.0,
                       help='Heartbeat interval in seconds')
    parser.add_argument('--executor', choices=['thread', 'process'], default='thread',
                       help='Executor type')
    parser.add_argument('--max-workers', type=int, default=None,
                       help='Maximum worker threads/processes')
    parser.add_argument('--log-level', default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='Logging level')
    
    args = parser.parse_args()
    
    # Configure logging
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    # Generate node ID if not provided
    if args.node_id is None:
        hostname = platform.node().split('.')[0]
        args.node_id = f"{hostname}-{uuid.uuid4().hex[:8]}"
    
    # Create configuration
    config = WorkerConfig(
        node_id=args.node_id,
        master_url=args.master_url.rstrip('/'),
        max_concurrent_tasks=args.max_tasks,
        heartbeat_interval=args.heartbeat_interval,
        executor_type=args.executor,
        max_workers=args.max_workers
    )
    
    # Start worker service
    worker = WorkerService(config)
    worker.start()


if __name__ == "__main__":
    main()