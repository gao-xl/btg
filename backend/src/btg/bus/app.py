"""FastAPI 应用工厂：装配路由、错误契约与应用生命周期。

配置中心的 REST 端点定义在 :mod:`btg.bus.settings_routes`；其余端点见
本包内 ``*_routes`` 模块；WebSocket 遥测流见 :mod:`btg.bus.websocket`。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from . import (
    bindings_routes,
    command_routes,
    control_routes,
    devices_routes,
    discovery_routes,
    estop_routes,
    features_routes,
    guardrail_routes,
    health_routes,
    manual_override_routes,
    modules_routes,
    persona_routes,
    play_routes,
    replay_routes,
    settings_routes,
    state_routes,
    story_routes,
    video_routes,
    workflow_routes,
)
from .contracts import install_exception_handlers
from .websocket import router as websocket_router

if TYPE_CHECKING:  # pragma: no cover - avoid runtime cycle with gateway.py
    from btg.gateway import Gateway


def create_app(gateway: "Gateway") -> FastAPI:
    """创建已装配全部路由与网关声明周期的 FastAPI 应用。"""

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await gateway.start()
        try:
            yield
        finally:
            await gateway.stop()

    app = FastAPI(title="Bio-Telemetry Gateway API", version="1.0.0", lifespan=lifespan)
    install_exception_handlers(app)
    app.state.gateway = gateway

    app.include_router(state_routes.router)
    app.include_router(devices_routes.router)
    app.include_router(discovery_routes.router)
    app.include_router(bindings_routes.router)
    app.include_router(command_routes.router)
    app.include_router(control_routes.router)
    app.include_router(play_routes.router)
    app.include_router(story_routes.router)
    app.include_router(workflow_routes.router)
    app.include_router(persona_routes.router)
    app.include_router(replay_routes.router)
    app.include_router(manual_override_routes.router)
    app.include_router(guardrail_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(features_routes.router)
    app.include_router(modules_routes.router)
    app.include_router(estop_routes.router)
    app.include_router(video_routes.router)
    app.include_router(health_routes.router)
    app.include_router(websocket_router)

    # 惰性导入 integration 路由，避免与 bus 包形成模块级循环依赖。
    from btg.integration import router as integration_router
    app.include_router(integration_router)
    return app
