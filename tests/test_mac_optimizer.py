"""Tests for mac_optimizer module."""
import pytest
from unittest.mock import patch, MagicMock
import platform
from src.lancompute.mac_optimizer import MacOptimizer


class TestMacOptimizer:
    """Test cases for MacOptimizer class."""
    
    def test_is_apple_silicon_true(self):
        """Test detection of Apple Silicon."""
        with patch('platform.system', return_value='Darwin'):
            with patch('platform.machine', return_value='arm64'):
                with patch.object(MacOptimizer, '_gather_system_info', return_value={}):
                    with patch.object(MacOptimizer, '_detect_unified_memory', return_value={}):
                        with patch.object(MacOptimizer, '_get_cpu_details', return_value={}):
                            with patch.object(MacOptimizer, '_get_gpu_details', return_value={}):
                                optimizer = MacOptimizer()
                                assert optimizer.is_apple_silicon is True
    
    def test_is_apple_silicon_false(self):
        """Test detection of Intel Mac."""
        with patch('platform.system', return_value='Darwin'):
            with patch('platform.machine', return_value='x86_64'):
                with patch.object(MacOptimizer, '_gather_system_info', return_value={}):
                    with patch.object(MacOptimizer, '_detect_unified_memory', return_value={}):
                        with patch.object(MacOptimizer, '_get_cpu_details', return_value={}):
                            with patch.object(MacOptimizer, '_get_gpu_details', return_value={}):
                                optimizer = MacOptimizer()
                                assert optimizer.is_apple_silicon is False
    
    def test_non_macos_system(self):
        """Test behavior on non-macOS system."""
        with patch('platform.system', return_value='Linux'):
            with patch.object(MacOptimizer, '_gather_system_info', return_value={}):
                with patch.object(MacOptimizer, '_detect_unified_memory', return_value={}):
                    with patch.object(MacOptimizer, '_get_cpu_details', return_value={}):
                        with patch.object(MacOptimizer, '_get_gpu_details', return_value={}):
                            optimizer = MacOptimizer()
                            assert optimizer.is_apple_silicon is False
    
    def test_get_optimization_recommendations(self):
        """Test optimization recommendations."""
        with patch.object(MacOptimizer, '_gather_system_info', return_value={}):
            with patch.object(MacOptimizer, '_detect_apple_silicon', return_value=True):
                with patch.object(MacOptimizer, '_detect_unified_memory', return_value={}):
                    with patch.object(MacOptimizer, '_get_cpu_details', return_value={}):
                        with patch.object(MacOptimizer, '_get_gpu_details', return_value={}):
                            optimizer = MacOptimizer()
                            optimizer.unified_memory_info = {'has_unified_memory': True, 'total_memory_gb': 16}
                            optimizer.cpu_info = {'logical_cores': 8}
                            optimizer.gpu_info = {'metal_support': True}
                            
                            recommendations = optimizer.get_optimization_recommendations()
                            
                            assert 'use_unified_memory' in recommendations
                            assert 'max_parallel_tasks' in recommendations
                            assert recommendations['max_parallel_tasks'] == 8
    
    def test_system_summary(self):
        """Test system summary generation."""
        with patch.object(MacOptimizer, '_gather_system_info', return_value={}):
            with patch.object(MacOptimizer, '_detect_apple_silicon', return_value=True):
                with patch.object(MacOptimizer, '_detect_unified_memory', return_value={}):
                    with patch.object(MacOptimizer, '_get_cpu_details', return_value={}):
                        with patch.object(MacOptimizer, '_get_gpu_details', return_value={}):
                            optimizer = MacOptimizer()
                            optimizer.system_info = {
                                'platform': 'Darwin',
                                'platform_version': '23.0.0',
                                'architecture': 'arm64'
                            }
                            optimizer.unified_memory_info = {
                                'total_memory_gb': 16,
                                'has_unified_memory': True,
                                'memory_bandwidth_gbps': 400.0,
                                'gpu_memory_gb': 16
                            }
                            optimizer.cpu_info = {
                                'logical_cores': 8,
                                'physical_cores': 8,
                                'performance_cores': 4,
                                'efficiency_cores': 4,
                                'cpu_frequency_ghz': 3.2
                            }
                            optimizer.gpu_info = {
                                'metal_support': True,
                                'gpu_cores': 8,
                                'neural_engine_cores': 16,
                                'gpu_family': 'Apple GPU',
                                'discrete_gpu': False
                            }

                            summary = optimizer.get_system_summary()
                            assert isinstance(summary, str)
                            assert len(summary) > 0
