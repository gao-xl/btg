"""设备接入中枢：BLE 扫描结果与已登记设备的内存注册表。

批次2 的「监控配置 / 逻辑通道绑定」会从这里选取已登记设备；端点定义在
:mod:`btg.bus.discovery_routes`。
"""
from __future__ import annotations

import threading
from typing import Any, Optional

_REGISTRY: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def register(address: str, name: str, kind: str) -> dict[str, Any]:
    """登记一台设备；同地址重复登记会覆盖元信息。"""
    with _LOCK:
        _REGISTRY[address] = {"address": address, "name": name, "kind": kind}
        return dict(_REGISTRY[address])


def unregister(address: str) -> bool:
    """移除一台设备，返回是否已存在。"""
    with _LOCK:
        return _REGISTRY.pop(address, None) is not None


def clear() -> int:
    """清空全部设备，返回移除数量。"""
    with _LOCK:
        count = len(_REGISTRY)
        _REGISTRY.clear()
        return count


def snapshot() -> list[dict[str, Any]]:
    """返回当前全部已登记设备的拷贝。"""
    with _LOCK:
        return [dict(v) for v in _REGISTRY.values()]


def get(address: str) -> Optional[dict[str, Any]]:
    """按地址取已登记设备，不存在返回 ``None``。"""
    with _LOCK:
        item = _REGISTRY.get(address)
        return dict(item) if item else None