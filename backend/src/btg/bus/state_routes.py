"""系统状态查询端点：返回当前状态机状态、近况迁移与最新遥测快照。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .contracts import success
from .deps import get_gateway

router = APIRouter(prefix="/api/v1", tags=["State"])


@router.get("/state")
async def get_state(gateway=Depends(get_gateway)):
    """返回融合引擎当前状态、最近迁移记录与各通道最新读数。"""
    return success(gateway.snapshot_state())