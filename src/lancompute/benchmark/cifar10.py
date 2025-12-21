#!/usr/bin/env python3
"""
CIFAR-10 GPU Benchmark Script

Standardized benchmark for measuring GPU training performance.
Results are stored in PostgreSQL for trend tracking and regression detection.
"""

import logging
import os
import platform
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Results from a benchmark run."""

    accuracy: float
    samples_per_second: float
    training_time_seconds: float
    epochs: int
    batch_size: int
    gpu_info: Dict[str, Any]
    details: Dict[str, Any]


def get_gpu_info() -> Dict[str, Any]:
    """Get GPU and CUDA information."""
    info: Dict[str, Any] = {
        "name": None,
        "memory_mb": None,
        "cuda_version": None,
        "pytorch_version": None,
        "driver_version": None,
    }

    # Try to get NVIDIA GPU info
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(",")
            if len(parts) >= 3:
                info["name"] = parts[0].strip()
                info["memory_mb"] = int(parts[1].strip())
                info["driver_version"] = parts[2].strip()
    except Exception as e:
        logger.warning(f"Could not get nvidia-smi info: {e}")

    # Get PyTorch and CUDA version
    try:
        import torch

        info["pytorch_version"] = torch.__version__
        if torch.cuda.is_available():
            info["cuda_version"] = torch.version.cuda
            if not info["name"]:
                info["name"] = torch.cuda.get_device_name(0)
            if not info["memory_mb"]:
                info["memory_mb"] = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
    except ImportError:
        logger.warning("PyTorch not available")

    return info


def run_cifar10_benchmark(
    epochs: int = 5,
    batch_size: int = 128,
    learning_rate: float = 0.001,
    num_workers: int = 4,
    device: Optional[str] = None,
) -> BenchmarkResult:
    """
    Run CIFAR-10 training benchmark.

    Args:
        epochs: Number of training epochs
        batch_size: Training batch size
        learning_rate: Optimizer learning rate
        num_workers: DataLoader workers
        device: Device to use (cuda, mps, cpu, or auto)

    Returns:
        BenchmarkResult with performance metrics
    """
    import torch
    import torch.nn as nn
    import torch.optim as optim
    import torchvision
    import torchvision.transforms as transforms

    # Determine device
    if device is None or device == "auto":
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

    device_obj = torch.device(device)
    logger.info(f"Using device: {device}")

    # Get GPU info
    gpu_info = get_gpu_info()
    logger.info(f"GPU: {gpu_info.get('name', 'N/A')}")

    # Data transforms
    transform_train = transforms.Compose([
        transforms.RandomCrop(32, padding=4),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
    ])

    transform_test = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
    ])

    # Load CIFAR-10
    logger.info("Loading CIFAR-10 dataset...")
    data_dir = os.environ.get("CIFAR_DATA_DIR", "/tmp/cifar10")

    trainset = torchvision.datasets.CIFAR10(
        root=data_dir,
        train=True,
        download=True,
        transform=transform_train,
    )
    trainloader = torch.utils.data.DataLoader(
        trainset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        pin_memory=(device == "cuda"),
    )

    testset = torchvision.datasets.CIFAR10(
        root=data_dir,
        train=False,
        download=True,
        transform=transform_test,
    )
    testloader = torch.utils.data.DataLoader(
        testset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=(device == "cuda"),
    )

    # Simple CNN model (ResNet-style)
    class SimpleCNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv1 = nn.Conv2d(3, 64, 3, padding=1)
            self.bn1 = nn.BatchNorm2d(64)
            self.conv2 = nn.Conv2d(64, 128, 3, padding=1)
            self.bn2 = nn.BatchNorm2d(128)
            self.conv3 = nn.Conv2d(128, 256, 3, padding=1)
            self.bn3 = nn.BatchNorm2d(256)
            self.pool = nn.MaxPool2d(2, 2)
            self.fc1 = nn.Linear(256 * 4 * 4, 512)
            self.fc2 = nn.Linear(512, 10)
            self.dropout = nn.Dropout(0.5)
            self.relu = nn.ReLU()

        def forward(self, x):
            x = self.pool(self.relu(self.bn1(self.conv1(x))))
            x = self.pool(self.relu(self.bn2(self.conv2(x))))
            x = self.pool(self.relu(self.bn3(self.conv3(x))))
            x = x.view(-1, 256 * 4 * 4)
            x = self.dropout(self.relu(self.fc1(x)))
            x = self.fc2(x)
            return x

    model = SimpleCNN().to(device_obj)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=learning_rate)

    # Training
    logger.info(f"Starting training: {epochs} epochs, batch_size={batch_size}")
    total_samples = 0
    epoch_losses = []
    epoch_accuracies = []

    start_time = time.time()

    for epoch in range(epochs):
        model.train()
        running_loss = 0.0
        correct = 0
        total = 0

        for i, (inputs, labels) in enumerate(trainloader):
            inputs, labels = inputs.to(device_obj), labels.to(device_obj)

            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            running_loss += loss.item()
            _, predicted = outputs.max(1)
            total += labels.size(0)
            correct += predicted.eq(labels).sum().item()
            total_samples += labels.size(0)

        epoch_loss = running_loss / len(trainloader)
        epoch_acc = 100.0 * correct / total
        epoch_losses.append(epoch_loss)
        epoch_accuracies.append(epoch_acc)

        logger.info(f"Epoch {epoch+1}/{epochs}: Loss={epoch_loss:.4f}, Train Acc={epoch_acc:.2f}%")

    training_time = time.time() - start_time

    # Evaluation
    logger.info("Evaluating on test set...")
    model.eval()
    correct = 0
    total = 0

    with torch.no_grad():
        for inputs, labels in testloader:
            inputs, labels = inputs.to(device_obj), labels.to(device_obj)
            outputs = model(inputs)
            _, predicted = outputs.max(1)
            total += labels.size(0)
            correct += predicted.eq(labels).sum().item()

    test_accuracy = 100.0 * correct / total
    samples_per_second = total_samples / training_time

    logger.info(f"Test Accuracy: {test_accuracy:.2f}%")
    logger.info(f"Training Time: {training_time:.1f}s")
    logger.info(f"Throughput: {samples_per_second:.0f} samples/sec")

    return BenchmarkResult(
        accuracy=test_accuracy,
        samples_per_second=samples_per_second,
        training_time_seconds=training_time,
        epochs=epochs,
        batch_size=batch_size,
        gpu_info=gpu_info,
        details={
            "epoch_losses": epoch_losses,
            "epoch_accuracies": epoch_accuracies,
            "total_samples": total_samples,
            "learning_rate": learning_rate,
            "device": device,
            "platform": platform.platform(),
        },
    )


def main():
    """Run benchmark from command line."""
    import argparse

    parser = argparse.ArgumentParser(description="CIFAR-10 GPU Benchmark")
    parser.add_argument("--epochs", type=int, default=5, help="Number of epochs")
    parser.add_argument("--batch-size", type=int, default=128, help="Batch size")
    parser.add_argument("--lr", type=float, default=0.001, help="Learning rate")
    parser.add_argument("--workers", type=int, default=4, help="DataLoader workers")
    parser.add_argument("--device", default="auto", help="Device (cuda, mps, cpu, auto)")
    parser.add_argument("--log-level", default="INFO", help="Logging level")

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    result = run_cifar10_benchmark(
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        num_workers=args.workers,
        device=args.device,
    )

    print("\n" + "=" * 50)
    print("BENCHMARK RESULTS")
    print("=" * 50)
    print(f"GPU: {result.gpu_info.get('name', 'N/A')}")
    print(f"CUDA: {result.gpu_info.get('cuda_version', 'N/A')}")
    print(f"PyTorch: {result.gpu_info.get('pytorch_version', 'N/A')}")
    print("-" * 50)
    print(f"Test Accuracy: {result.accuracy:.2f}%")
    print(f"Throughput: {result.samples_per_second:.0f} samples/sec")
    print(f"Training Time: {result.training_time_seconds:.1f}s")
    print(f"Epochs: {result.epochs}")
    print(f"Batch Size: {result.batch_size}")
    print("=" * 50)


if __name__ == "__main__":
    main()
