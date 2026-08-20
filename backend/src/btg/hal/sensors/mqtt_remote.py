"""主机侧远程传感器（对应开发板上的真实采集）。

经 ``@register_sensor("mqtt_bridge")`` 登记；在 ``devices.yaml`` 中一个
``heart_rate`` 通道可绑定 ``plugin: mqtt_bridge`` 设备，表示该读数来自
某块板的 MQTT 遥测。配置项：
- ``board_id``: 目标开发板标识（必填）
- ``channel``: 本机逻辑通道名（过滤板端上报的同名读数）
- broker 参数：``broker_host`` / ``broker_port`` / ``username`` / ``password``

未安装 paho-mqtt 时 ``connect`` 抛异常，由 HAL 冗余层触发本地备用设备接管。
"""
from __future__ import annotations

import asyncio
from typing import Any, Mapping

from btg_sdk import BaseSensor, Reading, register_sensor

from btg.hal.mqtt_bus import get_mqtt_bus


@register_sensor("mqtt_bridge")
class MqttRemoteSensor(BaseSensor):
    """从一块 MQTT 开发板持续接收某逻辑通道的 Reading。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.board_id = str(config["board_id"])
        self.channel = str(config.get("channel", self.board_id))
        self.instance_id = str(
            config.get("instance_id", f"mqtt:{self.board_id}:{self.channel}")
        )
        self._bus = get_mqtt_bus()
        self._bus.configure(
            host=config.get("broker_host"),
            port=int(config.get("broker_port", 1883)),
            username=config.get("username"),
            password=config.get("password"),
            prefix=config.get("prefix"),
        )
        self._queue: asyncio.Queue | None = None

    async def connect(self) -> bool:
        # subscribe_reading 内部会 start()（缺 paho 时抛 RuntimeError）
        self._queue = self._bus.subscribe_reading(self.board_id, self.channel)
        return True

    async def disconnect(self) -> None:
        if self._queue is not None:
            self._bus.unsubscribe_reading(self.board_id, self.channel, self._queue)
            self._queue = None

    async def read_stream(self, out_queue: asyncio.Queue) -> None:
        assert self._queue is not None, "必须先 connect()"
        while True:
            reading = await self._queue.get()
            if isinstance(reading, Reading):
                out_queue.put_nowait(reading)