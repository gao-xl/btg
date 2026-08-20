"""开发/联调用 mock 传感器插件（无真实硬件）。

通过 ``@register_sensor("mock_sensor")`` 登记，供 HAL 冗余路由、
融合引擎与总线在无硬件环境下联调。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Mapping

from btg_sdk import BaseSensor, Reading, register_sensor


@register_sensor("mock_sensor")
class MockSensor(BaseSensor):
    """周期性产出可配置读数的虚拟传感器。

    配置项：
    - ``channel``: 逻辑通道名，默认 ``"heart_rate"``。
    - ``unit``: 物理单位，默认 ``"bpm"``。
    - ``base_value``: 基础值（float）。
    - ``interval``: 采样间隔（秒）。
    - ``cycles``: 产出样本数，超过后结束读流以模拟断连；0 表示无限。
    """

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.instance_id = str(config.get("instance_id", "mock_sensor"))
        self.channel = str(config.get("channel", "heart_rate"))
        self.unit = str(config.get("unit", "bpm"))
        self.base_value = float(config.get("base_value", 80.0))
        self.interval = float(config.get("interval", 0.1))
        self.cycles = int(config.get("cycles", 0))
        self._connected = False

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def read_stream(self, out_queue: asyncio.Queue) -> None:
        n = 0
        while True:
            if self.cycles > 0 and n >= self.cycles:
                break  # 模拟物理断连：正常结束读流
            reading = Reading(
                channel=self.channel,
                sensor_id=self.instance_id,
                value=self.base_value + n,
                unit=self.unit,
                timestamp=time.time(),
            )
            out_queue.put_nowait(reading)
            n += 1
            await asyncio.sleep(self.interval)