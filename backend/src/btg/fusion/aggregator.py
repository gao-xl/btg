"""多通道滑动窗口聚合器：将高频传感器读数压缩为通道级特征。

设计原则（详见 ``docs/architecture.md``）：摄像头、麦克风、心率带、
IMU 等会以不同频率产出海量样本；融合引擎不直接消费原始样本，而是
先在本模块按逻辑通道维护一个时间滑动窗口，计算均值等统计特征，
供规则引擎/状态机以固定节奏评估。

面向单 asyncio 事件循环使用；``push`` 是同步快速路径，在两次 ``await``
之间原子完成，无需加锁。
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple

from btg_sdk import Reading


@dataclass(frozen=True, slots=True)
class ChannelSnapshot:
    """单个逻辑通道在滑动窗口内的聚合视图。

    Attributes:
        channel: 逻辑通道名。
        unit: 物理单位，取自最新样本。
        latest_value: 窗口内最新的采样值。
        mean: 窗口内样本均值。
        count: 窗口内样本数。
        window_start: 窗口内最早样本时间戳（Unix epoch 秒）。
        window_end: 窗口内最新样本时间戳。
    """

    channel: str
    unit: str
    latest_value: float
    mean: float
    count: int
    window_start: float
    window_end: float


class TelemetryAggregator:
    """按通道维护时间滑动窗口并计算统计特征。"""

    def __init__(
        self,
        window_seconds: float = 10.0,
        max_samples: int = 4096,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds 必须为正数（单位：秒）")
        if max_samples <= 0:
            raise ValueError("max_samples 必须为正整数")
        self.window_seconds = window_seconds
        self.max_samples = max_samples
        # channel -> [(timestamp, value), ...] 按时间戳递增
        self._windows: Dict[str, Deque[Tuple[float, float]]] = {}
        self._units: Dict[str, str] = {}

    def push(self, reading: Reading) -> None:
        """写入一条采样读数（同步快速路径）。"""
        window = self._windows.get(reading.channel)
        if window is None:
            window = deque()
            self._windows[reading.channel] = window

        window.append((reading.timestamp, reading.value))
        self._units[reading.channel] = reading.unit
        if len(window) > self.max_samples:
            window.popleft()
        self._prune(reading.channel, reading.timestamp)

    def _prune(self, channel: str, now: float) -> None:
        """丢弃早于 ``now - window_seconds`` 的样本。"""
        window = self._windows[channel]
        cutoff = now - self.window_seconds
        while window and window[0][0] < cutoff:
            window.popleft()

    def snapshot(self, channel: str) -> Optional[ChannelSnapshot]:
        """返回某通道的聚合快照，无样本返回 None。"""
        window = self._windows.get(channel)
        if not window:
            return None
        values = [v for _, v in window]
        return ChannelSnapshot(
            channel=channel,
            unit=self._units.get(channel, ""),
            latest_value=window[-1][1],
            mean=sum(values) / len(values),
            count=len(window),
            window_start=window[0][0],
            window_end=window[-1][0],
        )

    def snapshots(self) -> Dict[str, ChannelSnapshot]:
        """返回所有有样本通道的聚合快照映射。"""
        return {
            channel: snap
            for channel in self._windows
            if (snap := self.snapshot(channel)) is not None
        }

    def latest(self, channel: str) -> Optional[float]:
        """返回某通道最新值，无样本返回 None。"""
        window = self._windows.get(channel)
        return window[-1][1] if window else None

    def channels(self) -> list[str]:
        """返回存在样本的通道名列表。"""
        return list(self._windows.keys())

    def reset(self) -> None:
        """清空所有窗口（供测试隔离或模式切换后重启）。"""
        self._windows.clear()