"""复盘曲线注册中心：会话录制、回放查询与报告导出。

单次会话由 :class:`SessionLog` 存管；服务按 ``session_id`` 维护有限数量
会话。录制通过 ``record_reading``（遥测自动归类轨道）与 ``record_ai``
（AI 动作/台词标记）两条快速路径写入"当前录制中的会话"；无活动会话时
静默跳过，避免影响采集热路径。
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Mapping, Optional

from .models import SessionFrame, classify_channel
from .recorder import SessionLog
from .report import export_report_zip, render_session_svg


class ReplayServiceError(ValueError):
    """复盘曲线注册中心的预期业务错误。"""


class ReplayService:
    """内存版会话录制/回放注册中心（单机网关运行期存管）。"""

    def __init__(
        self,
        *,
        max_sessions: int = 64,
        max_frames: int = 20000,
        clock: Optional[Any] = None,
    ) -> None:
        self._sessions: Dict[str, SessionLog] = {}
        self._active_id: Optional[str] = None
        self._max_sessions = max_sessions
        self._max_frames = max_frames
        self._clock = clock or time.time

    # ------------------------------------------------------------------ #
    # 会话生命周期
    # ------------------------------------------------------------------ #
    def start_session(self, *, tags: Optional[List[str]] = None) -> SessionLog:
        """开启一个新录制会话（关闭上一个活动会话；自动生成唯一 id）。"""
        if self._active_id is not None:
            self._sessions[self._active_id].end()
        session_id = f"sess_{int(self._clock())}_{uuid.uuid4().hex[:6]}"
        session = SessionLog(session_id, started_at=self._clock(), tags=tags, max_frames=self._max_frames)
        self._sessions[session_id] = session
        self._active_id = session_id
        self._evict()
        return session

    def end_session(self, session_id: str) -> SessionLog:
        """结束指定会话（幂等）。"""
        session = self.get(session_id)
        session.end()
        if self._active_id == session_id:
            self._active_id = None
        return session

    def active_session(self) -> Optional[SessionLog]:
        """返回当前录制中的会话，无则 None。"""
        if self._active_id is None:
            return None
        return self._sessions.get(self._active_id)

    def active_session_id(self) -> Optional[str]:
        return self._active_id

    def delete_session(self, session_id: str) -> None:
        if session_id not in self._sessions:
            raise ReplayServiceError(f"session not found: {session_id}")
        if self._active_id == session_id:
            self._active_id = None
        del self._sessions[session_id]

    def _evict(self) -> None:
        while len(self._sessions) > self._max_sessions:
            oldest = next(
                (k for k in self._sessions if k != self._active_id),
                None,
            )
            if oldest is None:
                break
            del self._sessions[oldest]

    # ------------------------------------------------------------------ #
    # 录制
    # ------------------------------------------------------------------ #
    def record_frame(self, frame: SessionFrame) -> None:
        """写入一条帧到活动会话（无活动会话则静默跳过）。"""
        session = self.active_session()
        if session is not None:
            session.append(frame)

    def record_reading(self, reading: Any) -> None:
        """把一条遥测读数归类到轨道并写入活动会话。

        ``reading`` 需具备 ``channel`` / ``value`` / ``unit`` / ``timestamp`` 属性；
        无法归为 ``physio`` / ``hardware`` 轨道的通道被忽略。
        """
        session = self.active_session()
        if session is None:
            return
        track = classify_channel(reading.channel)
        if track is None:
            return
        session.push(
            timestamp=reading.timestamp,
            track=track,
            kind=reading.channel,
            value=reading.value,
            unit=getattr(reading, "unit", "") or "",
            sensor_id=getattr(reading, "sensor_id", ""),
            **dict(getattr(reading, "extra", None) or {}),
        )

    def record_ai(self, kind: str, value: Any = None, *, timestamp: Optional[float] = None, **meta: Any) -> None:
        """写入一条 AI 动作/台词标记到活动会话。"""
        session = self.active_session()
        if session is None:
            return
        session.push(
            timestamp=timestamp if timestamp is not None else self._clock(),
            track="ai",
            kind=kind,
            value=value,
            **meta,
        )

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def get(self, session_id: str) -> SessionLog:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise ReplayServiceError(f"session not found: {session_id}") from exc

    def list(self) -> List[dict]:
        """返回全部会话轻量元数据（按开始时间倒序）。"""
        sessions = sorted(self._sessions.values(), key=lambda s: s.started_at, reverse=True)
        return [s.summary() for s in sessions]

    def count(self) -> int:
        return len(self._sessions)

    # ------------------------------------------------------------------ #
    # 回放 / 导出
    # ------------------------------------------------------------------ #
    def frames(self, session_id: str, *, track: Optional[str] = None, kind: Optional[str] = None) -> List[dict]:
        return [f.model_dump() for f in self.get(session_id).frames(track=track, kind=kind)]

    def series(self, session_id: str, kind: str, *, track: Optional[str] = None) -> List[List[float]]:
        """返回某指标 ``[[timestamp, value], ...]`` 数值序列。"""
        return [[t, v] for t, v in self.get(session_id).series(kind, track=track)]

    def render_svg(self, session_id: str) -> str:
        return render_session_svg(self.get(session_id))

    def export_report(self, session_id: str, *, blackbox_snapshot: Optional[List[Dict[str, Any]]] = None) -> bytes:
        return export_report_zip(self.get(session_id), blackbox_snapshot=blackbox_snapshot)


__all__ = ["ReplayService", "ReplayServiceError"]