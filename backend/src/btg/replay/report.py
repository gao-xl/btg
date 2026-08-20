"""复盘报告导出：多维时空对齐 SVG 画布 + JSON 黑盒日志压缩包。

无需任何第三方图表库依赖，直接生成自包含 SVG：在同一时间轴上渲染
生理指标、硬件状态、AI 动作三条平行轨道，并用时间对齐标记叠加。
"""
from __future__ import annotations

import io
import json
import zipfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .recorder import SessionLog

# ------------------------------------------------------------------ #
# 几何常量
# ------------------------------------------------------------------ #
WIDTH = 1000
HEIGHT = 660
MARGIN_LEFT = 78
MARGIN_RIGHT = 24
MARGIN_TOP = 44
MARGIN_BOTTOM = 52
LANE_GAP = 14
PLOT_X0 = MARGIN_LEFT
PLOT_X1 = WIDTH - MARGIN_RIGHT


def _lane_geometry(count: int, index: int) -> Tuple[float, float]:
    """返回第 ``index`` 条轨道的上下 Y 边界。"""
    total = HEIGHT - MARGIN_TOP - MARGIN_BOTTOM
    lane_h = (total - LANE_GAP * (count - 1)) / count
    top = MARGIN_TOP + index * (lane_h + LANE_GAP)
    return top, top + lane_h


def _ticks(lo: float, hi: float, n: int = 4) -> List[float]:
    """在 [lo, hi] 间生成 n 个均匀刻度值。"""
    if hi == lo:
        return [lo]
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def _y_scale(lo: float, hi: float, top: float, bottom: float) -> Any:
    """把数据值映射到 SVG 像素 Y；``lo==hi`` 时取常量中点。"""
    span = hi - lo
    if span <= 0:
        span = 1.0
    pad = span * 0.08
    lo, hi = lo - pad, hi + pad

    def to_y(value: float) -> float:
        return bottom - (value - lo) / (hi - lo) * (bottom - top)

    def text(value: float) -> str:
        if abs(value) >= 1000:
            return f"{value / 1000:.1f}k"
        return f"{value:.1f}"

    return {"to_y": to_y, "lo": lo, "hi": hi, "text": text}


