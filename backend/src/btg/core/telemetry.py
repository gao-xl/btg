"""遥测环形缓冲：高频读写的内存存储。

设计目标：写入（传感器侧）与读取（WebSocket 广播/融合查询）互不阻塞，
单事件循环内安全。环形缓冲限制内存占用，超限自动覆盖最旧样本。
"""
from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional

from btg_sdk import Reading


class TelemetryRingBuffer:
    """按逻辑通道维护最近读数的环形缓冲。

    注意：面向单 asyncio 事件循环使用。``push`` 为同步快速路径，
    在两次 ``await`` 之间原子完成，故无需加锁。

    Attributes:
        capacity: 每个通道保留的最大样本数（单位：样本条数）。
    """

    def __init__(self, capacity: int = 4096) -> None:
        if capacity <= 0:
            raise ValueError("capacity 必须为正整数（单位：样本条数）")
        self._capacity = capacity
        self._channels: Dict[str, deque[Reading]] = {}
        self._latest: Dict[str, Reading] = {}
        self._total_pushed = 0

    def push(self, reading: Reading) -> None:
        """写入一条读数（同步快速路径）。"""
        buf = self._channels.get(reading.channel)
        if buf is None:
            buf = deque(maxlen=self._capacity)
            self._channels[reading.channel] = buf
        buf.append(reading)
        self._latest[reading.channel] = reading
        self._total_pushed += 1

    def latest(self, channel: str) -> Optional[Reading]:
        """返回某通道最新读数，无数据返回 None。"""
        return self._latest.get(channel)

    def latest_all(self) -> Dict[str, Reading]:
        """返回所有通道最新读数的映射副本。"""
        return dict(self._latest)

    def history(self, channel: str, limit: Optional[int] = None) -> List[Reading]:
        """按时间升序返回某通道历史（副本）。

        Args:
            channel: 逻辑通道名。
            limit: 返回最近 N 条；None 表示返回全部（不超过 capacity）。
        """
        buf = self._channels.get(channel)
        if buf is None:
            return []
        items = list(buf)
        if limit is not None:
            items = items[-limit:]
        return items

    def channels(self) -> List[str]:
        """返回存在数据的通道名列表。"""
        return list(self._channels.keys())

    @property
    def total_pushed(self) -> int:
        """累计写入样本总数。"""
        return self._total_pushed