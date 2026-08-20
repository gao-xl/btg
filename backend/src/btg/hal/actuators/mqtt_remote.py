"""主机侧远程执行器（由开发板本地驱动真实硬件）。

经 ``@register_actuator("mqtt_bridge")`` 登记；``set_target`` 把经过安全层
截断的目标发布到 ``btg/{board_id}/command``，由板端薄代理按其 channel→驱动
映射落地到真实设备。配置项：
- ``board_id``: 目标开发板标识（必填）
- broker 参数：``broker_host`` / ``broker_port`` / ``username`` / ``password``
"""
from __future__ import annotations

from typing import Any, Mapping

from btg_sdk import BaseActuator, register_actuator, transport

from btg.hal.mqtt_bus import get_mqtt_bus


@register_actuator("mqtt_bridge")
class MqttRemoteActuator(BaseActuator):
    """把执行目标转发给某块 MQTT 开发板。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.board_id = str(config["board_id"])
        self._bus = get_mqtt_bus()
        self._bus.configure(
            host=config.get("broker_host"),
            port=int(config.get("broker_port", 1883)),
            username=config.get("username"),
            password=config.get("password"),
            prefix=config.get("prefix"),
        )

    async def connect(self) -> bool:
        self._bus.start()
        return True

    async def disconnect(self) -> None:
        return None

    async def set_target(self, channel: str, value: float) -> bool:
        payload = transport.encode_command(self.board_id, channel, value, unit="%")
        return self._bus.publish_command(self.board_id, payload)

    async def stop(self) -> None:
        # 安全停机广播：板端薄代理对其全部执行驱动执行故障安全归零
        payload = transport.encode_command(self.board_id, "_all", None, action="stop")
        self._bus.publish_command(self.board_id, payload)