"""Tests for worker_service module."""
import pytest
from unittest.mock import patch, MagicMock
from src.lancompute.worker_service import PlatformDetector, WorkerConfig, WorkerService


class TestPlatformDetector:
    """Test cases for PlatformDetector class."""
    
    def test_get_capabilities_basic(self):
        """Test basic capability detection."""
        with patch('psutil.cpu_count') as mock_cpu_count:
            with patch('psutil.virtual_memory') as mock_memory:
                mock_cpu_count.side_effect = [4, 8]  # logical=False, logical=True
                mock_memory.return_value.total = 8 * 1024 * 1024 * 1024  # 8GB
                mock_memory.return_value.available = 6 * 1024 * 1024 * 1024  # 6GB
                
                capabilities = PlatformDetector.get_capabilities()
                
                assert capabilities['cpu_count'] == 4
                assert capabilities['cpu_count_logical'] == 8
                assert capabilities['memory_gb'] == 8
                assert 'platform' in capabilities
    
    def test_check_package_available(self):
        """Test package availability check."""
        with patch('importlib.util.find_spec', return_value=MagicMock()):
            result = PlatformDetector._check_package('numpy')
            assert result is True
    
    def test_check_package_unavailable(self):
        """Test package unavailability check."""
        with patch('importlib.util.find_spec', return_value=None):
            result = PlatformDetector._check_package('nonexistent_package')
            assert result is False
    
    def test_detect_gpu_no_gpu(self):
        """Test GPU detection when no GPU present."""
        with patch('subprocess.run', side_effect=Exception("Command not found")):
            result = PlatformDetector._detect_gpu()
            assert result is False


class TestWorkerService:
    """Test cases for WorkerService class."""
    
    def test_worker_service_initialization(self):
        """Test worker service initialization."""
        config = WorkerConfig(
            master_url="http://localhost:8080",
            node_id="test-node"
        )
        
        with patch('src.lancompute.worker_service.PlatformDetector.get_capabilities') as mock_detect:
            mock_detect.return_value = {'cpu_count': 4, 'memory_gb': 8}
            
            worker = WorkerService(config)
            
            assert worker.config.master_url == "http://localhost:8080"
            assert worker.capabilities['cpu_count'] == 4
            assert worker.running is False
    
    @patch('requests.Session.post')
    def test_register_with_master(self, mock_post):
        """Test worker registration with master."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"status": "registered"}
        
        config = WorkerConfig(
            master_url="http://localhost:8080",
            node_id="test-node"
        )
        
        with patch('src.lancompute.worker_service.PlatformDetector.get_capabilities') as mock_detect:
            mock_detect.return_value = {'cpu_count': 4}
            
            worker = WorkerService(config)
            result = worker._register()
            
            assert result is True
            mock_post.assert_called_once()
    
    @patch('requests.Session.post')
    def test_register_failure(self, mock_post):
        """Test worker registration failure."""
        mock_post.return_value.status_code = 500
        
        config = WorkerConfig(
            master_url="http://localhost:8080",
            node_id="test-node"
        )
        
        with patch('src.lancompute.worker_service.PlatformDetector.get_capabilities') as mock_detect:
            mock_detect.return_value = {'cpu_count': 4}
            
            worker = WorkerService(config)
            result = worker._register()
            
            assert result is False
