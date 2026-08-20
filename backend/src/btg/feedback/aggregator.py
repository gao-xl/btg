"""设备反馈聚合器：汇聚执行器回传的反馈，提供快照、历史与健康度查询。

面向单 asyncio 事件循环使用。``record`` 为同步快速路径，在两次 ``await``
之间原子完成，故无需加锁。
"""
from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, List, Optional

from btg_sdk import DeviceFeedback

from .models import DeviceHealth, compute_health


class FeedbackAggregator:
    """按设备维度聚合反馈，并派生健康度快照。

    Attributes:
        history_size: 每设备保留的最大反馈条数。
        stale_after_seconds: 超过该时长无新反馈即判定设备 ``STALE``。
    """

    def __init__(self, *, history_size: int = 64, stale_after_seconds: float = 30.0) -> None:
        if history_size <= 0:
            raise ValueError("history_size 必须为正整数")
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds 必须为正数（单位：秒）")
        self._history_size = history_size
        self._stale_after = stale_after_seconds
        self._latest: Dict[str, DeviceFeedback] = {}
        self._history: Dict[str, Deque[DeviceFeedback]] = {}

    def record(self, feedback: DeviceFeedback) -> None:
        """写入一条设备反馈（同步快速路径）。"""
        self._latest[feedback.device_id] = feedback
        buf = self._history.get(feedback.device_id)
        if buf is None:
            buf = deque(maxlen=self._history_size)
            self._history[feedback.device_id] = buf
        buf.append(feedback)

    def latest(self, device_id: str) -> Optional[DeviceFeedback]:
        """返回某设备最近一条反馈，无数据返回 None。"""
        return self._latest.get(device_id)

    def latest_all(self) -> Dict[str, DeviceFeedback]:
        """返回所有设备最近反馈的映射副本。"""
        return dict(self._latest)

    def device_ids(self) -> List[str]:
        """返回存在反馈的设备标识列表。"""
        return list(self._latest.keys())

    def history(self, device_id: str, limit: Optional[int] = None) -> List[DeviceFeedback]:
        """按时间升序返回某设备反馈历史（副本）。"""
        buf = self._history.get(device_id)
        if buf is None:
            return []
        items = list(buf)
        if limit is not None:
            items = items[-limit:]
        return items

    def health(self, device_id: str, *, now: Optional[float] = None) -> str:
        """返回某设备当前健康度。"""
        return compute_health(
            self._latest.get(device_id),
            now=now if now is not None else time.time(),
            stale_after_seconds=self._stale_after,
        )

    def snapshot(self, *, now: Optional[float] = None) -> Dict[str, Dict[str, object]]:
        """返回所有设备的最新反馈与健康度快照（可直接 JSON 序列化）。"""
        current = now if now is not None else time.time()
        result: Dict[str, Dict[str, object]] = {}
        for device_id, feedback in self._latest.items():
            result[device_id] = {
                "kind": feedback.kind,
                "channel": feedback.channel,
                "value": feedback.value,
                "unit": feedback.unit,
                "message": feedback.message,
                "timestamp": feedback.timestamp,
                "health": self.health(device_id, now=current),
            }
        return result

    def reset(self) -> None:
        """清空所有反馈（供测试隔离或模式切换后重启）。"""
        self._latest.clear()
        self._history.clear()