"""复盘曲线冒烟测试：信道归类、会话录制、回放查询与报告导出。

独立运行：``python tests/test_replay.py``
pytest 运行：``pytest tests/``
"""
from __future__ import annotations

import io
import sys
import zipfile
from types import SimpleNamespace
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "sdk"))
sys.path.insert(0, str(_ROOT / "backend" / "src"))

import pytest  # noqa: E402

from btg.replay import (  # noqa: E402
    ReplayService,
    ReplayServiceError,
    SessionFrame,
    SessionLog,
    classify_channel,
    render_session_svg,
)


def _reading(channel: str, value: float, ts: float = 1000.0) -> SimpleNamespace:
    return SimpleNamespace(
        channel=channel, value=value, unit="bpm", timestamp=ts, sensor_id=f"{channel}:mock:0", extra={}
    )


# ------------------------------------------------------------------ #
# 信道归类
# ------------------------------------------------------------------ #
@pytest.mark.parametrize("channel", ["heart_rate", "imu_accel", "pain_score", "accel_x"])
def test_classify_physio(channel: str) -> None:
    assert classify_channel(channel) == "physio"


@pytest.mark.parametrize("channel", ["channel_a_level", "channel_b_level", "position", "battery_pct"])
def test_classify_hardware(channel: str) -> None:
    assert classify_channel(channel) == "hardware"


def test_classify_unknown() -> None:
    assert classify_channel("co2_ppm") is None
    assert classify_channel("skin_temp") is None


# ------------------------------------------------------------------ #
# 会话录制缓冲
# ------------------------------------------------------------------ #
def test_session_log_append_and_series() -> None:
    session = SessionLog("s1", started_at=0.0)
    assert session.status == "recording"
    session.push(timestamp=1.0, track="physio", kind="heart_rate", value=80.0)
    session.push(timestamp=2.0, track="physio", kind="heart_rate", value=90.0)
    assert len(session) == 2
    assert session.series("heart_rate") == [(1.0, 80.0), (2.0, 90.0)]
    session.end(ended_at=3.0)
    assert session.status == "ended"
    assert session.summary()["frame_count"] == 2


def test_session_log_filters_track_kind() -> None:
    session = SessionLog("s2", started_at=0.0)
    session.push(timestamp=1.0, track="physio", kind="heart_rate", value=80.0)
    session.push(timestamp=2.0, track="hardware", kind="channel_a_level", value=30.0)
    assert len(session.frames(track="hardware")) == 1
    assert len(session.frames(kind="heart_rate")) == 1


# ------------------------------------------------------------------ #
# 注册中心
# ------------------------------------------------------------------ #
def test_service_record_reading_and_ai() -> None:
    service = ReplayService()
    # 无活动会话时静默跳过。
    service.record_reading(_reading("heart_rate", 70.0))
    assert service.count() == 0

    session = service.start_session(tags=["hardcore"])
    assert service.active_session_id() == session.session_id
    service.record_reading(_reading("heart_rate", 80.0, 1.0))
    service.record_reading(_reading("imu_accel", 1.4, 2.0))
    service.record_reading(_reading("channel_a_level", 45.0, 3.0))
    service.record_ai("ai_prompt", "say something", timestamp=4.0)

    assert len(service.frames(session.session_id)) == 4
    assert service.series(session.session_id, "heart_rate") == [[1.0, 80.0]]
    ai = service.frames(session.session_id, track="ai")
    assert ai[0]["kind"] == "ai_prompt"
    assert ai[0]["value"] == "say something"


def test_service_end_and_list() -> None:
    service = ReplayService()
    sid = service.start_session().session_id
    service.end_session(sid)
    assert service.get(sid).status == "ended"
    assert service.list()[0]["session_id"] == sid
    assert service.count() == 1


def test_service_delete_and_not_found() -> None:
    service = ReplayService()
    sid = service.start_session().session_id
    service.delete_session(sid)
    with pytest.raises(ReplayServiceError):
        service.get(sid)
    with pytest.raises(ReplayServiceError):
        service.end_session(sid)


def test_start_new_session_closes_previous() -> None:
    service = ReplayService()
    first = service.start_session()
    service.start_session()
    assert first.status == "ended"
    assert service.count() == 2


# ------------------------------------------------------------------ #
# 报告导出
# ------------------------------------------------------------------ #
def test_render_svg_empty_and_filled() -> None:
    empty = SessionLog("empty", started_at=0.0)
    assert "<svg" in render_session_svg(empty)

    session = SessionLog("filled", started_at=1000.0)
    for i, hr in enumerate([80, 90, 110, 130, 150, 140]):
        session.push(timestamp=1000.0 + i, track="physio", kind="heart_rate", value=float(hr))
        session.push(timestamp=1000.0 + i, track="hardware", kind="channel_a_level", value=float(20 + i * 5))
    session.push(timestamp=1002.0, track="ai", kind="ai_prompt", value="mock line")
    svg = render_session_svg(session)
    assert "<svg" in svg
    assert "heart_rate" in svg and "channel_a" in svg


def test_export_report_zip() -> None:
    service = ReplayService()
    sid = service.start_session().session_id
    service.record_reading(_reading("heart_rate", 120.0, 1.0))
    service.record_ai("ai_prompt", "line", timestamp=2.0)
    service.end_session(sid)

    payload = service.export_report(sid, blackbox_snapshot=[{"id": "ID_1"}])
    assert isinstance(payload, bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())
    assert {"report.svg", "telemetry.json", "blackbox.json", "manifest.json"} <= names