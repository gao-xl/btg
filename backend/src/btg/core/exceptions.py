"""BTG 核心异常体系。

统一异常便于上层安全层/融合层精准捕获与降级处理：

- 越界/安全违规交给安全策略层（clamps/policy）。
- 心跳超时交给 Watchdog（自动归零）。
- 设备断连交给冗余路由（故障切换）。
- 非法指令直接拒绝，防止恶意参数穿透。
"""
from __future__ import annotations


class BTGError(Exception):
    """网关所有业务异常的基类。"""

    code: str = "BTG_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class SafetyViolationError(BTGError):
    """数值越界或安全策略拦截异常。"""

    code = "SAFETY_VIOLATION"


class HeartbeatTimeoutError(BTGError):
    """Watchdog 心跳超时异常（超过设置期限未收到保活心跳）。"""

    code = "HEARTBEAT_TIMEOUT"


class DeviceConnectionError(BTGError):
    """设备断连/连接超时异常。"""

    code = "DEVICE_CONNECTION_ERROR"


class InvalidCommandError(BTGError):
    """非法下行指令/参数异常（疑似恶意或越权输入）。"""

    code = "INVALID_COMMAND"