"""BTG 硬件抽象层（HAL）：逻辑通道、插件加载与冗余路由。"""
from .config import (
    ChannelConfig,
    DeviceBinding,
    DeviceConfig,
    load_config,
    parse_channels,
)
from .loader import discover_and_load, load_builtin_plugins
from .manager import ChannelManager
from .redundancy import ActuatorGroup, DeviceHandle, RedundantSensorGroup

__all__ = [
    "ActuatorGroup",
    "ChannelConfig",
    "ChannelManager",
    "DeviceBinding",
    "DeviceConfig",
    "DeviceHandle",
    "RedundantSensorGroup",
    "discover_and_load",
    "load_builtin_plugins",
    "load_config",
    "parse_channels",
]