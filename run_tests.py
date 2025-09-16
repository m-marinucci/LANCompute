#!/usr/bin/env python3
"""Test runner script for LANCompute."""
import subprocess
import sys

def main():
    """Run all tests with coverage."""
    try:
        # Run pytest with coverage
        result = subprocess.run([
            sys.executable, "-m", "pytest",
            "tests/",
            "--cov=src/lancompute",
            "--cov-report=term-missing",
            "--cov-report=html",
            "-v"
        ], check=True)
        
        print("\n✅ All tests passed!")
        return 0
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Tests failed with exit code {e.returncode}")
        return e.returncode

if __name__ == "__main__":
    sys.exit(main())
