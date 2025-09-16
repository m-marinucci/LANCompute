#!/usr/bin/env python3
"""
Master Service for LANCompute Distributed Computing Platform
Central coordinator for task distribution and node management
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, asdict
from enum import Enum
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from queue import Queue, PriorityQueue
import signal
import sys


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task execution status"""
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeStatus(Enum):
    """Node availability status"""
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    MAINTENANCE = "maintenance"


@dataclass
class Task:
    """Represents a computational task"""
    id: str
    type: str
    payload: Dict[str, Any]
    priority: int = 0
    requirements: Dict[str, Any] = None
    status: TaskStatus = TaskStatus.PENDING
    assigned_node: Optional[str] = None
    created_at: float = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.requirements is None:
            self.requirements = {}
    
    def __lt__(self, other):
        """For priority queue comparison"""
        return self.priority > other.priority


@dataclass
class Node:
    """Represents a compute node"""
    id: str
    address: str
    port: int
    capabilities: Dict[str, Any]
    status: NodeStatus = NodeStatus.ONLINE
    last_heartbeat: float = None
    current_tasks: Set[str] = None
    total_completed: int = 0
    total_failed: int = 0
    
    def __post_init__(self):
        if self.last_heartbeat is None:
            self.last_heartbeat = time.time()
        if self.current_tasks is None:
            self.current_tasks = set()


