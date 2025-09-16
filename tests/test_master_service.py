"""Tests for master_service module."""
import pytest
from unittest.mock import patch, MagicMock
import json
import time
from src.lancompute.master_service import (
    TaskStatus, NodeStatus, Task, Node, TaskQueue, NodeManager, MasterService
)


class TestTask:
    """Test cases for Task class."""
    
    def test_task_creation(self):
        """Test task creation with default values."""
        task = Task(
            id="test-123",
            type="compute",
            payload={"data": "test"}
        )
        assert task.id == "test-123"
        assert task.type == "compute"
        assert task.status == TaskStatus.PENDING
        assert task.priority == 0  # Default priority
    
    def test_task_with_priority(self):
        """Test task creation with custom priority."""
        task = Task(
            id="test-123",
            type="compute",
            payload={"data": "test"},
            priority=10
        )
        assert task.priority == 10


class TestNode:
    """Test cases for Node class."""
    
    def test_node_creation(self):
        """Test node creation."""
        capabilities = {"cpu_cores": 4, "memory_gb": 8}
        node = Node(
            id="node-1",
            address="192.168.1.100",
            port=8080,
            capabilities=capabilities
        )
        assert node.id == "node-1"
        assert node.address == "192.168.1.100"
        assert node.capabilities == capabilities
        assert node.status == NodeStatus.ONLINE
        assert isinstance(node.current_tasks, set)


class TestTaskQueue:
    """Test cases for TaskQueue class."""
    
    def test_task_queue_add_task(self):
        """Test adding tasks to queue."""
        queue = TaskQueue()
        
        task1 = Task("task-1", "compute", {}, priority=1)
        task2 = Task("task-2", "compute", {}, priority=10)
        
        queue.add_task(task1)
        queue.add_task(task2)
        
        # Check tasks are stored
        assert "task-1" in queue.tasks
        assert "task-2" in queue.tasks
    
    def test_task_queue_get_task(self):
        """Test getting task from queue."""
        queue = TaskQueue()

        # Test getting task by ID from empty queue
        result = queue.get_task("nonexistent-task")
        assert result is None

        # Add a task and get it by ID
        task = Task("task-1", "compute", {})
        queue.add_task(task)

        retrieved_task = queue.get_task("task-1")
        assert retrieved_task is not None
        assert retrieved_task.id == "task-1"


class TestNodeManager:
    """Test cases for NodeManager class."""
    
    def test_node_registration(self):
        """Test node registration."""
        manager = NodeManager()
        
        node_data = {
            "id": "node-1",
            "address": "192.168.1.100",
            "port": 8080,
            "capabilities": {"cpu_cores": 4}
        }
        
        node = manager.register_node(node_data)
        
        assert node.id == "node-1"
        assert node.address == "192.168.1.100"
        assert "node-1" in manager.nodes
    
    def test_get_available_nodes(self):
        """Test getting available nodes."""
        manager = NodeManager()
        
        # Register nodes
        node_data1 = {
            "id": "node-1",
            "address": "192.168.1.100",
            "port": 8080,
            "capabilities": {"cpu_cores": 4}
        }
        node_data2 = {
            "id": "node-2",
            "address": "192.168.1.101",
            "port": 8080,
            "capabilities": {"cpu_cores": 8}
        }
        
        manager.register_node(node_data1)
        manager.register_node(node_data2)
        
        available = manager.get_available_nodes()
        assert len(available) == 2
        assert all(node.status == NodeStatus.ONLINE for node in available)
    
    def test_heartbeat_update(self):
        """Test heartbeat update."""
        manager = NodeManager()
        
        node_data = {
            "id": "node-1",
            "address": "192.168.1.100",
            "port": 8080,
            "capabilities": {"cpu_cores": 4}
        }
        
        manager.register_node(node_data)
        
        # Update heartbeat
        result = manager.update_heartbeat("node-1")
        assert result is True
        
        # Try non-existent node
        result = manager.update_heartbeat("non-existent")
        assert result is False


class TestMasterService:
    """Test cases for MasterService class."""
    
    def test_master_service_initialization(self):
        """Test master service initialization."""
        master = MasterService(host="localhost", port=8080)
        
        assert master.host == "localhost"
        assert master.port == 8080
        assert master.task_queue is not None
        assert master.node_manager is not None
        assert master.scheduler is not None
