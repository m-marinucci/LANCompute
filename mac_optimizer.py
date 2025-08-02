#!/usr/bin/env python3
"""
macOS Optimization Module for LANCompute
Detects and utilizes unified memory architecture on Apple Silicon Macs
"""

import platform
import subprocess
import plistlib
import json
import re
from typing import Dict, Optional, Tuple, Any


class MacOptimizer:
    """Detects and optimizes for macOS-specific hardware features"""
    
    def __init__(self):
        self.system_info = self._gather_system_info()
        self.is_apple_silicon = self._detect_apple_silicon()
        self.unified_memory_info = self._detect_unified_memory()
        self.cpu_info = self._get_cpu_details()
        self.gpu_info = self._get_gpu_details()
    
    def _gather_system_info(self) -> Dict[str, Any]:
        """Gather basic system information"""
        info = {
            'platform': platform.system(),
            'platform_version': platform.version(),
            'architecture': platform.machine(),
            'processor': platform.processor(),
            'python_version': platform.python_version()
        }
        return info
    
    def _detect_apple_silicon(self) -> bool:
        """Check if running on Apple Silicon"""
        if platform.system() != 'Darwin':
            return False
        
        # Check processor type
        processor = platform.processor()
        if 'arm' in processor.lower():
            return True
        
        # Alternative check using sysctl
        try:
            result = subprocess.run(
                ['sysctl', '-n', 'hw.optional.arm64'],
                capture_output=True,
                text=True
            )
            return result.stdout.strip() == '1'
        except:
            return False
    
    def _detect_unified_memory(self) -> Dict[str, Any]:
        """Detect unified memory configuration on Apple Silicon"""
        memory_info = {
            'has_unified_memory': False,
            'total_memory_gb': 0,
            'memory_bandwidth_gbps': 0,
            'gpu_memory_gb': 0  # Same as total on unified architecture
        }
        
        if not self.is_apple_silicon:
            # Traditional memory architecture
            memory_info.update(self._get_traditional_memory_info())
            return memory_info
        
        # Get memory size
        try:
            # Total physical memory
            result = subprocess.run(
                ['sysctl', '-n', 'hw.memsize'],
                capture_output=True,
                text=True
            )
            total_bytes = int(result.stdout.strip())
            memory_info['total_memory_gb'] = total_bytes / (1024**3)
            memory_info['gpu_memory_gb'] = memory_info['total_memory_gb']  # Unified
            memory_info['has_unified_memory'] = True
            
            # Estimate bandwidth based on chip model
            chip_model = self._get_chip_model()
            memory_info['memory_bandwidth_gbps'] = self._estimate_memory_bandwidth(chip_model)
            
        except Exception as e:
            print(f"Error detecting unified memory: {e}")
        
        return memory_info
    
    def _get_traditional_memory_info(self) -> Dict[str, Any]:
        """Get memory info for Intel Macs"""
        info = {}
        try:
            # Get total memory
            result = subprocess.run(
                ['sysctl', '-n', 'hw.memsize'],
                capture_output=True,
                text=True
            )
            total_bytes = int(result.stdout.strip())
            info['total_memory_gb'] = total_bytes / (1024**3)
            
            # Try to detect discrete GPU memory (if available)
            info['gpu_memory_gb'] = self._detect_discrete_gpu_memory()
            
        except Exception as e:
            print(f"Error getting memory info: {e}")
        
        return info
    
    def _get_chip_model(self) -> str:
        """Identify the specific Apple Silicon chip model"""
        try:
            # Use system_profiler to get chip info
            result = subprocess.run(
                ['system_profiler', 'SPHardwareDataType', '-json'],
                capture_output=True,
                text=True
            )
            data = json.loads(result.stdout)
            hardware = data.get('SPHardwareDataType', [{}])[0]
            
            # Look for chip model in various fields
            chip_name = hardware.get('chip_type', '')
            if not chip_name:
                # Alternative field names
                chip_name = hardware.get('cpu_type', '')
                if not chip_name:
                    model_name = hardware.get('machine_model', '')
                    if 'M1' in model_name:
                        chip_name = 'Apple M1'
                    elif 'M2' in model_name:
                        chip_name = 'Apple M2'
                    elif 'M3' in model_name:
                        chip_name = 'Apple M3'
            
            return chip_name
            
        except Exception as e:
            print(f"Error detecting chip model: {e}")
            return "Unknown"
    
    def _estimate_memory_bandwidth(self, chip_model: str) -> float:
        """Estimate memory bandwidth based on chip model"""
        # Bandwidth estimates in GB/s
        bandwidth_map = {
            'Apple M1': 68.25,
            'Apple M1 Pro': 200.0,
            'Apple M1 Max': 400.0,
            'Apple M1 Ultra': 800.0,
            'Apple M2': 100.0,
            'Apple M2 Pro': 200.0,
            'Apple M2 Max': 400.0,
            'Apple M2 Ultra': 800.0,
            'Apple M3': 100.0,
            'Apple M3 Pro': 150.0,
            'Apple M3 Max': 400.0,
        }
        
        for chip, bandwidth in bandwidth_map.items():
            if chip in chip_model:
                return bandwidth
        
        return 100.0  # Default estimate
    
    def _get_cpu_details(self) -> Dict[str, Any]:
        """Get detailed CPU information"""
        cpu_info = {
            'physical_cores': 0,
            'logical_cores': 0,
            'performance_cores': 0,
            'efficiency_cores': 0,
            'cpu_frequency_ghz': 0.0
        }
        
        try:
            # Get core counts
            result = subprocess.run(
                ['sysctl', '-n', 'hw.physicalcpu'],
                capture_output=True,
                text=True
            )
            cpu_info['physical_cores'] = int(result.stdout.strip())
            
            result = subprocess.run(
                ['sysctl', '-n', 'hw.logicalcpu'],
                capture_output=True,
                text=True
            )
            cpu_info['logical_cores'] = int(result.stdout.strip())
            
            # Get performance and efficiency core counts (Apple Silicon)
            if self.is_apple_silicon:
                try:
                    result = subprocess.run(
                        ['sysctl', '-n', 'hw.perflevel0.physicalcpu'],
                        capture_output=True,
                        text=True
                    )
                    cpu_info['efficiency_cores'] = int(result.stdout.strip())
                    
                    result = subprocess.run(
                        ['sysctl', '-n', 'hw.perflevel1.physicalcpu'],
                        capture_output=True,
                        text=True
                    )
                    cpu_info['performance_cores'] = int(result.stdout.strip())
                except:
                    # Estimate based on total cores
                    cpu_info['performance_cores'] = cpu_info['physical_cores'] // 2
                    cpu_info['efficiency_cores'] = cpu_info['physical_cores'] - cpu_info['performance_cores']
            
            # Get CPU frequency
            try:
                result = subprocess.run(
                    ['sysctl', '-n', 'hw.cpufrequency_max'],
                    capture_output=True,
                    text=True
                )
                freq_hz = int(result.stdout.strip())
                cpu_info['cpu_frequency_ghz'] = freq_hz / 1e9
            except:
                cpu_info['cpu_frequency_ghz'] = 3.2  # Default estimate
                
        except Exception as e:
            print(f"Error getting CPU details: {e}")
        
        return cpu_info
    
    def _get_gpu_details(self) -> Dict[str, Any]:
        """Get GPU information"""
        gpu_info = {
            'gpu_cores': 0,
            'metal_support': False,
            'neural_engine_cores': 0,
            'gpu_family': '',
            'discrete_gpu': False
        }
        
        try:
            # Check for Metal support
            result = subprocess.run(
                ['system_profiler', 'SPDisplaysDataType'],
                capture_output=True,
                text=True
            )
            output = result.stdout
            
            gpu_info['metal_support'] = 'Metal' in output
            
            if self.is_apple_silicon:
                # Parse Apple GPU info
                chip_model = self._get_chip_model()
                gpu_info['gpu_family'] = 'Apple GPU'
                gpu_info['gpu_cores'] = self._estimate_gpu_cores(chip_model)
                gpu_info['neural_engine_cores'] = 16  # Most Apple Silicon chips
            else:
                # Check for discrete GPU
                if 'AMD' in output or 'NVIDIA' in output:
                    gpu_info['discrete_gpu'] = True
                    gpu_info['gpu_family'] = 'AMD' if 'AMD' in output else 'NVIDIA'
                else:
                    gpu_info['gpu_family'] = 'Intel Integrated'
                    
        except Exception as e:
            print(f"Error getting GPU details: {e}")
        
        return gpu_info
    
    def _estimate_gpu_cores(self, chip_model: str) -> int:
        """Estimate GPU core count based on chip model"""
        gpu_cores_map = {
            'Apple M1': 8,
            'Apple M1 Pro': 16,
            'Apple M1 Max': 32,
            'Apple M1 Ultra': 64,
            'Apple M2': 10,
            'Apple M2 Pro': 19,
            'Apple M2 Max': 38,
            'Apple M2 Ultra': 76,
            'Apple M3': 10,
            'Apple M3 Pro': 18,
            'Apple M3 Max': 40,
        }
        
        for chip, cores in gpu_cores_map.items():
            if chip in chip_model:
                return cores
        
        return 8  # Default estimate
    
    def _detect_discrete_gpu_memory(self) -> float:
        """Detect discrete GPU memory on Intel Macs"""
        try:
            result = subprocess.run(
                ['system_profiler', 'SPDisplaysDataType'],
                capture_output=True,
                text=True
            )
            output = result.stdout
            
            # Look for VRAM info
            vram_match = re.search(r'VRAM.*?:\s*(\d+)\s*(MB|GB)', output, re.IGNORECASE)
            if vram_match:
                size = float(vram_match.group(1))
                unit = vram_match.group(2).upper()
                if unit == 'MB':
                    return size / 1024
                else:
                    return size
        except:
            pass
        
        return 0.0
    
    def get_optimization_recommendations(self) -> Dict[str, Any]:
        """Get optimization recommendations based on hardware"""
        recommendations = {
            'use_unified_memory': self.unified_memory_info['has_unified_memory'],
            'max_parallel_tasks': self.cpu_info['logical_cores'],
            'preferred_batch_size': self._calculate_optimal_batch_size(),
            'gpu_acceleration': self.gpu_info['metal_support'],
            'memory_limit_gb': self.unified_memory_info['total_memory_gb'] * 0.8,
            'architecture_specific': []
        }
        
        if self.is_apple_silicon:
            recommendations['architecture_specific'].extend([
                'Use Metal Performance Shaders for GPU compute',
                'Leverage unified memory for zero-copy data sharing',
                'Schedule background tasks on efficiency cores',
                'Use Neural Engine for ML inference when possible'
            ])
        else:
            recommendations['architecture_specific'].extend([
                'Use OpenCL or CUDA for GPU compute',
                'Optimize for cache hierarchy',
                'Consider NUMA effects on larger systems',
                'Use AVX instructions for vectorization'
            ])
        
        return recommendations
    
    def _calculate_optimal_batch_size(self) -> int:
        """Calculate optimal batch size based on memory and cores"""
        memory_gb = self.unified_memory_info['total_memory_gb']
        cores = self.cpu_info['logical_cores']
        
        # Simple heuristic: aim for batches that fit in L3 cache
        # but scale with available memory
        base_batch = 1024
        memory_factor = min(memory_gb / 8, 4)  # Scale up to 4x for high memory
        core_factor = min(cores / 8, 2)  # Scale up to 2x for many cores
        
        return int(base_batch * memory_factor * core_factor)
    
    def get_system_summary(self) -> str:
        """Get a human-readable system summary"""
        lines = [
            "=== macOS System Information ===",
            f"Platform: {self.system_info['platform']} {self.system_info['platform_version']}",
            f"Architecture: {self.system_info['architecture']}",
            f"Apple Silicon: {'Yes' if self.is_apple_silicon else 'No'}",
            "",
            "=== CPU Information ===",
            f"Physical Cores: {self.cpu_info['physical_cores']}",
            f"Logical Cores: {self.cpu_info['logical_cores']}",
        ]
        
        if self.is_apple_silicon:
            lines.extend([
                f"Performance Cores: {self.cpu_info['performance_cores']}",
                f"Efficiency Cores: {self.cpu_info['efficiency_cores']}",
            ])
        
        lines.extend([
            f"CPU Frequency: {self.cpu_info['cpu_frequency_ghz']:.2f} GHz",
            "",
            "=== Memory Information ===",
            f"Total Memory: {self.unified_memory_info['total_memory_gb']:.1f} GB",
            f"Unified Memory: {'Yes' if self.unified_memory_info['has_unified_memory'] else 'No'}",
        ])
        
        if self.unified_memory_info['has_unified_memory']:
            lines.append(f"Memory Bandwidth: {self.unified_memory_info['memory_bandwidth_gbps']:.1f} GB/s")
        else:
            lines.append(f"GPU Memory: {self.unified_memory_info['gpu_memory_gb']:.1f} GB")
        
        lines.extend([
            "",
            "=== GPU Information ===",
            f"GPU Family: {self.gpu_info['gpu_family']}",
            f"GPU Cores: {self.gpu_info['gpu_cores']}",
            f"Metal Support: {'Yes' if self.gpu_info['metal_support'] else 'No'}",
        ])
        
        if self.is_apple_silicon:
            lines.append(f"Neural Engine Cores: {self.gpu_info['neural_engine_cores']}")
        
        return "\n".join(lines)


def main():
    """Test the MacOptimizer functionality"""
    optimizer = MacOptimizer()
    
    print(optimizer.get_system_summary())
    print("\n=== Optimization Recommendations ===")
    recommendations = optimizer.get_optimization_recommendations()
    for key, value in recommendations.items():
        if key == 'architecture_specific':
            print(f"{key}:")
            for rec in value:
                print(f"  - {rec}")
        else:
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()