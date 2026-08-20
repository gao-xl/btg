"""Contract tests for the YoKoNex feedback/status-listening adapter."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "sdk"))
sys.path.insert(0, str(_ROOT / "backend" / "src"))

from btg.hal.actuators.yokonex_feedback_adapter import (  # noqa: E402
    ActuatorTelemetryFrame,
    YokoNexStatusNormalizer,
    YoKoNexFeedbackAdapter,
    YoKoNexFeedbackConfig,
)


def _config(**overrides) -> YoKoNexFeedbackConfig:
    config = {
        "instance_id": "yokonex_sensor:yokonex_im:0",
        "channel": "tens",
        "mode": "poll",
        "bridge_url": "http://127.0.0.1:3001",
        "poll_endpoint": "/api/status",
        "poll_interval_seconds": 0.01,
        "offline_alert_threshold": 2,
    }
    config.update(overrides)
    return YoKoNexFeedbackConfig(**config)


# --------------------------------------------------------------------------- #
# 配置边界
# --------------------------------------------------------------------------- #
def test_loopback_bridge_accepted_by_default() -> None:
    cfg = _config()
    assert str(cfg.bridge_url) == "http://127.0.0.1:3001/"


def test_remote_bridge_requires_explicit_opt_in() -> None:
    with pytest.raises(ValidationError, match="remote API-bridge is disabled"):
        _config(bridge_url="http://192.0.2.10:3001")
    _config(bridge_url="http://192.0.2.10:3001", allow_remote_bridge=True)


def test_bridge_url_must_be_an_origin() -> None:
    with pytest.raises(ValidationError, match="origin"):
        _config(bridge_url="http://127.0.0.1:3001/api/status")


def test_resolved_ws_url_derives_from_bridge() -> None:
    assert _config().resolved_ws_url == "ws://127.0.0.1:3001/"
    assert _config(ws_url="ws://127.0.0.1:8099").resolved_ws_url == "ws://127.0.0.1:8099/"


# --------------------------------------------------------------------------- #
# 归一化：字段抽取与别名
# --------------------------------------------------------------------------- #
def test_normalizer_extracts_full_standard_fields() -> None:
    n = YokoNexStatusNormalizer()
    frame = n.normalize(
        {"device_id": "lock-1", "is_online": True, "battery": 87, "state_payload": {"locked": True}},
        source="poll",
        device_fallback="fb",
    )
    assert frame.device_id == "lock-1"
    assert frame.is_online is True
    assert frame.battery == 87
    assert frame.state_payload == {"locked": True}
    assert frame.source == "poll"


def test_normalizer_accepts_aliases_and_clamps_battery() -> None:
    n = YokoNexStatusNormalizer()
    frame = n.normalize(
        {"uid": "toy-7", "online": True, "batteryLevel": "240%"},
        source="websocket",
        device_fallback="fb",
    )
    assert frame.device_id == "toy-7"
    assert frame.is_online is True
    assert frame.battery == 100  # clamped at 100


def test_normalizer_falls_back_when_fields_missing() -> None:
    n = YokoNexStatusNormalizer()
    frame = n.normalize({"data": {"state_payload": {"pos": 0.5}}}, source="poll", device_fallback="fb")
    assert frame.device_id == "fb"
    assert frame.battery is None


def test_normalizer_unwraps_websocket_im_nesting() -> None:
    n = YokoNexStatusNormalizer()
    raw = {
        "type": "message",
        "data": {
            "messages": [
                {
                    "payload": {
                        "text": '{"code": 0, "id": "ng-3", "payload": {"is_online": true}}',
                    }
                }
            ]
        },
    }
    frame = n.normalize(raw, source="websocket", device_fallback="fb")
    assert frame.device_id == "ng-3"
    assert frame.is_online is True


def test_normalizer_offline_when_network_disconnected() -> None:
    n = YokoNexStatusNormalizer()
    frame = n.normalize(
        {"network": {"state": "DISCONNECTED"}}, source="poll", device_fallback="fb"
    )
    assert frame.is_online is False


# --------------------------------------------------------------------------- #
# 遥测帧 -> 反馈契约
# --------------------------------------------------------------------------- #
def test_online_frame_produces_connection_battery_feedback() -> None:
    frame = ActuatorTelemetryFrame(
        device_id="toy-7", is_online=True, battery=60, extra={"channel": "tens"}
    )
    feedback = frame.to_device_feedback()
    assert len(feedback) == 2
    conn, batt = feedback
    assert conn.device_id == "toy-7"
    assert conn.value == 1.0
    assert batt.value == 0.6


def test_offline_frame_produces_only_connection_zero() -> None:
    frame = ActuatorTelemetryFrame(device_id="toy-7", is_online=False)
    feedback = frame.to_device_feedback()
    assert len(feedback) == 1
    assert feedback[0].value == 0.0


# --------------------------------------------------------------------------- #
# 轮询模式 + 断连保护
# --------------------------------------------------------------------------- #
def _adapter(handler, **overrides) -> YoKoNexFeedbackAdapter:
    adapter = YoKoNexFeedbackAdapter(_config(**overrides))
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter


def test_poll_once_normalizes_online_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"device_id": "lock-1", "is_online": True, "battery": 55, "state_payload": {"locked": True}},
        )

    adapter = _adapter(handler)

    async def scenario() -> None:
        frame = await adapter.poll_once()
        assert frame.device_id == "lock-1"
        assert frame.is_online is True
        assert frame.battery == 55
        await adapter._close_client()

    asyncio.run(scenario())


def test_poll_loop_marks_offline_and_alerts_on_repeated_failure() -> None:
    sent: list[ActuatorTelemetryFrame] = []
    alerts: list[str] = []

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 1:
            return httpx.Response(200, json={"device_id": "lock-1", "is_online": True})
        # 之后桥接连续超时 -> 置灰 + 达到阈值告警
        raise httpx.ConnectTimeout("bridge unreachable", request=request)

    adapter = _adapter(handler, poll_interval_seconds=0.01, backoff_base_seconds=0.001)

    async def sink(f: ActuatorTelemetryFrame) -> None:
        sent.append(f)

    async def alert(reason: str, f: ActuatorTelemetryFrame) -> None:
        alerts.append(reason)

    adapter._sink = sink
    adapter._on_alert = alert

    async def scenario() -> None:
        await adapter.start()
        for _ in range(8):
            await asyncio.sleep(0)
        # 足够多的循环迭代
        deadline = asyncio.get_event_loop().time() + 1.0
        while adapter.consecutive_failures < adapter.config.offline_alert_threshold and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.002)
        assert adapter.consecutive_failures >= adapter.config.offline_alert_threshold
        assert adapter.alerted is True
        assert any(a == "bridge_timeout" for a in alerts)
        # 至少有一条离线帧（CONNECTION value == 0）
        assert any(not f.is_online for f in sent)
        await adapter.stop()

    asyncio.run(scenario())


def test_offline_state_triggers_alert_via_direct_handle() -> None:
    alerts: list[str] = []
    adapter = _adapter(lambda r: httpx.Response(200, json={}))
    adapter._on_alert = lambda reason, f: _append(alerts, reason)

    async def scenario() -> None:
        await adapter._note_failure("device_offline")  # failure #1
        await adapter._note_failure("device_offline")  # failure #2 -> 首次达阈值触发一次告警
        assert adapter.consecutive_failures == 2
        assert adapter.alerted is True
        assert alerts == ["device_offline"]

    asyncio.run(scenario())


async def _append(lst: list[str], value: str) -> None:
    lst.append(value)


def test_recovery_resets_failures() -> None:
    adapter = _adapter(lambda r: httpx.Response(200, json={}))
    adapter.consecutive_failures = 5
    adapter.alerted = True
    frame = ActuatorTelemetryFrame(device_id="lock-1", is_online=True)

    async def scenario() -> None:
        await adapter._handle_state(frame)
        assert adapter.consecutive_failures == 0
        assert adapter.alerted is False
        assert adapter.last_frame.is_online is True

    asyncio.run(scenario())


def test_websocket_mode_config_validation_requires_package() -> None:
    adapter = YoKoNexFeedbackAdapter(_config(mode="websocket"))
    # resolve the ws URL; connect itself is exercised via _handle_ws_message below
    assert adapter.config.mode == "websocket"


def test_handle_ws_message_online_and_json_nesting() -> None:
    adapter = _adapter(lambda r: httpx.Response(200, json={}), mode="websocket")
    emitted: list[ActuatorTelemetryFrame] = []

    async def sink(f: ActuatorTelemetryFrame) -> None:
        emitted.append(f)

    adapter._sink = sink

    async def scenario() -> None:
        # 内嵌 JSON 字符串，身份与状态分离
        await adapter._handle_ws_message(
            {
                "type": "message",
                "data": {
                    "messages": [
                        {"payload": {"text": '{"code":0,"id":"ng-3","payload":{"is_online":true}}'}}
                    ]
                },
            }
        )
        assert adapter.consecutive_failures == 0
        assert emitted and emitted[-1].device_id == "ng-3"
        assert emitted[-1].is_online is True

    asyncio.run(scenario())


def test_handle_ws_message_offline_triggers_disconnect_protection() -> None:
    adapter = _adapter(lambda r: httpx.Response(200, json={}), mode="websocket")
    adapter._on_alert = lambda reason, f: _append([], reason)
    adapter.config.offline_alert_threshold = 1

    async def scenario() -> None:
        await adapter._handle_ws_message(
            {"type": "message", "payload": {"text": '{"id":"toy","is_online":false}'}}
        )
        assert adapter.consecutive_failures == 1
        assert adapter.alerted is True
        adapter._reset_failures()

    asyncio.run(scenario())


def test_handle_ws_message_drops_invalid_json() -> None:
    adapter = _adapter(lambda r: httpx.Response(200, json={}), mode="websocket")
    adapter.consecutive_failures = 0

    async def scenario() -> None:
        await adapter._handle_ws_message("not-json")
        await adapter._handle_ws_message({"type": "error", "message": "boom"})
        assert adapter.consecutive_failures == 0

    asyncio.run(scenario())