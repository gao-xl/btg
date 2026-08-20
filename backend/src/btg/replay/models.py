"""历史心率与惩罚复盘曲线：会话遥测数据契约。

一条会话由时间有序的 :class:`SessionFrame` 组成，帧按轨道分组：

- ``physio``：生理指标（心率、IMU 挣扎加速度、视觉痛苦/挣扎评分）；
- ``hardware``：硬件状态（执行器 A/B 通道强度、物理位置、电量）；
- ``ai``：AI 动作与台词标记（话术、视觉代理缩略图引用）。

模型严格校验（``extra="forbid"``），供录制、回放与报告导出的统一契约。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: 轨道类型。
Track = Literal["physio", "hardware", "ai"]

TRACKS: tuple[str, ...] = ("physio", "hardware", "ai")

#: 归类为生理指标的遥测通道。
PHYSIO_CHANNELS = frozenset({
    "heart_rate",
    "imu_accel",
    "accel_x",
    "accel_y",
    "accel_z",
    "pain_score",
    "struggle_score",
})
#: 归类为硬件状态的遥测通道。
HARDWARE_CHANNELS = frozenset({
    "channel_a_level",
    "channel_b_level",
    "position",
    "battery_pct",
    "intensity",
})


def classify_channel(channel: str) -> str | None:
    """把逻辑通道名归类到 ``physio`` / ``hardware`` 轨道，无法判定返回 None。"""
    if channel in PHYSIO_CHANNELS:
        return "physio"
    if channel in HARDWARE_CHANNELS:
        return "hardware"
    low = channel.lower()
    if any(k in low for k in ("heart", "hr", "bpm", "pulse", "imu", "accel", "pain", "struggle")):
        return "physio"
    if any(k in low for k in ("channel", "level", "intensity", "position", "battery", "tens", "coyote")):
        return "hardware"
    return None


class SessionFrame(BaseModel):
    """一条会话遥测帧。

    Attributes:
        timestamp: 记录时间（Unix epoch 秒）。
        track: 轨道（``physio`` / ``hardware`` / ``ai``）。
        kind: 帧内指标/事件名（如 ``heart_rate`` / ``channel_a_level`` / ``ai_prompt``）。
        value: 数值或文本值；无值（纯标记）可为 None。
        unit: 数值单位（可选）。
        meta: 附加数据（如视觉代理缩略图引用 ``latest.jpg``）。
    """

    model_config = ConfigDict(extra="forbid")

    timestamp: float = Field(ge=0)
    track: Track
    kind: str = Field(min_length=1, max_length=64)
    value: float | str | None = None
    unit: str = Field(default="", max_length=32)
    meta: dict[str, Any] = Field(default_factory=dict)


class SessionSummary(BaseModel):
    """会话轻量元数据（列表/回放导航用，不含完整帧流）。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    started_at: float = Field(ge=0)
    ended_at: float | None = None
    status: Literal["recording", "ended"] = "recording"
    tags: list[str] = Field(default_factory=list)
    frame_count: int = Field(default=0, ge=0)


__all__ = [
    "TRACKS",
    "Track",
    "PHYSIO_CHANNELS",
    "HARDWARE_CHANNELS",
    "SessionFrame",
    "SessionSummary",
    "classify_channel",
]