"""手动遥测覆盖端点：接收前端手动录入的位置、强度与校准参数。

端点：

- ``POST /api/v1/override`` — 提交或更新一条手动覆盖
- ``GET  /api/v1/override`` — 查询所有设备的当前覆盖状态
- ``GET  /api/v1/override/{device_id}`` — 查询单个设备的覆盖状态
- ``GET  /api/v1/override/{device_id}/history`` — 查询覆盖历史
- ``DELETE /api/v1/override/{device_id}`` — 清除某设备的覆盖
- ``GET  /api/v1/override/{device_id}/merged`` — 获取合并后的遥测
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from .contracts import APIError, success
from .deps import get_gateway
from ..hal.actuators.manual_telemetry_override import ManualOverrideRequest

router = APIRouter(prefix="/api/v1", tags=["ManualOverride"])


def _get_store(gateway: Any) -> Any:
    """从网关获取 ManualOverrideStore（惰性初始化）。"""
    if not hasattr(gateway, "_manual_override_store"):
        from ..hal.actuators.manual_telemetry_override import ManualOverrideStore

        store = ManualOverrideStore(
            event_bus=gateway.event_bus,
            hub=gateway.telemetry_hub,
        )
        gateway._manual_override_store = store  # type: ignore[attr-defined]
    return gateway._manual_override_store


@router.post("/override")
async def post_override(payload: ManualOverrideRequest, gateway=Depends(get_gateway)):
    """提交或更新一条手动遥测覆盖。

    手动录入后立即通过 WebSocket 广播给所有连接的客户端和 AI 主控。
    """
    store = _get_store(gateway)
    override = await store.update(payload)

    return success({
        "device_id": override.device_id,
        "manual_position": override.manual_position,
        "subjective_intensity": override.subjective_intensity,
        "authoritative_position": override.authoritative_position,
        "timestamp": override.timestamp,
        "source": override.source,
        "note": override.note,
        "updated_at": override.updated_at,
    })


@router.get("/override")
async def list_overrides(gateway=Depends(get_gateway)):
    """查询所有设备的当前手动覆盖状态。"""
    store = _get_store(gateway)
    return success(store.snapshot())


@router.get("/override/{device_id}")
async def get_override(device_id: str, gateway=Depends(get_gateway)):
    """查询单个设备的手动覆盖状态。"""
    store = _get_store(gateway)
    override = store.get(device_id)
    if override is None:
        raise APIError(
            404, "not_found",
            f"设备 {device_id} 无手动覆盖记录",
        )
    return success({
        "device_id": override.device_id,
        "manual_position": override.manual_position,
        "subjective_intensity": override.subjective_intensity,
        "authoritative_position": override.authoritative_position,
        "timestamp": override.timestamp,
        "source": override.source,
        "note": override.note,
        "updated_at": override.updated_at,
    })


@router.get("/override/{device_id}/history")
async def get_override_history(
    device_id: str,
    limit: Optional[int] = Query(default=None, ge=1, le=1000),
    gateway=Depends(get_gateway),
):
    """查询某设备的手动覆盖历史记录。"""
    store = _get_store(gateway)
    items = store.history(device_id, limit=limit)
    return success({
        "device_id": device_id,
        "count": len(items),
        "history": [
            {
                "device_id": o.device_id,
                "manual_position": o.manual_position,
                "subjective_intensity": o.subjective_intensity,
                "authoritative_position": o.authoritative_position,
                "timestamp": o.timestamp,
                "source": o.source,
                "note": o.note,
                "updated_at": o.updated_at,
            }
            for o in items
        ],
    })


@router.delete("/override/{device_id}")
async def delete_override(device_id: str, gateway=Depends(get_gateway)):
    """清除某设备的手动覆盖记录。"""
    store = _get_store(gateway)
    existing = store.get(device_id)
    if existing is None:
        raise APIError(
            404, "not_found",
            f"设备 {device_id} 无手动覆盖记录",
        )
    store.clear(device_id)
    return success({"cleared": device_id})


@router.get("/override/{device_id}/merged")
async def get_merged_telemetry(
    device_id: str,
    gateway=Depends(get_gateway),
):
    """获取某设备手动覆盖与硬件遥测合并后的全息状态。"""
    store = _get_store(gateway)
    override = store.get(device_id)

    # 从网关获取该设备的硬件遥测（如有）
    hw_telemetry: Dict[str, Any] = {}
    if hasattr(gateway, "ring_buffer"):
        for channel, reading in gateway.ring_buffer.latest_all().items():
            if reading.sensor_id == device_id or reading.channel == device_id:
                hw_telemetry[channel] = {
                    "value": reading.value,
                    "unit": reading.unit,
                    "timestamp": reading.timestamp,
                }

    merged = store.get_merged_telemetry(device_id, hw_telemetry)
    return success(merged)
