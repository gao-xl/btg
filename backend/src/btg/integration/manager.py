"""第三方平台接入管理器：Outbound 事件扇出。

订阅事件总线（``telemetry`` / ``state_change``），将结构化事件转发给每个
已注册的第三方平台插件。单个插件失败会被隔离，不影响其余插件与主流程。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from btg.core.events import EventBus
from btg_sdk import ThirdPartyProvider

logger = logging.getLogger(__name__)


class IntegrationManager:
    """持有第三方平台插件并转发出站事件。"""

    def __init__(
        self,
        providers: Optional[List[ThirdPartyProvider]] = None,
        bus: Optional[EventBus] = None,
    ) -> None:
        self.providers: List[ThirdPartyProvider] = list(providers or [])
        self.bus = bus

    def subscribe(self, bus: EventBus) -> None:
        """订阅遥测与状态迁移事件（幂等）。"""
        bus.subscribe("telemetry", self._on_telemetry)
        bus.subscribe("state_change", self._on_state_change)

    async def _on_telemetry(self, reading: Any, **kwargs: Any) -> None:
        await self._fanout({
            "type": "telemetry",
            "channel": getattr(reading, "channel", ""),
            "sensor_id": getattr(reading, "sensor_id", ""),
            "value": getattr(reading, "value", None),
            "unit": getattr(reading, "unit", ""),
            "timestamp": getattr(reading, "timestamp", time.time()),
            "extra": dict(getattr(reading, "extra", {}) or {}),
        })

    async def _on_state_change(
        self,
        state: str,
        previous: str,
        reason: str = "",
        confidence: float = 1.0,
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        await self._fanout({
            "type": "state_change",
            "state": state,
            "previous": previous,
            "reason": reason,
            "confidence": confidence,
            "context": context or {},
            "timestamp": time.time(),
        })

    def push_event(self, event: Dict[str, Any]) -> None:
        """同步收集入口（供测试或本地审计使用），不执行 I/O。"""

    async def _fanout(self, event: Dict[str, Any]) -> None:
        for provider in self.providers:
            try:
                await provider.push_telemetry(event)
            except Exception:  # noqa: BLE001
                logger.exception("第三方平台推送失败 provider=%r", provider)

    async def start(self) -> None:
        """启动所有提供方（若有可选 ``start`` 生命周期方法）。"""
        for provider in self.providers:
            start = getattr(provider, "start", None)
            if start is not None:
                await start()

    async def stop(self) -> None:
        """关闭所有提供方（优先调用 ``close``，其次 ``stop``）。"""
        for provider in self.providers:
            close = getattr(provider, "close", None)
            if close is not None:
                await close()
                continue
            stop = getattr(provider, "stop", None)
            if stop is not None and stop is not self.stop:
                await stop()