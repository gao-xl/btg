"""配置中心冒烟测试：加载/更新/持久化、非法输入、HTTP 端点。

独立运行：``python tests/test_config_manager.py``
pytest 运行：``pytest tests/``
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "backend" / "src", _ROOT / "tests"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from btg.bus.app import create_app  # noqa: E402
from btg.config import ConfigManager, SystemSettings  # noqa: E402
from helpers import build_gateway  # noqa: E402


def test_defaults_when_missing() -> None:
    td = tempfile.mkdtemp()
    cm = ConfigManager(Path(td) / "nested" / "settings.yaml")  # 目录也不存在
    s = cm.get_settings()
    assert s.max_system_intensity == 50
    assert s.watchdog_timeout_sec == 2.0
    assert s.edging_target_hr == 135
    assert s.system_mode == "manual"
    assert s.algorithm_mode == "classical_motion"
    assert cm.config_path.exists()  # 自动创建目录与文件


def test_update_persists_to_disk() -> None:
    td = tempfile.mkdtemp()
    path = Path(td) / "settings.yaml"
    cm = ConfigManager(path)
    updated = cm.update_settings({"max_system_intensity": 80, "system_mode": "api_script"})
    assert updated.max_system_intensity == 80
    assert updated.system_mode == "api_script"

    cm2 = ConfigManager(path)
    assert cm2.get_settings().max_system_intensity == 80
    assert cm2.get_settings().system_mode == "api_script"


def test_algorithm_mode_update_persists_to_disk() -> None:
    td = tempfile.mkdtemp()
    path = Path(td) / "settings.yaml"
    cm = ConfigManager(path)
    updated = cm.update_settings({"algorithm_mode": "mediapipe_pose"})
    assert updated.algorithm_mode == "mediapipe_pose"
    assert ConfigManager(path).get_settings().algorithm_mode == "mediapipe_pose"


def test_invalid_field_raises() -> None:
    td = tempfile.mkdtemp()
    cm = ConfigManager(Path(td) / "settings.yaml")
    try:
        cm.update_settings({"watchdog_timeout_sec": -1.0})
    except ValidationError:
        return
    raise AssertionError("负数看门狗超时应触发 ValidationError")


def test_unknown_field_raises() -> None:
    td = tempfile.mkdtemp()
    cm = ConfigManager(Path(td) / "settings.yaml")
    try:
        cm.update_settings({"nonexistent_field": 123})
    except ValidationError:
        return
    raise AssertionError("未知字段应触发 ValidationError（extra=forbid）")


def test_subscribe_notified_on_update() -> None:
    td = tempfile.mkdtemp()
    cm = ConfigManager(Path(td) / "settings.yaml")
    received: list[int] = []
    cm.subscribe(lambda s: received.append(s.max_system_intensity))
    cm.update_settings({"max_system_intensity": 60})
    assert received == [60]


def test_http_get_and_put() -> None:
    td = tempfile.mkdtemp()
    gateway = build_gateway(Path(td))
    client = TestClient(create_app(gateway))

    resp = client.get("/api/v1/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["code"] == 200
    assert isinstance(body["timestamp"], float)
    assert body["data"]["system_mode"] == "manual"

    resp = client.put("/api/v1/settings", json={"edging_target_hr": 140})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"]["edging_target_hr"] == 140

    # 非法值 -> 422 + 错误信封
    resp = client.put("/api/v1/settings", json={"system_mode": "invalid_mode"})
    assert resp.status_code == 422
    error = resp.json()
    assert error["status"] == "error"
    assert error["code"] == 422
    assert error["error"]["type"] == "validation_error"

    # 非对象请求体 -> 422
    resp = client.put("/api/v1/settings", json=["not", "an", "object"])
    assert resp.status_code == 422
    error = resp.json()
    assert error["status"] == "error"
    assert error["error"]["type"] == "validation_error"


if __name__ == "__main__":
    test_defaults_when_missing()
    test_update_persists_to_disk()
    test_invalid_field_raises()
    test_unknown_field_raises()
    test_subscribe_notified_on_update()
    test_http_get_and_put()
    print("config manager smoke ok")
