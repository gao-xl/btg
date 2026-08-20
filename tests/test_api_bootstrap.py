"""生产网关装配冒烟：真实 Gateway 内核发现 + API 路由齐备性。

回归守护：曾因 `create_app` 遗漏挂载 `modules_routes` 导致
`GET /api/v1/modules` 404，且真实 `Gateway()` 构造因缺失的内置模块包
(persona/replay) 崩溃，而 `helpers.build_gateway` 并未覆盖这些真实路径。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "sdk", _ROOT / "backend" / "src"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from btg.bus.app import create_app
from btg.gateway import Gateway
from btg.settings import AppSettings


def test_production_gateway_constructs_and_discovers_modules() -> None:
    """真实 Gateway() 必须能完成内核发现（缺失占位包不阻断）。"""
    gateway = Gateway(settings=AppSettings.from_env())
    discovered = gateway.modules()
    assert isinstance(discovered, list) and len(discovered) > 0
    # 至少覆盖一个传感器模块与一个执行器模块
    kinds = {m.get("kind") for m in discovered}
    assert "sensor" in kinds and "actuator" in kinds


def test_app_exposes_modules_endpoint() -> None:
    """API 路由必须包含 /api/v1/modules（曾遗漏挂载导致 404）。"""
    gateway = Gateway(settings=AppSettings.from_env())
    app = create_app(gateway)
    paths = set(app.openapi()["paths"])
    assert "/api/v1/modules" in paths