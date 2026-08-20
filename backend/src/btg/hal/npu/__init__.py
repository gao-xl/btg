"""NPU 硬件加速后端：自动检测、策略切换与 CPU 降级。"""
from .npu_manager import (
    BaseNPUBackend,
    CPUFallbackBackend,
    HailoNPUBackend,
    NPUManager,
    RKNNNPUBackend,
)

__all__ = [
    "BaseNPUBackend",
    "CPUFallbackBackend",
    "HailoNPUBackend",
    "NPUManager",
    "RKNNNPUBackend",
]
