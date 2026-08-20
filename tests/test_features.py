"""功能开关（Feature Flags）测试：REST 接口、模块启停与路由门控。

独立运行：``python tests/test_features.py``
pytest 运行：``pytest tests/``
"""
from __future__ import annotations

import sys
import tempfile
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


def _features(client: TestClient) -> dict:
    resp = client.get("/api/v1/features")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    return {f["key"]: f for f in body["data"]}


def test_features_list_contains_modules_and_services() -> None:
    client = TestClient(_app())
    features = _features(client)
    # 内置服务
    assert features["telemetry"]["group"] == "service"
    assert features["telemetry"]["enabled"] is True
    assert features["watchdog"]["locked"] is True
    # 平台模块
    assert features["mock_sensor"]["group"] == "module"
    assert features["mock_sensor"]["kind"] == "sensor"
    assert features["mock_actuator"]["group"] == "module"


def test_features_toggle_service() -> None:
    client = TestClient(_app())
    resp = client.put("/api/v1/features", json={"telemetry": False})
    assert resp.status_code == 200
    features = {f["key"]: f for f in resp.json()["data"]}
    assert features["telemetry"]["enabled"] is False
    # 持久化到配置中心
    gateway = client.app.state.gateway
    persisted = gateway.config_manager.get_settings().feature_flags
    assert persisted.get("telemetry") is False


def test_features_locked_cannot_disable() -> None:
    client = TestClient(_app())
    resp = client.put("/api/v1/features", json={"watchdog": False})
    assert resp.status_code == 200
    features = {f["key"]: f for f in resp.json()["data"]}
    assert features["watchdog"]["enabled"] is True


def test_features_unknown_key_ignored() -> None:
    client = TestClient(_app())
    before = _features(client)
    resp = client.put("/api/v1/features", json={"no_such_feature": False})
    assert resp.status_code == 200
    after = {f["key"]: f for f in resp.json()["data"]}
    assert set(before) == set(after)


def test_features_invalid_payload_422() -> None:
    client = TestClient(_app())
    # 非字典载荷无法通过 Dict[str, bool] 校验
    resp = client.put("/api/v1/features", json=[1, 2, 3])
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "validation_error"


def test_features_module_toggle() -> None:
    client = TestClient(_app())
    gateway = client.app.state.gateway
    assert gateway.kernel.is_enabled("mock_sensor") is True
    resp = client.put("/api/v1/features", json={"mock_sensor": False})
    assert resp.status_code == 200
    features = {f["key"]: f for f in resp.json()["data"]}
    assert features["mock_sensor"]["enabled"] is False
    assert gateway.kernel.is_enabled("mock_sensor") is False
    # 重新启用
    resp = client.put("/api/v1/features", json={"mock_sensor": True})
    assert resp.status_code == 200
    assert gateway.kernel.is_enabled("mock_sensor") is True


def test_route_gated_when_feature_disabled() -> None:
    client = TestClient(_app())
    # 停用手动控制后，控制指令被网关拒绝
    client.put("/api/v1/features", json={"manual_control": False})
    resp = client.post(
        "/api/v1/command",
        json={"channel": "tens_intensity", "value": 10.0, "unit": "mA"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["type"] == "feature_disabled"
    # 恢复后指令可正常下发
    client.put("/api/v1/features", json={"manual_control": True})
    resp = client.post(
        "/api/v1/command",
        json={"channel": "tens_intensity", "value": 10.0, "unit": "mA"},
    )
    assert resp.status_code == 200


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
