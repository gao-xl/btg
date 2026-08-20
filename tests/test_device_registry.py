"""设备接入中枢单元测试：注册表 CRUD 与协议类型推断（不依赖真实蓝牙）。"""
from __future__ import annotations

import pytest

from btg.bus import device_registry as registry
from btg.bus.discovery_routes import _guess_kind


@pytest.fixture(autouse=True)
def clean_registry():
    before = registry.clear()
    yield
    registry.clear()


def test_registry_register_overwrite_and_get() -> None:
    entry = registry.register("AA:BB:CC:DD:EE:FF", "Coyote V2", "coyote")
    assert entry["address"] == "AA:BB:CC:DD:EE:FF"
    assert registry.get("AA:BB:CC:DD:EE:FF")["kind"] == "coyote"
    # 重复登记覆盖元信息
    registry.register("AA:BB:CC:DD:EE:FF", "Coyote V2", "thermo")
    assert registry.get("AA:BB:CC:DD:EE:FF")["kind"] == "thermo"


def test_registry_unregister_and_snapshot() -> None:
    registry.register("11:22:33:44:55:66", "Mi Band 8", "mi_band")
    registry.register("66:55:44:33:22:11", "LYWSD03MMC", "thermo")
    assert len(registry.snapshot()) == 2
    assert registry.unregister("11:22:33:44:55:66") is True
    assert registry.unregister("00:00:00:00:00:00") is False
    snap = registry.snapshot()
    assert len(snap) == 1
    assert snap[0]["address"] == "66:55:44:33:22:11"


def test_registry_clear_returns_count() -> None:
    registry.register("11:22:33:44:55:66", "A", "ble_generic")
    registry.register("12:12:12:12:12:12", "B", "ble_generic")
    assert registry.clear() == 2
    assert registry.snapshot() == []


def test_registry_snapshot_is_copy() -> None:
    registry.register("AB:CD:EF:00:11:22", "X", "ble_generic")
    snap = registry.snapshot()
    snap[0]["name"] = "mutated"
    assert registry.get("AB:CD:EF:00:11:22")["name"] == "X"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("DGLab Coyote V2", "coyote"),
        ("Mi Band 8 Pro", "mi_band"),
        ("LYWSD03MMC", "thermo"),
        ("Unknown Device", "ble_generic"),
        (None, "ble_generic"),
        ("", "ble_generic"),
    ],
)
def test_guess_kind(name, expected) -> None:
    assert _guess_kind(name) == expected