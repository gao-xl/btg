"""手动指令端点：下发单条执行器指令（经安全层截断后执行）。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from btg_sdk import ActuatorCommand

from btg.core.exceptions import (
    DeviceConnectionError,
    InvalidCommandError,
    SafetyViolationError,
)

from .contracts import APIError, success
from .deps import get_gateway, require_feature
from .schemas import CommandRequest

router = APIRouter(prefix="/api/v1", tags=["Command"])


@router.post("/command", dependencies=[Depends(require_feature("manual_control"))])
async def post_command(payload: CommandRequest, gateway=Depends(get_gateway)):
    """下发单条手动指令，返回安全层处理后的最终目标值。

    指令先经安全策略（第三方钩子 + 数值截断）校验，再路由到对应
    执行器冗余组；任一步失败均返回规范错误信封。
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