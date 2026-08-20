"""第三方 Inbound 控制端点：接收外部平台下发的执行器指令。

前缀 ``/integration/v1``。与 REST 手动指令共用同一条安全管道，但语义
上属于第三方脚本/平台主动控制（系统模式 ``api_script`` 场景预留入口）。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from btg_sdk import ActuatorCommand

from btg.core.exceptions import (
    DeviceConnectionError,
    InvalidCommandError,
    SafetyViolationError,
)

from ..bus.contracts import APIError, success
from ..bus.deps import get_gateway, require_feature
from ..bus.schemas import CommandRequest

router = APIRouter(
    prefix="/integration/v1",
    tags=["Integration"],
    dependencies=[Depends(require_feature("integration"))],
)


@router.post("/control")
async def inbound_control(payload: CommandRequest, gateway=Depends(get_gateway)):
    """接收第三方控制指令并经安全层下发。

    载荷与 ``/api/v1/command`` 一致：``{channel, value, unit?, actuator_id?}``。
    """
    command = ActuatorCommand(
        channel=payload.channel,
        actuator_id=payload.actuator_id,
        value=payload.value,
        unit=payload.unit,
        timestamp=time.time(),
    )
    try:
        safe = await gateway.dispatch(command)
    except SafetyViolationError as exc:
        raise APIError(400, "safety_violation", str(exc)) from exc
    except InvalidCommandError as exc:
        raise APIError(400, "invalid_command", str(exc)) from exc
    except DeviceConnectionError as exc:
        raise APIError(502, "device_unavailable", str(exc)) from exc

    return success({
        "channel": safe.channel,
        "value": safe.value,
        "unit": safe.unit,
        "clamped": safe.value != command.value,
    })