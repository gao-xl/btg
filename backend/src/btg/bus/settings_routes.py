"""统一配置 API（Configuration Center）。

前缀 ``/api/v1/settings``，标签 ``Configuration Center``：

- ``GET  /api/v1/settings``：返回当前全局系统配置。
- ``PUT  /api/v1/settings``：局部更新配置（JSON 字典），返回更新后的完整配置。

均使用统一响应信封（``success`` / ``APIError``）；非法输入返回规范 422。
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import ValidationError

from .contracts import APIError, success
from .deps import get_gateway

router = APIRouter(prefix="/api/v1/settings", tags=["Configuration Center"])


@router.get("")
async def get_settings(gateway=Depends(get_gateway)):
    """返回当前全局系统配置（``ai.api_key`` 已脱敏）。"""
    return success(gateway.config_manager.get_public_settings())


@router.put("")
async def update_settings(payload: Dict[str, Any], gateway=Depends(get_gateway)):
    """局部更新全局配置并持久化。

    Args:
        payload: 待更新的字段字典（可只包含部分字段）。

    Returns:
        更新后的配置（``ai.api_key`` 已脱敏，包裹在成功信封中）。

    Raises:
        APIError: 422 —— 字段非法/类型不符/未知字段（pydantic 校验）；
            400 —— YAML 持久化失败（磁盘不可写等）。
    """
    try:
        gateway.config_manager.update_settings(payload)
    except ValidationError as exc:
        raise APIError(
            422, "validation_error", "Request validation failed.", details=exc.errors()
        ) from exc
    except OSError as exc:
        raise APIError(400, "persistence_error", str(exc)) from exc

    # 返回脱敏后的完整配置，避免把 api_key 回写前端
    return success(gateway.config_manager.get_public_settings())