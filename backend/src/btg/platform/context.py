"""平台上下文：模块访问内核服务的统一句柄。

模块实现只允许通过该上下文与平台交互（事件总线、遥测缓存、配置中心、
进程级设置与日志），不得直接 import 其他模块的内部实现，从而守住
"万物皆插件、模块间零耦合"的边界。
"""
from __future__ import annotations

import logging
from typing import Any, Optional


class PlatformContext:
    """向插件模块暴露的平台能力句柄。

    Attributes:
        event_bus: 进程内异步事件总线（见 :mod:`btg.core.events`）。
        ring_buffer: 遥测环形缓冲（见 :mod:`btg.core.telemetry`）。
        config_manager: 全局配置中心（见 :mod:`btg.config.config_manager`）。
        settings: 网关进程级设置（见 :mod:`btg.settings`）。
        logger: 模块可复用的日志器。
    """

    def __init__(
        self,
        *,
        event_bus: Any = None,
        ring_buffer: Any = None,
        config_manager: Any = None,
        settings: Any = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.event_bus = event_bus
        self.ring_buffer = ring_buffer
        self.config_manager = config_manager
        self.settings = settings
        self.logger = logger or logging.getLogger("btg.platform")