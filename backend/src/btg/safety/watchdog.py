"""心跳看门狗：控制链路超时后自动归零执行器。

设计原则（详见 ``docs/architecture.md``）：取代传统「大红急停按钮」。
正常情况下控制链路（前端/融合引擎/第三方平台）会周期性下发指令，每次
指令都会刷新心跳；一旦链路失联或上位机进程卡死，超过 ``timeout`` 秒未
收到任何心跳，看门狗立即触发回调，把所有执行器归零并物理断开。

回调由使用方注入（通常是执行器冗余组的 ``stop()``），本模块不感知具体
执行器实现，保持与 HAL 层的解耦。
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Optional

from btg.core.exceptions import HeartbeatTimeoutError
from btg.core.logging import get_audit_logger

audit = get_audit_logger()

TimeoutCallback = Callable[[], Awaitable[None]]


class Watchdog:
    """单事件循环内的心跳看门狗。

    通过 ``feed()`` 刷新心跳；后台协程周期性检测，超时触发一次
    ``on_timeout`` 回调并重置心跳（等待下一轮喂狗），避免重复触发。
    """

    def __init__(
        self,
        timeout: float,
        on_timeout: TimeoutCallback,
        *,
        poll_interval: Optional[float] = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout 必须为正数（单位：秒）")
        self.timeout = timeout
        self._poll_interval = poll_interval or min(timeout / 2.0, 1.0)
        self._on_timeout = on_timeout
        self._last_feed = time.monotonic()
        self._task: Optional[asyncio.Task] = None

    def feed(self) -> None:
        """刷新心跳时间戳。

        每次合法下行指令通过安全层后调用；链路保活也可靠此续命。
        """
        self._last_feed = time.monotonic()

    def set_timeout(self, timeout: float) -> None:
        """运行期热更新超时时间（供配置中心联动安全层）。

        Args:
            timeout: 新的心跳超时（秒），必须为正数。
        """
        if timeout <= 0:
            raise ValueError("timeout 必须为正数（单位：秒）")
        self.timeout = timeout
        self._poll_interval = min(timeout / 2.0, 1.0)

    async def start(self) -> None:
        """启动后台监控协程（幂等：重复调用不叠加任务）。"""
        if self._task is not None:
            return
        self._last_feed = time.monotonic()
        self._task = asyncio.create_task(self._monitor())

    async def _monitor(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval)
            if time.monotonic() - self._last_feed >= self.timeout:
                await self._fire()

    async def _fire(self) -> None:
        audit.warning(
            "看门狗心跳超时 timeout=%ss，触发执行器归零", self.timeout
        )
        try:
            await self._on_timeout()
        except Exception:  # noqa: BLE001
            audit.exception("看门狗归零回调执行失败")
        # 超时后重置心跳，仅当再次超时才会重复触发（持续失联则周期性归零）
        self._last_feed = time.monotonic()

    async def stop(self) -> None:
        """停止后台监控并等待协程退出（幂等）。"""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def check_now(self) -> None:
        """立即检测一次是否超时（供测试或手动巡检）。

        Raises:
            HeartbeatTimeoutError: 距离上次 feed 已超过 timeout。
        """
        if time.monotonic() - self._last_feed >= self.timeout:
            raise HeartbeatTimeoutError(
                f"心跳超时：已 {time.monotonic() - self._last_feed:.2f}s 未喂狗"
            )