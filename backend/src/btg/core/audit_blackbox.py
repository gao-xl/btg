"""黑盒审计日志：进程内「飞行数据记录器」。

采用内存环形缓冲，保留最近约 1 小时的系统状态帧（可配置）。每条帧除时间戳
外还带因果链指针（``parent_id``），把「触发原因 ➔ 执行动作 ➔ 结果」串成可
回溯的因果链，供事后复盘、安全审计与报告导出使用。

与 :class:`TelemetryRingBuffer`（高频遥测样本）不同，黑盒记录的是低频的安全
决策 / 软降级 / 硬急停 / 复位等关键状态帧，侧重因果性与可审计性。
"""
from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True, slots=True)
class AuditFrame:
    """一条黑盒状态帧。

    Attributes:
        frame_id: 全局自增帧编号（``ID_<n>``）。
        timestamp: 记录时间（Unix epoch 秒）。
        event: 事件名（如 ``soft_degrade`` / ``hard_interlock``）。
        cause: 触发原因（如 ``heart_rate_critical value=165 consecutive=3``）。
        action: 采取的动作（如 ``zero_out_all_actuators``）。
        result: 结果（如 ``all_channels=0``）。
        parent_id: 因果链上游帧编号（缺省自动链接到前一帧）。
        data: 附加结构化数据。
    """

    frame_id: str
    timestamp: float
    event: str
    cause: str
    action: str
    result: str
    parent_id: Optional[str]
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.frame_id,
            "timestamp": self.timestamp,
            "event": self.event,
            "cause": self.cause,
            "action": self.action,
            "result": self.result,
            "parent_id": self.parent_id,
            "data": self.data,
        }


class AuditBlackbox:
    """面向单事件循环的黑盒环形缓冲。

    写入为同步快速路径；按时间窗（默认 1 小时）与最大帧数双重约束淘汰
    旧帧。同一次安全事件序列通过 ``parent_id`` 自动连成因果链。
    """

    def __init__(self, *, retention_seconds: float = 3600.0, max_frames: int = 10000) -> None:
        if retention_seconds <= 0:
            raise ValueError("retention_seconds 必须为正数")
        if max_frames <= 0:
            raise ValueError("max_frames 必须为正整数")
        self._retention_seconds = retention_seconds
        self._max_frames = max_frames
        self._frames: deque[AuditFrame] = deque()
        self._seq = 0

    def record(
        self,
        event: str,
        *,
        cause: str = "",
        action: str = "",
        result: str = "",
        parent_id: Optional[str] = None,
        **data: Any,
    ) -> AuditFrame:
        """写入一条帧，若未指定 ``parent_id`` 则自动链接到前一帧。"""
        self._seq += 1
        frame_id = f"ID_{self._seq}"
        if parent_id is None and self._frames:
            parent_id = self._frames[-1].frame_id
        self._frames.append(
            AuditFrame(
                frame_id=frame_id,
                timestamp=time.time(),
                event=event,
                cause=cause,
                action=action,
                result=result,
                parent_id=parent_id,
                data=dict(data),
            )
        )
        self._evict()
        return self._frames[-1]

    def _evict(self) -> None:
        cutoff = time.time() - self._retention_seconds
        while self._frames and self._frames[0].timestamp < cutoff:
            self._frames.popleft()
        while len(self._frames) > self._max_frames:
            self._frames.popleft()

    def frames(self) -> List[AuditFrame]:
        """返回当前全部帧（副本，按时间升序）。"""
        return list(self._frames)

    def snapshot(self) -> List[Dict[str, Any]]:
        """返回全部帧的可序列化字典列表。"""
        return [f.to_dict() for f in self._frames]

    def last_frame_id(self) -> Optional[str]:
        """返回最近一帧的编号，无帧返回 None。"""
        return self._frames[-1].frame_id if self._frames else None

    def export_json(self) -> str:
        """导出全部帧为 JSON 字符串（供报告/复盘）。"""
        return json.dumps(self.snapshot(), ensure_ascii=False)

    @staticmethod
    def frame_text(frame: AuditFrame) -> str:
        """将单帧渲染为人类可读的因果描述。"""
        parts = [frame.frame_id]
        if frame.cause:
            parts.append(f"触发原因 = {frame.cause}")
        if frame.action:
            parts.append(f"动作 = {frame.action}")
        if frame.result:
            parts.append(f"结果 = {frame.result}")
        return " ➔ ".join(parts)

    def chain(self, frame_id: str) -> List[AuditFrame]:
        """沿 ``parent_id`` 回溯某帧的因果链（由远及近）。"""
        by_id = {f.frame_id: f for f in self._frames}
        chain: List[AuditFrame] = []
        current = by_id.get(frame_id)
        while current is not None:
            chain.append(current)
            current = by_id.get(current.parent_id) if current.parent_id else None
        return list(reversed(chain))

    def __len__(self) -> int:
        return len(self._frames)