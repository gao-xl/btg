"""Bio-Telemetry Gateway 插件 SDK。

第三方开发者仅依赖本包即可开发设备驱动或第三方平台接入插件，
无需 clone 整个网关代码。用法示例见 ``docs/architecture.md``。
"""
from . import hooks as hook
from .base import BaseActuator, BaseSensor, ThirdPartyProvider
from .registry import (
    clear_registry,
    get_actuator_class,
    get_provider_class,
    get_sensor_class,
    register_actuator,
    register_provider,
    register_sensor,
)
from . import transport
from .transport import (
    ack_topic,
    command_topic,
    event_topic,
    telemetry_topic,
)
from .types import ActuatorCommand, DeviceFeedback, FeedbackKind, Reading

__version__ = "0.1.0"

__all__ = [
    "ActuatorCommand",
    "BaseActuator",
    "BaseSensor",
    "DeviceFeedback",
    "FeedbackKind",
    "Reading",
    "ThirdPartyProvider",
    "ack_topic",
    "clear_registry",
    "command_topic",
    "event_topic",
    "get_actuator_class",
    "get_provider_class",
    "get_sensor_class",
    "hook",
    "register_actuator",
    "register_provider",
    "register_sensor",
    "telemetry_topic",
    "transport",
]