def _x_scale(start: float, end: float, lane: Tuple[float, float]) -> Tuple[Any, Any]:
    """把绝对时间映射到 SVG 像素 X，并返回时间刻度格式化器。"""
    x0, x1 = PLOT_X0, PLOT_X1
    duration = end - start
    if duration <= 0:
        duration = 60.0

    def to_x(ts: float) -> float:
        return x0 + (ts - start) / duration * (x1 - x0)

    def fmt_secs(ts: float) -> str:
        secs = ts - start
        m, s = int(secs // 60), int(secs % 60)
        return f"{m}:{s:02d}"

    return to_x, fmt_secs


def _polyline(series: Sequence[Tuple[float, float]], to_x, to_y) -> str:
    if not series:
        return ""
    pts = [f"{to_x(t):.1f},{to_y(v):.1f}" for t, v in series]
    return " ".join(pts)


def _step(series: Sequence[Tuple[float, float]], to_x, to_y) -> str:
    """阶梯图：先横后纵，逼近真实输出强度阶梯。"""
    if not series:
        return ""
    pts: List[str] = []
    for i, (t, v) in enumerate(series):
        pts.append(f"{to_x(t):.1f},{to_y(v):.1f}")
        if i + 1 < len(series):
            pts.append(f"{to_x(series[i + 1][0]):.1f},{to_y(v):.1f}")
    return " ".join(pts)


def _extent(series_list: Sequence[Sequence[Tuple[float, float]]]) -> Tuple[float, float]:
    values = [v for s in series_list for _, v in s]
    if not values:
        return 0.0, 1.0
    return min(values), max(values)


def _lane_bg(top: float, bottom: float, label: str) -> str:
    return (
        f'<rect x="{PLOT_X0}" y="{top:.1f}" width="{PLOT_X1 - PLOT_X0:.1f}" '
        f'height="{bottom - top:.1f}" fill="#0e1420" rx="6" />'
        f'<text x="10" y="{(top + bottom) / 2:.1f}" fill="#8b98b8" font-size="12" '
        f'font-family="monospace" transform="rotate(-90 10 {(top + bottom) / 2:.1f})">{label}</text>'
    )


# ------------------------------------------------------------------ #
# SVG 渲染
# ------------------------------------------------------------------ #
def render_session_svg(session: SessionLog) -> str:
    """把会话渲染为三轨道时间对齐 SVG 字符串（空会话返回占位图）。"""
    frames = session.frames()
    if not frames:
        return _empty_svg(session.session_id)

    start = min(f.timestamp for f in frames)
    end = max(f.timestamp for f in frames)
    if end <= start:
        end = start + 60.0
    to_x, fmt_secs = _x_scale(start, end, (0, 0))

    hr = session.series("heart_rate")
    imu = session.series("imu_accel")
    pain = session.series("pain_score")
    ch_a = session.series("channel_a_level")
    ch_b = session.series("channel_b_level")
    pos = session.series("position")
    ai_frames = [
        f for f in frames if f.track == "ai" and f.kind in {"ai_prompt", "ai_line", "ai_visual"}
    ]

    physio_top, physio_bottom = _lane_geometry(3, 0)
    hw_top, hw_bottom = _lane_geometry(3, 1)
    ai_top, ai_bottom = _lane_geometry(3, 2)

    parts: List[str] = [_header(session)]
    parts.append(_lane_bg(physio_top, physio_bottom, "生理指标"))
    parts.append(_lane_bg(hw_top, hw_bottom, "硬件状态"))
    parts.append(_lane_bg(ai_top, ai_bottom, "AI 动作/台词"))

    # 轨道 1：心率折线 + IMU 挣扎峰值。
    physio_lo, physio_hi = _extent([hr, imu, pain])
    hr_scale = _y_scale(physio_lo, physio_hi, physio_top, physio_bottom)
    imu_lo, imu_hi = _extent([imu])
    imu_scale = _y_scale(imu_lo, imu_hi, physio_top, physio_bottom)
    parts.append(f'<polyline fill="none" stroke="#ff5c7a" stroke-width="2" '
                 f'points="{_polyline(hr, to_x, hr_scale["to_y"])}" />')
    for t, v in imu:
        x = to_x(t)
        y = imu_scale["to_y"](v)
        parts.append(f'<line x1="{x:.1f}" y1="{physio_bottom:.1f}" x2="{x:.1f}" y2="{y:.1f}" '
                     f'stroke="#ffb347" stroke-width="1.5" />')
    for tick in _ticks(hr_scale["lo"], hr_scale["hi"], 4):
        y = hr_scale["to_y"](tick)
        parts.append(f'<text x="{PLOT_X1 - 4:.1f}" y="{y + 3:.1f}" fill="#ff5c7a" font-size="10" '
                     f'text-anchor="end" font-family="monospace">{hr_scale["text"](tick)}</text>')

    # 轨道 2：A/B 通道阶梯 + 物理位置曲线。
    hw_lo, hw_hi = _extent([ch_a, ch_b, pos])
    hw_scale = _y_scale(hw_lo, hw_hi, hw_top, hw_bottom)
    parts.append(f'<polyline fill="none" stroke="#4dd0e1" stroke-width="2" '
                 f'points="{_step(ch_a, to_x, hw_scale["to_y"])}" />')
    parts.append(f'<polyline fill="none" stroke="#7c83ff" stroke-width="2" '
                 f'points="{_step(ch_b, to_x, hw_scale["to_y"])}" />')
    parts.append(f'<polyline fill="none" stroke="#9aa5b1" stroke-width="1.5" stroke-dasharray="4 3" '
                 f'points="{_polyline(pos, to_x, hw_scale["to_y"])}" />')
    for tick in _ticks(hw_scale["lo"], hw_scale["hi"], 4):
        y = hw_scale["to_y"](tick)
        parts.append(f'<text x="{PLOT_X1 - 4:.1f}" y="{y + 3:.1f}" fill="#4dd0e1" font-size="10" '
                     f'text-anchor="end" font-family="monospace">{hw_scale["text"](tick)}</text>')

    # 轨道 3：AI 标记点。
    parts.append(f'<line x1="{PLOT_X0:.1f}" y1="{(ai_top + ai_bottom) / 2:.1f}" '
                 f'x2="{PLOT_X1:.1f}" y2="{(ai_top + ai_bottom) / 2:.1f}" stroke="#2a3650" stroke-width="1" />')
    for f in ai_frames:
        x = to_x(f.timestamp)
        y = (ai_top + ai_bottom) / 2
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#ffb347" />')
        label = _truncate(_ai_label(f), 20)
        parts.append(f'<text x="{x:.1f}" y="{y - 8:.1f}" fill="#d8e0f0" font-size="9" '
                     f'text-anchor="middle" font-family="monospace">{_escape(label)}</text>')

    # 时间轴刻度。
    for i in range(6):
        ts = start + (end - start) * i / 5
        x = to_x(ts)
        parts.append(f'<line x1="{x:.1f}" y1="{HEIGHT - MARGIN_BOTTOM + 6:.1f}" '
                     f'x2="{x:.1f}" y2="{HEIGHT - MARGIN_BOTTOM - 2:.1f}" stroke="#3a4a6b" stroke-width="1" />')
        parts.append(f'<text x="{x:.1f}" y="{HEIGHT - MARGIN_BOTTOM + 20:.1f}" fill="#8b98b8" '
                     f'font-size="10" text-anchor="middle" font-family="monospace">{fmt_secs(ts)}</text>')

    # 图例。
    parts.append(_legend(hr, ch_a, ch_b, pos, imu, ai_frames))
    parts.append("</svg>")
    return "\n".join(parts)


def _header(session: SessionLog) -> str:
    summary = session.summary()
    duration = 0.0
    frames = session.frames()
    if frames:
        duration = max(f.timestamp for f in frames) - min(f.timestamp for f in frames)
    mins, secs = int(duration // 60), int(duration % 60)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="monospace">'
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#0a0f1a" />'
        f'<text x="{MARGIN_LEFT:.1f}" y="26" fill="#e6ecff" font-size="16" font-weight="bold">'
        f'{_escape(session.session_id)} - Telemetry Replay</text>'
        f'<text x="{PLOT_X1:.1f}" y="26" fill="#8b98b8" font-size="11" text-anchor="end">'
        f'status={summary["status"]} frames={summary["frame_count"]} duration={mins}:{secs:02d}</text>'
    )


def _legend(hr, ch_a, ch_b, pos, imu, ai_frames) -> str:
    items = [
        ("#ff5c7a", "heart_rate"),
        ("#ffb347", "imu_accel"),
        ("#4dd0e1", "channel_a"),
        ("#7c83ff", "channel_b"),
        ("#9aa5b1", "position"),
    ]
    x = PLOT_X0
    y = HEIGHT - 16
    parts: List[str] = []
    for color, label in items:
        parts.append(f'<rect x="{x:.1f}" y="{y - 8:.1f}" width="10" height="10" fill="{color}" />')
        parts.append(f'<text x="{x + 14:.1f}" y="{y:.1f}" fill="#8b98b8" font-size="10">{label}</text>')
        x += 90
    return "".join(parts)


def _ai_label(frame) -> str:
    if isinstance(frame.value, str):
        return f"AI: {frame.value}"
    return frame.kind


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _empty_svg(session_id: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="monospace">'
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#0a0f1a" />'
        f'<text x="50%" y="50%" fill="#8b98b8" font-size="16" text-anchor="middle">'
        f'{session_id}: no telemetry frames recorded</text></svg>'
    )


# ------------------------------------------------------------------ #
# 压缩包导出
# ------------------------------------------------------------------ #
def export_report_zip(session: SessionLog, *, blackbox_snapshot: Optional[List[Dict[str, Any]]] = None) -> bytes:
    """导出「全息体征报告」压缩包：SVG 画布 + 遥测 JSON + 黑盒 JSON + 清单。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("report.svg", render_session_svg(session))
        zf.writestr(
            "telemetry.json",
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
        )
        zf.writestr(
            "blackbox.json",
            json.dumps(blackbox_snapshot or [], ensure_ascii=False, indent=2),
        )
        zf.writestr(
            "manifest.json",
            json.dumps(session.summary(), ensure_ascii=False, indent=2),
        )
    return buf.getvalue()


__all__ = ["render_session_svg", "export_report_zip"]