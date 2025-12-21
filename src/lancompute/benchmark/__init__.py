"""LANCompute Benchmark - GPU performance regression testing."""

from .cifar10 import run_cifar10_benchmark
from .db import BenchmarkDB

__all__ = ["run_cifar10_benchmark", "BenchmarkDB"]
