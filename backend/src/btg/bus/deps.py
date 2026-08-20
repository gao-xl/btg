"""FastAPI dependency that exposes the assembled :class:`~btg.gateway.Gateway`.

The gateway is attached to the app via ``app.state.gateway`` in
:func:`btg.bus.app.create_app`, allowing every route to reach the live runtime
(telemetry buffer, channel manager, safety policy, integration, ...) without a
module-level singleton.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Request

from .contracts import APIError

if TYPE_CHECKING:  # pragma: no cover - avoid runtime cycle with gateway.py
    from btg.gateway import Gateway


def get_gateway(request: Request) -> "Gateway":
    """Return the gateway instance bound to the current application."""
    return request.app.state.gateway


def require_feature(feature_key: str):
    """返回 FastAPI 依赖：对应功能关闭时抛 409。

    用法：``@router.get("", dependencies=[Depends(require_feature("play_waves"))])``
    """

    def _check(gateway=Depends(get_gateway)) -> None:
        if not gateway.features.is_enabled(feature_key):
            raise APIError(409, "feature_disabled", f"feature '{feature_key}' is disabled")

    return _check