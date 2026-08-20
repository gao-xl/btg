"""操作员急停端点：触发 / 复位 / 状态查询。

前端 Dashboard 的急停按钮（``POST /api/v1/estop``）此前缺少后端支撑，
现与 :meth:`btg.gateway.Gateway.estop` 打通：触发后归零全部执行器并
保持急停标，直到显式复位。
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .contracts import success
from .deps import get_gateway

router = APIRouter(prefix="/api/v1/estop", tags=["Emergency Stop"])


class EstopIn(BaseModel):
    source: str = "operator"
    reason: str = "operator_emergency_stop"


@router.get("/status")
async def estop_status(gateway=Depends(get_gateway)):
    """返回当前急停 / 安全闸 / 看门狗状态。"""
    return success(gateway.estop_status())


@router.post("")
async def trigger_estop(body: EstopIn, gateway=Depends(get_gateway)):
    """触发操作员急停。"""
    return success(await gateway.estop(body.reason))


@router.delete("")
async def clear_estop(gateway=Depends(get_gateway)):
    """复位操作员急停（清标，不自动恢复输出）。"""
    return success(await gateway.clear_estop())