"""单个会话的录制缓冲：内存环形存管时间有序的遥测帧。

面向单 asyncio 事件循环；``append`` 为同步快速路径，超限自动覆盖最旧帧。
"""
from __future__ import annotations

import time
from collections import deque
from typing import Iterable, List, Optional, Tuple

from .models import SessionFrame, SessionSummary


class SessionLog:
    """单次会话的时间对齐遥测录制（三轨道合一）。"""

    def __init__(
        self,
        session_id: str,
        *,
        started_at: Optional[float] = None,
        tags: Optional[Iterable[str]] = None,
        max_frames: int = 20000,
    ) -> None:
        if max_frames <= 0:
            raise ValueError("max_frames 必须为正整数")
        self.session_id = session_id
        self.started_at = started_at if started_at is not None else time.time()
        self._tags: List[str] = list(tags or [])
        self._max_frames = max_frames
        self._frames: deque[SessionFrame] = deque(maxlen=max_frames)
        self._ended_at: Optional[float] = None

    # ------------------------------------------------------------------ #
    # 写入
    # ------------------------------------------------------------------ #
    def append(self, frame: SessionFrame) -> SessionFrame:
        """追加一帧（同步快速路径，超限覆盖最旧）。"""
        self._frames.append(frame)
        return frame

    def push(self, *, timestamp: float, track: str, kind: str, value=None, unit: str = "", **meta) -> SessionFrame:
        """以关键字参数构造并追加一帧。"""
        return self.append(
            SessionFrame(timestamp=timestamp, track=track, kind=kind, value=value, unit=unit, meta=dict(meta))
        )

    def end(self, *, ended_at: Optional[float] = None) -> None:
        """结束录制（幂等）。"""
        if self._ended_at is None:
            self._ended_at = ended_at if ended_at is not None else time.time()

    # ------------------------------------------------------------------ #
    # 读取
    # ------------------------------------------------------------------ #
    @property
    def status(self) -> str:
        return "ended" if self._ended_at is not None else "recording"

    @property
    def ended_at(self) -> Optional[float]:
        return self._ended_at

    @property
    def tags(self) -> List[str]:
        return list(self._tags)

    def frames(self, *, track: Optional[str] = None, kind: Optional[str] = None) -> List[SessionFrame]:
        """按轨道/指标筛选帧（时间升序副本）。"""
        items: List[SessionFrame] = []
        for frame in self._frames:
            if track is not None and frame.track != track:
                continue
            if kind is not None and frame.kind != kind:
                continue
            items.append(frame)
        return items

    def series(self, kind: str, *, track: Optional[str] = None) -> List[Tuple[float, float]]:
        """返回某指标的 ``(timestamp, value)`` 数值序列（仅保留数值帧）。"""
        result: List[Tuple[float, float]] = []
        for frame in self.frames(track=track, kind=kind):
            if isinstance(frame.value, (int, float)) and not isinstance(frame.value, bool):
                result.append((frame.timestamp, float(frame.value)))
        return result

    def numeric_series(self, kind: str, *, track: Optional[str] = None) -> List[Tuple[float, float]]:
        """``series`` 的别名（相对时间不在此处理，报告层自行归一）。"""
        return self.series(kind, track=track)

    def summary(self) -> dict:
        """返回会话轻量元数据字典。"""
        return SessionSummary(
            session_id=self.session_id,
            started_at=self.started_at,
            ended_at=self._ended_at,
            status=self.status,
            tags=list(self._tags),
            frame_count=len(self._frames),
        ).model_dump()

    def to_dict(self) -> dict:
        """返回完整会话（含全部帧）的可序列化字典。"""
        return {
            **self.summary(),
            "frames": [f.model_dump() for f in self._frames],
        }

    def __len__(self) -> int:
        return len(self._frames)


__all__ = ["SessionLog"]