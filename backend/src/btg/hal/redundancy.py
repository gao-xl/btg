"""冗余路由：逻辑通道下的主备设备自动故障切换。

实现 ``devices.yaml`` 中「同通道多设备 + 优先级」设计。上层（融合/总线）
只需面向逻辑通道，不必关心背后是主设备还是备用设备在服务。

设备只做单轮尝试（按优先级各试一次）；全部失败后进入停机状态，
由上层决定是否重试重连。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional, cast

from btg_sdk import BaseActuator, BaseSensor

logger = logging.getLogger(__name__)


@dataclass
class DeviceHandle:
    """设备句柄（构造时设备列表已按 priority 升序）。"""

    instance_id: str
    device: BaseSensor | BaseActuator
    priority: int


class RedundantSensorGroup:
    """传感器冗余组：读流断连时按优先级降级到备用设备。"""

    def __init__(
        self,
        channel: str,
        handles: List[DeviceHandle],
        queue: asyncio.Queue,
    ) -> None:
        self.channel = channel
        self.handles = sorted(handles, key=lambda h: h.priority)
        self.queue = queue
        self.active: Optional[DeviceHandle] = None
        self._cursor = 0
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> bool:
        """依次连接设备直至成功；全部失败返回 False。"""
        return await self._activate_next()

    async def stop(self) -> None:
        """停止读流并断开设备（幂等）。"""
        if self._task is not None:
            self._task.cancel()
            self._task = None
        await self._disconnect(self.active)
        self.active = None

    async def _activate_next(self) -> bool:
        while self._cursor < len(self.handles):
            handle = self.handles[self._cursor]
            self._cursor += 1
            if await self._try_connect(handle):
                return True
        return False

    async def _try_connect(self, handle: DeviceHandle) -> bool:
        try:
            ok = await handle.device.connect()
        except Exception:  # noqa: BLE001
            logger.exception(
                "传感器连接失败 channel=%s instance=%s", self.channel, handle.instance_id
            )
            ok = False
        if not ok:
            return False
        self.active = handle
        self._task = asyncio.create_task(self._stream(handle))
        return True

    async def _stream(self, handle: DeviceHandle) -> None:
        sensor = cast(BaseSensor, handle.device)
        try:
            await sensor.read_stream(self.queue)
        except asyncio.CancelledError:
            raise  # 主动停止：交由 stop() 统一清理，不触发故障切换
        except Exception:  # noqa: BLE001
            logger.exception(
                "传感器读流异常 channel=%s instance=%s", self.channel, handle.instance_id
            )
        await self._failover(handle)

    async def _failover(self, failed: DeviceHandle) -> None:
        if self.active is failed:
            self.active = None
        await self._disconnect(failed)
        await self._activate_next()

    async def _disconnect(self, handle: Optional[DeviceHandle]) -> None:
        if handle is None:
            return
        try:
            await handle.device.disconnect()
        except Exception:  # noqa: BLE001
            logger.exception(
                "设备断开异常 channel=%s instance=%s", self.channel, handle.instance_id
            )


class ActuatorGroup:
    """执行器冗余组：下发失败时按优先级切换到备用执行器。"""

    def __init__(self, channel: str, handles: List[DeviceHandle]) -> None:
        self.channel = channel
        self.handles = sorted(handles, key=lambda h: h.priority)
        self.active: Optional[DeviceHandle] = None
        self._cursor = 0

    async def start(self) -> bool:
        """连接首选执行器；全部失败返回 False。"""
        return await self._activate_next()

    async def _activate_next(self) -> bool:
        while self._cursor < len(self.handles):
            handle = self.handles[self._cursor]
            self._cursor += 1
            try:
                ok = await handle.device.connect()
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                self.active = handle
                return True
        return False

    async def set_target(self, value: float) -> bool:
        """下发目标值；当前执行器失败则切换备用后重试一次。"""
        if self.active is None and not await self._activate_next():
            return False
        if await self._send(self.active, value):
            return True
        await self._disconnect(self.active)
        self.active = None
        if not await self._activate_next():
            return False
        return await self._send(self.active, value)

    async def _send(self, handle: DeviceHandle, value: float) -> bool:
        actuator = cast(BaseActuator, handle.device)
        try:
            return await actuator.set_target(self.channel, value)
        except Exception:  # noqa: BLE001
            logger.exception(
                "执行器下发失败 channel=%s instance=%s", self.channel, handle.instance_id
            )
            return False

    async def _disconnect(self, handle: Optional[DeviceHandle]) -> None:
        if handle is None:
            return
        try:
            await handle.device.disconnect()
        except Exception:  # noqa: BLE001
            logger.exception(
                "执行器断开异常 channel=%s instance=%s", self.channel, handle.instance_id
            )

    async def stop(self) -> None:
        """停止当前执行器并断开（幂等）。"""
        if self.active is not None:
            actuator = cast(BaseActuator, self.active.device)
            try:
                await actuator.stop()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "执行器归零异常 channel=%s instance=%s",
                    self.channel,
                    self.active.instance_id,
                )
            await self._disconnect(self.active)
            self.active = None