"""功能开关 API（Feature Flags）。

前缀 ``/api/v1/features``，标签 ``Feature Flags``：

- ``GET  /api/v1/features``：返回平台模块 + 内置服务的完整开关清单；
- ``PUT  /api/v1/features``：局部更新开关（``{key: bool}``），热更新启停
  对应模块/服务，返回更新后的完整清单。

安全项（看门狗、黑盒审计）不可关闭；未知 key 会被忽略。
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from .contracts import APIError, success
from .deps import get_gateway

router = APIRouter(prefix="/api/v1/features", tags=["Feature Flags"])


@router.get("")
async def list_features(gateway=Depends(get_gateway)):
    """返回全部功能开关清单（模块 + 内置服务）。"""
    return success(gateway.features.list_features())


@router.put("")
async def update_features(payload: Dict[str, bool], gateway=Depends(get_gateway)):
    """局部更新功能开关并热更新启停。

    Args:
        payload: ``{key: bool}`` 字典，仅包含要变更的项。

    Returns:
        更新后的完整开关清单。

    Raises:
        APIError: 422 —— 载荷非法（非布尔值等）。
    """
    if not isinstance(payload, dict) or not all(
        isinstance(k, str) and isinstance(v, bool) for k, v in payload.items()
    ):
        raise APIError(422, "validation_error", "payload must be a dict of str -> bool")
    features = await gateway.features.apply(payload)
    return success(features)
