"""反馈采集器：周期轮询激活执行器，采集其回传的设备反馈信息。

执行器通过可选的 ``collect_feedback()`` 方法（见 ``btg_sdk.BaseActuator``）
返回反馈列表；未实现该方法的执行器被静默跳过。采集到的反馈经 ``sink``
回调订阅方（通常由网关接入聚合器并广播到事件总线）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, List, Optional

from btg_sdk import DeviceFeedback

logger = logging.getLogger(__name__)

# 反馈消费者：接收单条反馈（例如写入聚合器并广播）。
FeedbackSink = Callable[[DeviceFeedback], Awaitable[None]]


class FeedbackCollector:
    """周期轮询激活执行器并分发其反馈。

    ``channel_manager`` 应具备 ``actuator_groups`` 与 ``DeviceHandle`` 结构
    （见 ``btg.hal.redundancy``），本模块不反向依赖 hal 层以保持解耦。
    """

    def __init__(
        self,
        channel_manager: object,
        *,
        interval_seconds: float = 10.0,
        sink: Optional[FeedbackSink] = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds 必须为正数（单位：秒）")
        self._channel_manager = channel_manager
        self._interval = interval_seconds
        self._sink = sink
        self._task: Optional[asyncio.Task] = None

    def set_sink(self, sink: FeedbackSink) -> None:
        """设置反馈消费者回调。"""
        self._sink = sink

    async def start(self) -> None:
        """启动后台采集任务（幂等）。"""
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """停止后台采集任务（幂等）。"""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def collect_once(self) -> List[DeviceFeedback]:
        """对当前所有激活执行器采集一轮，返回收集到的反馈列表。"""
        collected: List[DeviceFeedback] = []
        for group in self._channel_manager.actuator_groups.values():
            handle = group.active
            if handle is None:
                continue
            collect = getattr(handle.device, "collect_feedback", None)
            if collect is None:
                continue
            try:
                items = await collect()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "执行器反馈采集异常 instance=%s", getattr(handle, "instance_id", "?")
                )
                continue
            for feedback in items or []:
                collected.append(feedback)
                if self._sink is not None:
                    try:
                        await self._sink(feedback)
                    except Exception:  # noqa: BLE001
                        logger.exception("反馈消费者处理异常 device=%s", feedback.device_id)
        return collected

    async def _run(self) -> None:
        while True:
            try:
                await self.collect_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("反馈采集轮询异常")
            await asyncio.sleep(self._interval)