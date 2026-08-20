"""通道管理器：解析配置 → 实例化插件 → 组装冗余组 → 生命周期管理。"""
from __future__ import annotations

import asyncio
from typing import Dict, List

from btg_sdk import get_actuator_class, get_sensor_class

from .config import ChannelConfig, DeviceConfig
from .redundancy import ActuatorGroup, DeviceHandle, RedundantSensorGroup


class ChannelManager:
    """管理所有逻辑通道（传感器冗余组 + 执行器冗余组）。"""

    def __init__(self, config: DeviceConfig, queue: asyncio.Queue) -> None:
        self.config = config
        self.queue = queue
        self.sensor_groups: Dict[str, RedundantSensorGroup] = {}
        self.actuator_groups: Dict[str, ActuatorGroup] = {}

    def build(self) -> None:
        """根据配置实例化插件并组装冗余组。

        Raises:
            KeyError: 配置引用了未注册的插件实现名。
        """
        for ch in self.config.channels:
            if ch.kind == "sensor":
                self.sensor_groups[ch.name] = RedundantSensorGroup(
                    ch.name, self._sensor_handles(ch), self.queue
                )
            else:
                self.actuator_groups[ch.name] = ActuatorGroup(
                    ch.name, self._actuator_handles(ch)
                )

    async def start(self) -> None:
        """构建并连接所有通道。"""
        self.build()
        for group in self.sensor_groups.values():
            await group.start()
        for group in self.actuator_groups.values():
            await group.start()

    async def stop(self) -> None:
        """停止所有通道并释放设备（幂等）。"""
        for group in self.sensor_groups.values():
            await group.stop()
        for group in self.actuator_groups.values():
            await group.stop()

    def _sensor_handles(self, ch: ChannelConfig) -> List[DeviceHandle]:
        handles: List[DeviceHandle] = []
        for i, d in enumerate(ch.devices):
            cls = get_sensor_class(d.plugin)
            cfg = dict(d.config)
            cfg["instance_id"] = f"{ch.name}:{d.plugin}:{i}"
            handles.append(DeviceHandle(cfg["instance_id"], cls(config=cfg), d.priority))
        return handles

    def _actuator_handles(self, ch: ChannelConfig) -> List[DeviceHandle]:
        handles: List[DeviceHandle] = []
        for i, d in enumerate(ch.devices):
            cls = get_actuator_class(d.plugin)
            cfg = dict(d.config)
            cfg["instance_id"] = f"{ch.name}:{d.plugin}:{i}"
            handles.append(DeviceHandle(cfg["instance_id"], cls(config=cfg), d.priority))
        return handles