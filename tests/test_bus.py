"""总线层冒烟测试：REST 状态/设备/指令、第三方控制入口与 WebSocket 遥测流。

独立运行：``python tests/test_bus.py``
pytest 运行：``pytest tests/``
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "sdk", _ROOT / "backend" / "src", _ROOT / "tests"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from fastapi.testclient import TestClient  # noqa: E402

from btg.bus.app import create_app  # noqa: E402
from helpers import build_gateway  # noqa: E402


def _app():
    return create_app(build_gateway(Path(tempfile.mkdtemp()), base_value=80.0))


def test_state_endpoint() -> None:
    client = TestClient(_app())
    resp = client.get("/api/v1/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["code"] == 200
    assert body["data"]["state"] == "init"


def test_devices_endpoint() -> None:
    client = TestClient(_app())
    resp = client.get("/api/v1/devices")
    assert resp.status_code == 200
    channels = resp.json()["data"]
    kinds = {c["channel"]: c["kind"] for c in channels}
    assert kinds["heart_rate"] == "sensor"
    assert kinds["tens_intensity"] == "actuator"


def test_command_clamped() -> None:
    client = TestClient(_app())
    # max_intensity 默认 50，clamp 上限 50 → 80 被截断为 50
    resp = client.post("/api/v1/command", json={"channel": "tens_intensity", "value": 80.0, "unit": "mA"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"]["channel"] == "tens_intensity"
    assert body["data"]["value"] == 50.0
    assert body["data"]["clamped"] is True


def test_command_unknown_channel() -> None:
    client = TestClient(_app())
    resp = client.post("/api/v1/command", json={"channel": "no_such_channel", "value": 1.0})
    assert resp.status_code == 400
    error = resp.json()
    assert error["status"] == "error"
    assert error["error"]["type"] == "invalid_command"


def test_command_invalid_body() -> None:
    client = TestClient(_app())
    resp = client.post("/api/v1/command", json={"channel": "tens_intensity"})  # 缺少 value
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "validation_error"


def test_integration_control_clamped() -> None:
    client = TestClient(_app())
    resp = client.post("/integration/v1/control", json={"channel": "tens_intensity", "value": 90.0, "unit": "mA"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["value"] == 50.0
    assert body["data"]["clamped"] is True


def test_websocket_stream() -> None:
    app = _app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            snapshot = ws.receive_json()
            assert snapshot.get("state") is not None
            message = ws.receive_json()
            assert message.get("type") in ("telemetry", "state_change")


def test_agent_control_clamped() -> None:
    client = TestClient(_app())
    resp = client.post("/api/v1/control/actuators", json={
        "session_id": "s-1",
        "source": "scenario_agent",
        "scenario_id": "demo",
        "scene_id": "start",
        "channel": "tens_intensity",
        "value": 90.0,
        "unit": "mA",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["value"] == 50.0
    assert body["data"]["clamped"] is True
    assert body["data"]["scenario_id"] == "demo"


def test_agent_control_rejects_unknown_source() -> None:
    client = TestClient(_app())
    resp = client.post("/api/v1/control/actuators", json={
        "session_id": "s-1",
        "source": "rogue_agent",
        "scenario_id": "demo",
        "scene_id": "start",
        "channel": "tens_intensity",
        "value": 10.0,
        "unit": "mA",
    })
    assert resp.status_code == 422


def test_ws_events_stream_and_publish_roundtrip() -> None:
    app = _app()
    marker = {"type": "tts.request", "scenario_id": "demo", "text": "hello"}
    with TestClient(app) as client:
        with client.websocket_connect("/ws/events") as events_ws:
            snapshot = events_ws.receive_json()
            assert snapshot.get("state") is not None
            with client.websocket_connect("/ws/events/publish") as pub_ws:
                pub_ws.send_json(marker)
                for _ in range(50):
                    message = events_ws.receive_json()
                    if message.get("type") == "tts.request":
                        assert message["text"] == "hello"
                        break
                else:
                    raise AssertionError("published agent event never reached /ws/events")


def test_guardrails_endpoint() -> None:
    client = TestClient(_app())
    resp = client.get("/api/v1/guardrails")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    data = body["data"]
    assert data["degraded"] is False
    assert data["hard_triggered"] is False
    assert "config" in data
    assert "heart_rate_warn_bpm" in data["config"]


def test_state_snapshot_contains_guardrail() -> None:
    client = TestClient(_app())
    resp = client.get("/api/v1/state")
    assert resp.status_code == 200
    assert "guardrail" in resp.json()["data"]


def test_blackbox_endpoint_empty() -> None:
    client = TestClient(_app())
    resp = client.get("/api/v1/blackbox")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["count"] == 0
    assert body["data"]["frames"] == []


def test_guardrails_reset_endpoint() -> None:
    client = TestClient(_app())
    resp = client.post("/api/v1/guardrails/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["reset"] is True
    assert body["data"]["guardrail"]["hard_triggered"] is False


def test_ws_heartbeat_feeds_guardrail() -> None:
    app = _app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/heartbeat") as ws:
            ws.send_json({"type": "heartbeat"})
    assert app.state.gateway.guardrail.hard_triggered is False


if __name__ == "__main__":
    test_state_endpoint()
    test_devices_endpoint()
    test_command_clamped()
    test_command_unknown_channel()
    test_command_invalid_body()
    test_integration_control_clamped()
    test_agent_control_clamped()
    test_agent_control_rejects_unknown_source()
    test_state_snapshot_contains_guardrail()
    test_guardrails_endpoint()
    test_blackbox_endpoint_empty()
    test_guardrails_reset_endpoint()
    # WebSocket 依赖 lifespan 启动采集泵，独立运行时代替性验证 hub
    test_websocket_stream()
    test_ws_heartbeat_feeds_guardrail()
    print("bus smoke ok")