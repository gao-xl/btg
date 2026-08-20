"""动态风控与黑盒审计端点。

前缀 ``/api/v1``，标签 ``Guardrail``：

- ``GET  /api/v1/guardrails``：返回分级安全闸当前状态 + 配置快照。
- ``POST /api/v1/guardrails/reset``：复位硬急停锁存与软降级态（人工恢复）。
- ``GET  /api/v1/blackbox``：返回黑盒审计最近一小时状态帧（含因果链指针）。
- ``GET  /api/v1/blackbox/{frame_id}/chain``：回溯某帧的因果链。

均使用统一响应信封（``success``）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .contracts import APIError, success
from .deps import get_gateway

router = APIRouter(prefix="/api/v1", tags=["Guardrail"])


@router.get("/guardrails")
async def get_guardrails(gateway=Depends(get_gateway)):
    """返回分级安全闸当前状态、最近读数与配置。"""
    snapshot = gateway.guardrail.snapshot()
    snapshot["blackbox_frames"] = len(gateway.blackbox)
    return success(snapshot)


@router.post("/guardrails/reset")
async def reset_guardrails(gateway=Depends(get_gateway)):
    """复位硬急停锁存与软降级态。"""
    gateway.guardrail.reset()
    return success({"reset": True, "guardrail": gateway.guardrail.snapshot()})


@router.get("/blackbox")
async def get_blackbox(gateway=Depends(get_gateway)):
    """返回黑盒审计全部状态帧（时间升序）。"""
    return success({
        "frames": gateway.blackbox.snapshot(),
        "count": len(gateway.blackbox),
    })


@router.get("/blackbox/{frame_id}/chain")
async def get_blackbox_chain(frame_id: str, gateway=Depends(get_gateway)):
    """沿 ``parent_id`` 回溯某帧的因果链（由远及近）。"""
    chain = gateway.blackbox.chain(frame_id)
    if not chain:
        raise APIError(404, "not_found", f"未找到黑盒帧: {frame_id}")
    return success([f.to_dict() for f in chain])