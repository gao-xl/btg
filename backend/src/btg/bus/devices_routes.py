"""设备清单端点：返回所有逻辑通道及其主备设备的在线状态。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .contracts import success
from .deps import get_gateway

router = APIRouter(prefix="/api/v1", tags=["Devices"])


@router.get("/devices")
async def get_devices(gateway=Depends(get_gateway)):
    """返回逻辑通道（sensor/actuator）及当前激活设备的清单。"""
    return success(gateway.device_status())