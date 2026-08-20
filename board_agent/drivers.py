"""板端本地驱动抽象与内置 mock 驱动。

薄代理不关心"是什么硬件"，只按 channel 名绑定一个驱动对象：传感器产出
``Reading``，执行器接收 ``value`` / ``stop``。真实驱动（郊狼 BLE、Lynx、
摄像头/音频、小米手环等）后续在此实现，或在板端对现有 ``btg.hal`` 驱动
做一层适配后接入。
"""
from __future__ import annotations

import abc
import time
from typing import List, Optional

from btg_sdk import Reading


class BaseLocalSensor(abc.ABC):
    """板上真实采集驱动。"""

    @abc.abstractmethod
    def read(self) -> Optional[Reading]:
        """返回一次采样；返回 None 表示暂无数据。"""

    def close(self) -> None:
        """释放资源（可选）"""


class BaseLocalActuator(abc.ABC):
    """板上真实执行器驱动。"""

    @abc.abstractmethod
    def set_target(self, value: float, unit: str = "") -> bool:
        """设置目标强度/频率。"""

    @abc.abstractmethod
    def stop(self) -> None:
        """故障安全归零。"""

    def close(self) -> None:
        """释放资源（可选）"""


class MockHeartRateSensor(BaseLocalSensor):
    """联调用虚拟心率传感器。"""

    def __init__(self, board_id: str, channel: str) -> None:
        self.sensor_id = f"mock_hr:{board_id}:{channel}"
        self._n = 0

    def read(self) -> Optional[Reading]:
        self._n += 1
        return Reading(
            channel="heart_rate",
            sensor_id=self.sensor_id,
            value=72 + (self._n % 9),
            unit="bpm",
            timestamp=time.time(),
        )


class MockIntensityActuator(BaseLocalActuator):
    """联调用虚拟执行器（记录目标值）。"""

    def __init__(self, channel: str) -> None:
        self.channel = channel
        self.last_value = 0.0

    def set_target(self, value: float, unit: str = "") -> bool:
        self.last_value = float(value)
        return True

    def stop(self) -> None:
        self.last_value = 0.0


def build_drivers(
    board_id: str, channels, *, actuator: bool
):
    """由 channel 配置实例化内置 mock 驱动（后续替换为真实驱动工厂）。"""
    out: dict = {}
    if actuator:
        for ch in channels:
            out[ch.channel] = MockIntensityActuator(ch.channel)
    else:
        for ch in channels:
            out[ch.channel] = MockHeartRateSensor(board_id, ch.channel)
    return out