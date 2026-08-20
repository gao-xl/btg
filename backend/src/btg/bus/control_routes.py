"""内部代理控制端点：供 scenario_agent 等网关内代理下发带会话上下文的指令。

与 ``POST /api/v1/command`` 的区别：本端点要求调用方携带 ``session_id`` 与
场景溯源字段（``source`` / ``scenario_id`` / ``scene_id``），指令同样经过
安全层截断后执行，并记录审计日志。
"""
from __future__ import annotations

import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from btg_sdk import ActuatorCommand

from btg.core.exceptions import (
    DeviceConnectionError,
    InvalidCommandError,
    SafetyViolationError,
)
from btg.core.logging import get_audit_logger

from .contracts import APIError, success
from .deps import get_gateway, require_feature

router = APIRouter(prefix="/api/v1/control", tags=["Agent Control"])

audit = get_audit_logger()


class AgentControlRequest(BaseModel):
    """网关内代理（scenario_agent 等）的受控指令请求。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    source: Literal["scenario_agent"]
    scenario_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    actuator_id: Optional[str] = None
    value: float
    unit: str = Field(min_length=1)


@router.post("/actuators", dependencies=[Depends(require_feature("ai_dialogue"))])
async def post_agent_control(payload: AgentControlRequest, gateway=Depends(get_gateway)):
    """接收剧本代理指令：审计溯源 → 安全层校验 → 执行器冗余组。"""
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

    audit.info(
        "agent_control session=%s source=%s scenario=%s scene=%s channel=%s value=%s->%s",
        payload.session_id, payload.source, payload.scenario_id, payload.scene_id,
        payload.channel, payload.value, safe.value,
    )
    return success({
        "channel": safe.channel,
        "value": safe.value,
        "unit": safe.unit,
        "clamped": safe.value != command.value,
        "scenario_id": payload.scenario_id,
        "scene_id": payload.scene_id,
    })