class TaskQueue:
    """Priority-based task queue with requirements matching"""
    
    def __init__(self):
        self.queue = PriorityQueue()
        self.tasks: Dict[str, Task] = {}
        self.lock = threading.Lock()
    
    def add_task(self, task: Task) -> None:
        """Add a task to the queue"""
        with self.lock:
            self.tasks[task.id] = task
            self.queue.put(task)
            logger.info(f"Task {task.id} added to queue")
    
    def get_task_for_node(self, node: Node) -> Optional[Task]:
        """Get next suitable task for a node based on capabilities"""
        with self.lock:
            temp_tasks = []
            found_task = None
            
            while not self.queue.empty():
                task = self.queue.get()
                
                # Check if task still exists and is pending
                if task.id not in self.tasks or task.status != TaskStatus.PENDING:
                    continue
                
                # Check if node meets task requirements
                if self._node_meets_requirements(node, task):
                    found_task = task
                    break
                else:
                    temp_tasks.append(task)
            
            # Put back tasks that weren't suitable
            for task in temp_tasks:
                self.queue.put(task)
            
            if found_task:
                found_task.status = TaskStatus.ASSIGNED
                found_task.assigned_node = node.id
                logger.info(f"Task {found_task.id} assigned to node {node.id}")
            
            return found_task
    
    def _node_meets_requirements(self, node: Node, task: Task) -> bool:
        """Check if node capabilities meet task requirements"""
        for req_key, req_value in task.requirements.items():
            node_value = node.capabilities.get(req_key)
            
            if node_value is None:
                return False
            
            # Handle different requirement types
            if isinstance(req_value, (int, float)):
                if node_value < req_value:
                    return False
            elif isinstance(req_value, bool):
                if node_value != req_value:
                    return False
            elif isinstance(req_value, str):
                if node_value != req_value:
                    return False
            elif isinstance(req_value, list):
                if node_value not in req_value:
                    return False
        
        return True
    
    def update_task_status(self, task_id: str, status: TaskStatus, 
                          result: Any = None, error: str = None) -> bool:
        """Update task status"""
        with self.lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                task.status = status
                
                if status == TaskStatus.RUNNING:
                    task.started_at = time.time()
                elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                    task.completed_at = time.time()
                    task.result = result
                    task.error = error
                
                logger.info(f"Task {task_id} status updated to {status.value}")
                return True
            return False
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID"""
        with self.lock:
            return self.tasks.get(task_id)
    
    def get_all_tasks(self) -> List[Task]:
        """Get all tasks"""
        with self.lock:
            return list(self.tasks.values())


class NodeManager:
    """Manages compute nodes"""
    
    def __init__(self, heartbeat_timeout: float = 30.0):
        self.nodes: Dict[str, Node] = {}
        self.heartbeat_timeout = heartbeat_timeout
        self.lock = threading.Lock()
    
    def register_node(self, node_data: Dict[str, Any]) -> Node:
        """Register a new node or update existing"""
        with self.lock:
            node_id = node_data.get('id', str(uuid.uuid4()))
            
            if node_id in self.nodes:
                # Update existing node
                node = self.nodes[node_id]
                node.capabilities = node_data.get('capabilities', {})
                node.last_heartbeat = time.time()
                node.status = NodeStatus.ONLINE
            else:
                # Create new node
                node = Node(
                    id=node_id,
                    address=node_data['address'],
                    port=node_data['port'],
                    capabilities=node_data.get('capabilities', {}),
                    status=NodeStatus.ONLINE
                )
                self.nodes[node_id] = node
                logger.info(f"New node registered: {node_id}")
            
            return node
    
    def update_heartbeat(self, node_id: str) -> bool:
        """Update node heartbeat"""
        with self.lock:
            if node_id in self.nodes:
                self.nodes[node_id].last_heartbeat = time.time()
                self.nodes[node_id].status = NodeStatus.ONLINE
                return True
            return False
    
    def get_available_nodes(self) -> List[Node]:
        """Get list of available nodes"""
        with self.lock:
            current_time = time.time()
            available = []
            
            for node in self.nodes.values():
                # Check if node is responsive
                if current_time - node.last_heartbeat > self.heartbeat_timeout:
                    node.status = NodeStatus.OFFLINE
                
                # Node is available if online and not at capacity
                if node.status == NodeStatus.ONLINE and len(node.current_tasks) < 2:
                    available.append(node)
            
            return available
    
    def assign_task_to_node(self, node_id: str, task_id: str) -> bool:
        """Assign a task to a node"""
        with self.lock:
            if node_id in self.nodes:
                self.nodes[node_id].current_tasks.add(task_id)
                return True
            return False
    
    def complete_task_on_node(self, node_id: str, task_id: str, success: bool) -> bool:
        """Mark task as completed on node"""
        with self.lock:
            if node_id in self.nodes:
                node = self.nodes[node_id]
                node.current_tasks.discard(task_id)
                if success:
                    node.total_completed += 1
                else:
                    node.total_failed += 1
                return True
            return False
    
    def get_node(self, node_id: str) -> Optional[Node]:
        """Get node by ID"""
        with self.lock:
            return self.nodes.get(node_id)
    
    def get_all_nodes(self) -> List[Node]:
        """Get all nodes"""
        with self.lock:
            return list(self.nodes.values())


class MasterHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the master service"""
    
    def do_GET(self):
        """Handle GET requests"""
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/status':
            self._handle_status()
        elif parsed_path.path == '/tasks':
            self._handle_list_tasks()
        elif parsed_path.path == '/nodes':
            self._handle_list_nodes()
        elif parsed_path.path.startswith('/task/'):
            task_id = parsed_path.path.split('/')[-1]
            self._handle_get_task(task_id)
        else:
            self.send_error(404, "Not Found")
    
    def do_POST(self):
        """Handle POST requests"""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/task':
            self._handle_submit_task(data)
        elif parsed_path.path == '/node/register':
            self._handle_register_node(data)
        elif parsed_path.path == '/node/heartbeat':
            self._handle_heartbeat(data)
        elif parsed_path.path == '/task/update':
            self._handle_update_task(data)
        else:
            self.send_error(404, "Not Found")
    
    def _handle_status(self):
        """Get master service status"""
        status = {
            'status': 'running',
            'version': '1.0.0',
            'uptime': time.time() - self.server.master.start_time,
            'total_tasks': len(self.server.master.task_queue.tasks),
            'total_nodes': len(self.server.master.node_manager.nodes),
            'timestamp': datetime.utcnow().isoformat()
        }
        self._send_json_response(status)
    
    def _handle_list_tasks(self):
        """List all tasks"""
        tasks = self.server.master.task_queue.get_all_tasks()
        task_list = [asdict(task) for task in tasks]
        self._send_json_response({'tasks': task_list})
    
    def _handle_list_nodes(self):
        """List all nodes"""
        nodes = self.server.master.node_manager.get_all_nodes()
        node_list = []
        for node in nodes:
            node_dict = asdict(node)
            node_dict['current_tasks'] = list(node.current_tasks)
            node_list.append(node_dict)
        self._send_json_response({'nodes': node_list})
    
    def _handle_get_task(self, task_id: str):
        """Get specific task details"""
        task = self.server.master.task_queue.get_task(task_id)
        if task:
            self._send_json_response(asdict(task))
        else:
            self.send_error(404, "Task not found")
    
    def _handle_submit_task(self, data: Dict[str, Any]):
        """Submit a new task"""
        try:
            task = Task(
                id=str(uuid.uuid4()),
                type=data['type'],
                payload=data['payload'],
                priority=data.get('priority', 0),
                requirements=data.get('requirements', {})
            )
            self.server.master.task_queue.add_task(task)
            self.server.master.scheduler.notify()
            self._send_json_response({'task_id': task.id, 'status': 'submitted'})
        except KeyError as e:
            self.send_error(400, f"Missing required field: {e}")
    
    def _handle_register_node(self, data: Dict[str, Any]):
        """Register a new node"""
        try:
            node = self.server.master.node_manager.register_node(data)
            self._send_json_response({
                'node_id': node.id,
                'status': 'registered'
            })
        except KeyError as e:
            self.send_error(400, f"Missing required field: {e}")
    
    def _handle_heartbeat(self, data: Dict[str, Any]):
        """Handle node heartbeat"""
        node_id = data.get('node_id')
        if not node_id:
            self.send_error(400, "Missing node_id")
            return
        
        success = self.server.master.node_manager.update_heartbeat(node_id)
        if success:
            # Check for tasks for this node
            node = self.server.master.node_manager.get_node(node_id)
            if node and len(node.current_tasks) < 2:
                task = self.server.master.task_queue.get_task_for_node(node)
                if task:
                    self.server.master.node_manager.assign_task_to_node(node_id, task.id)
                    self._send_json_response({
                        'status': 'ok',
                        'task': asdict(task)
                    })
                    return
            
            self._send_json_response({'status': 'ok'})
        else:
            self.send_error(404, "Node not found")
    
    def _handle_update_task(self, data: Dict[str, Any]):
        """Update task status"""
        task_id = data.get('task_id')
        status = data.get('status')
        node_id = data.get('node_id')
        
        if not all([task_id, status]):
            self.send_error(400, "Missing required fields")
            return
        
        try:
            task_status = TaskStatus(status)
        except ValueError:
            self.send_error(400, f"Invalid status: {status}")
            return
        
        success = self.server.master.task_queue.update_task_status(
            task_id, 
            task_status,
            result=data.get('result'),
            error=data.get('error')
        )
        
        if success and node_id:
            # Update node statistics
            is_success = task_status == TaskStatus.COMPLETED
            self.server.master.node_manager.complete_task_on_node(
                node_id, task_id, is_success
            )
        
        if success:
            self._send_json_response({'status': 'updated'})
        else:
            self.send_error(404, "Task not found")
    
    def _send_json_response(self, data: Any):
        """Send JSON response"""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())
    
    def log_message(self, format, *args):
        """Override to use logger instead of stderr"""
        logger.info(f"{self.client_address[0]} - {format % args}")


