"""BTG 后端核心：跨层基础设施（事件总线、遥测缓冲、黑盒审计、异常、日志）。"""
from .audit_blackbox import AuditBlackbox, AuditFrame
from .events import EventBus
from .exceptions import (
    BTGError,
    DeviceConnectionError,
    HeartbeatTimeoutError,
    InvalidCommandError,
    SafetyViolationError,
)
from .logging import get_audit_logger, get_logger, setup_logging
from .telemetry import TelemetryRingBuffer

__all__ = [
    "AuditBlackbox",
    "AuditFrame",
    "BTGError",
    "DeviceConnectionError",
    "EventBus",
    "HeartbeatTimeoutError",
    "InvalidCommandError",
    "SafetyViolationError",
    "TelemetryRingBuffer",
    "get_audit_logger",
    "get_logger",
    "setup_logging",
]