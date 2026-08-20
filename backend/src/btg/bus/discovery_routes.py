"""设备接入端点：BLE 扫描、设备登记与连接探测。

这是「设备中心」前端（DeviceCenter）的后端支撑：先把周边 BLE 设备扫描
出来并登记到 :mod:`btg.bus.device_registry`，后续批次（监控通道绑定）再从
注册表中选取设备。扫描依赖 ``bleak``（Windows 上经 WinRT 后端实现）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from . import device_registry as registry
from .contracts import APIError, success

router = APIRouter(prefix="/api/v1/discovery", tags=["Discovery"])


def _guess_kind(name: str | None) -> str:
    """按设备广播名粗略推断协议类型，仅供前端展示默认值。"""
    low = (name or "").lower()
    if "coyote" in low:
        return "coyote"
    if "mi band" in low or "mi_band" in low:
        return "mi_band"
    if "lywsd" in low:
        return "thermo"
    return "ble_generic"


class RegisterIn(BaseModel):
    name: str = Field(default="", description="设备显示名")
    kind: str | None = Field(default=None, description="覆盖协议类型推断")


@router.get("/ble/scan")
async def scan_ble(timeout: float = 4.0):
    """扫描周边 BLE 设备，返回发现列表（不写入注册表）。"""
    try:
        from bleak import BleakScanner
    except ImportError as exc:  # pragma: no cover - 取决于安装的可选依赖
        raise APIError(503, "ble_unavailable", "BLE 后端未安装（需要 bleak）") from exc
    try:
        devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    except Exception as exc:  # pragma: no cover - 平台差异导致的扫描异常
        raise APIError(500, "ble_scan_failed", f"BLE 扫描失败: {exc}") from exc
    payload = []
    for address, adv in devices.items():
        name = getattr(adv, "local_name", None) or ""
        payload.append(
            {
                "name": name,
                "address": address,
                "rssi": getattr(adv, "rssi", None),
                "kind_tip": _guess_kind(name),
            }
        )
    return success(payload)


@router.get("/registry")
async def list_registry():
    """列出已登记设备（后续监控绑定的候选池）。"""
    return success(registry.snapshot())


@router.post("/registry/{address}")
async def register_device(address: str, body: RegisterIn):
    """登记一台设备到注册表。"""
    kind = body.kind or _guess_kind(body.name)
    return success(registry.register(address, body.name, kind))


@router.delete("/registry/{address}")
async def unregister_device(address: str):
    if not registry.unregister(address):
        raise APIError(404, "not_found", f"设备 {address} 未登记")
    return success({"removed": address})


@router.delete("/registry")
async def clear_registry():
    """清空注册表。"""
    return success({"cleared": registry.clear()})


@router.post("/ble/{address}/probe")
async def probe_device(address: str):
    """尝试连接指定 BLE 设备验证可达性（连接后立即断开）。

    不可达是有效业务结果（返回 ``reachable: false``），不作为异常抛出。
    """
    try:
        from bleak import BleakClient
    except ImportError as exc:  # pragma: no cover
        raise APIError(503, "ble_unavailable", "BLE 后端未安装（需要 bleak）") from exc
    import time

    started = time.monotonic()
    try:
        async with BleakClient(address, timeout=6) as client:
            reachable = bool(client.is_connected)
        return success(
            {
                "address": address,
                "reachable": reachable,
                "detail": "OK" if reachable else "连接被拒绝或超时",
                "latency_ms": round((time.monotonic() - started) * 1000),
            }
        )
    except Exception as exc:
        return success(
            {
                "address": address,
                "reachable": False,
                "detail": str(exc),
                "latency_ms": round((time.monotonic() - started) * 1000),
            }
        )