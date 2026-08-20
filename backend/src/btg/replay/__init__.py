"""历史心率与惩罚复盘曲线（Timeline & Replay / Session Log）。

赛车级 Telemetry 会话回放：录制生理指标/硬件状态/AI 动作三轨道遥测，
在同一时间轴上渲染多维时空对齐画布，并导出含 SVG 与黑盒日志的报告包。

对外暴露稳定句柄：

- :class:`btg.replay.models.SessionFrame`：会话遥测帧契约；
- :class:`btg.replay.recorder.SessionLog`：单会话录制缓冲；
- :class:`btg.replay.service.ReplayService`：会话录制/回放注册中心；
- :func:`btg.replay.report.export_report_zip`：全息体征报告导出。
"""
from __future__ import annotations

from .models import (
    HARDWARE_CHANNELS,
    PHYSIO_CHANNELS,
    TRACKS,
    SessionFrame,
    SessionSummary,
    Track,
    classify_channel,
)
from .recorder import SessionLog
from .report import export_report_zip, render_session_svg
from .service import ReplayService, ReplayServiceError

__all__ = [
    "TRACKS",
    "Track",
    "PHYSIO_CHANNELS",
    "HARDWARE_CHANNELS",
    "SessionFrame",
    "SessionSummary",
    "classify_channel",
    "SessionLog",
    "render_session_svg",
    "export_report_zip",
    "ReplayService",
    "ReplayServiceError",
]