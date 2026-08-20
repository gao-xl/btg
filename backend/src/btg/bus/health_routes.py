"""运维健康看板端点：聚合急停、看门狗、相机、通道与模块状态。

对应前端「运维」页，为操作人员提供单页运行状态总览，而无需在多个
业务端点间切换。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .contracts import success
from .deps import get_gateway

router = APIRouter(prefix="/api/v1", tags=["Health"])


@router.get("/health")
async def health_overview(gateway=Depends(get_gateway)):
    """聚合运维看板所需的全维度运行状态。"""
    estop = gateway.estop_status()
    return success(
        {
            "state": gateway.fusion.state_machine.current,
            "estop": estop,
            "features": gateway.features.list_features(),
            "channels": gateway.device_status(),
            "cameras": gateway.camera_runtime.cameras(),
            "modules": gateway.modules(),
            "feedback": gateway.feedback.snapshot(),
        }
    )