class TaskScheduler:
    """Background task scheduler"""
    
    def __init__(self, master):
        self.master = master
        self.running = False
        self.thread = None
        self.condition = threading.Condition()
    
    def start(self):
        """Start the scheduler"""
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info("Task scheduler started")
    
    def stop(self):
        """Stop the scheduler"""
        self.running = False
        self.notify()
        if self.thread:
            self.thread.join()
        logger.info("Task scheduler stopped")
    
    def notify(self):
        """Notify scheduler of new work"""
        with self.condition:
            self.condition.notify()
    
    def _run(self):
        """Main scheduler loop"""
        while self.running:
            with self.condition:
                # Wait for notification or timeout
                self.condition.wait(timeout=5.0)
            
            if not self.running:
                break
            
            # Get available nodes
            available_nodes = self.master.node_manager.get_available_nodes()
            
            # Assign tasks to available nodes
            for node in available_nodes:
                if len(node.current_tasks) >= 2:
                    continue
                
                task = self.master.task_queue.get_task_for_node(node)
                if task:
                    self.master.node_manager.assign_task_to_node(node.id, task.id)
                    logger.info(f"Scheduled task {task.id} to node {node.id}")


class MasterService:
    """Main master service coordinator"""
    
    def __init__(self, host: str = '0.0.0.0', port: int = 8080):
        self.host = host
        self.port = port
        self.task_queue = TaskQueue()
        self.node_manager = NodeManager()
        self.scheduler = TaskScheduler(self)
        self.server = None
        self.start_time = time.time()
    
    def start(self):
        """Start the master service"""
        logger.info(f"Starting master service on {self.host}:{self.port}")
        
        # Start scheduler
        self.scheduler.start()
        
        # Start HTTP server
        self.server = HTTPServer((self.host, self.port), MasterHTTPHandler)
        self.server.master = self
        
        # Handle shutdown signals
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        
        logger.info(f"Master service listening on http://{self.host}:{self.port}")
        self.server.serve_forever()
    
    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signal"""
        logger.info("Shutting down master service...")
        self.scheduler.stop()
        if self.server:
            self.server.shutdown()
        sys.exit(0)


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='LANCompute Master Service')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8080, help='Port to listen on')
    parser.add_argument('--log-level', default='INFO', 
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='Logging level')
    
    args = parser.parse_args()
    
    # Configure logging
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    # Start master service
    master = MasterService(host=args.host, port=args.port)
    master.start()


if __name__ == "__main__":
    main()