"""进程内异步事件总线。

用于解耦核心各层（采集→融合→控制、状态变化、安全事件），
订阅者与发布者互不直接引用。所有处理器均为 async 协程。
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict, List

logger = logging.getLogger(__name__)

EventHandler = Callable[..., Awaitable[None]]


class EventBus:
    """以主题为 key 的异步发布/订阅总线（单事件循环模型）。

    订阅与发布均需在已运行的事件循环内调用。处理器异常会被隔离，
    不阻断同一主题下的其他处理器。
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[EventHandler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        """订阅主题。同一 handler 重复订阅会被忽略。"""
        if handler not in self._subscribers[topic]:
            self._subscribers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: EventHandler) -> None:
        """取消订阅。handler 不存在时静默忽略。"""
        try:
            self._subscribers[topic].remove(handler)
        except ValueError:
            pass

    def on(self, topic: str) -> Callable[[EventHandler], EventHandler]:
        """订阅装饰器，用法：``@bus.on("state_change")``。"""

        def decorator(handler: EventHandler) -> EventHandler:
            self.subscribe(topic, handler)
            return handler

        return decorator

    async def publish(self, topic: str, *args: Any, **kwargs: Any) -> None:
        """向主题的所有订阅者并发广播。

        单个处理器异常会被记录并隔离，不影响其余处理器。
        """
        handlers = list(self._subscribers.get(topic, []))
        if not handlers:
            return

        async def _guarded(handler: EventHandler) -> None:
            try:
                await handler(*args, **kwargs)
            except Exception:  # noqa: BLE001
                logger.exception("事件处理器异常 topic=%s handler=%r", topic, handler)

        await asyncio.gather(*(_guarded(h) for h in handlers))