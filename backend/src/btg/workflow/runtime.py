"""工作流运行时：按固定频率（Tick）驱动启用工作流并执行命中动作。

运行时与「上下文提供者」「动作执行器」解耦，通过异步回调注入：

- ``context_provider``：返回当前运行时上下文（心率/视觉/设备反馈/手动触发）；
- ``action_executor``：消费一条命中动作（设强度/设位置/调用 AI 话术）。

这样运行时既可挂在网关上（读遥测缓存 + 下发执行器），也可在测试中注入假实现。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Mapping, Optional

from .service import WorkflowService

logger = logging.getLogger(__name__)

ContextProvider = Callable[[], Awaitable[Mapping[str, Any]]]
ActionExecutor = Callable[[Mapping[str, Any]], Awaitable[None]]


class WorkflowRuntime:
    """背包工作流的后台 Tick 循环（面向单事件循环）。"""

    def __init__(
        self,
        service: WorkflowService,
        context_provider: ContextProvider,
        action_executor: ActionExecutor,
        *,
        default_tick_hz: float = 5.0,
    ) -> None:
        self.service = service
        self._context_provider = context_provider
        self._action_executor = action_executor
        self._default_tick_hz = default_tick_hz
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """启动后台 Tick 循环（幂等）。"""
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """停止后台 Tick 循环（幂等）。"""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def tick_once(self) -> int:
        """手动求值一轮，返回命中的动作条数（供测试/REST 触发）。"""
        context = await self._context_provider()
        actions = self.service.tick(context)
        for action in actions:
            try:
                await self._action_executor(action)
            except Exception:  # noqa: BLE001 - 单动作失败不阻断其余动作
                logger.exception("工作流动作执行失败 action=%s", action)
        return len(actions)

    async def _run(self) -> None:
        while True:
            try:
                await self.tick_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("工作流 Tick 循环异常")
            await asyncio.sleep(1.0 / self._default_tick_hz)


__all__ = ["WorkflowRuntime", "ContextProvider", "ActionExecutor"]