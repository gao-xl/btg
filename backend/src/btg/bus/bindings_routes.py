"""监控配置端点：逻辑通道主备绑定、设备候选与热重载。

把批次1登记的 BLE 设备（或设备插件）持久化绑定到 sensor/actuator 逻辑通道，
写入 ``devices.yaml`` 的主备设备列表；``POST /reload`` 触发热重载使配置生效。
写入为持久化操作，会改写 ``config/devices.yaml``（PyYAML 重写，注释不保留）。
"""
from __future__ import annotations

from typing import Any

import yaml
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from btg.hal import ChannelManager, load_config

from . import device_registry as registry
from .contracts import success
from .deps import get_gateway

router = APIRouter(prefix="/api/v1/monitor", tags=["Monitor"])


def _load_raw(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_raw(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


async def _rebuild_channel_manager(gateway) -> None:
    """安全重载通道：stop -> 重新加载配置 -> build -> start。"""
    old = gateway.channel_manager
    try:
        await old.stop()
    except Exception:  # pragma: no cover - 平台差异
        pass
    gateway.device_config = load_config(str(gateway.settings.device_config_path))
    new = ChannelManager(gateway.device_config, gateway._queue)
    new.build()
    await new.start()
    gateway.channel_manager = new


@router.get("/bindings")
async def get_bindings(gateway=Depends(get_gateway)):
    """返回全部逻辑通道及其主备设备绑定（merge 运行时激活状态）。"""
    raw = _load_raw(str(gateway.settings.device_config_path))
    active = {c["channel"]: c for c in gateway.device_status()}
    out = []
    for name, spec in raw.get("channels", {}).items():
        devices = []
        for i, d in enumerate(spec.get("devices", []), start=1):
            devices.append(
                {
                    "order": i,
                    "plugin": d.get("plugin"),
                    "priority": d.get("priority"),
                    "config": d.get("config", {}),
                }
            )
        out.append(
            {
                "channel": name,
                "type": spec.get("type", "sensor"),
                "devices": devices,
                "active": active.get(name, {}).get("active"),
            }
        )
    return success(out)


class BindDevice(BaseModel):
    plugin: str
    priority: int = Field(ge=1, le=2)
    address: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class BindIn(BaseModel):
    channel: str
    devices: list[BindDevice]


@router.put("/bindings")
async def put_bindings(body: BindIn, gateway=Depends(get_gateway)):
    """持久化某逻辑通道的主备设备绑定（priority 1/2 即主/备）。"""
    path = str(gateway.settings.device_config_path)
    raw = _load_raw(path)
    spec = raw.setdefault("channels", {}).setdefault(body.channel, {})
    spec.setdefault("type", "sensor")
    new_devices: list[dict[str, Any]] = []
    for bd in sorted(body.devices, key=lambda d: d.priority):
        item: dict[str, Any] = {"plugin": bd.plugin, "priority": bd.priority}
        cfg = dict(bd.config or {})
        if bd.address:
            cfg["address"] = bd.address
        if cfg:
            item["config"] = cfg
        new_devices.append(item)
    spec["devices"] = new_devices
    raw["channels"][body.channel] = spec
    _save_raw(path, raw)
    return success({"saved": True, "channel": body.channel, "devices": new_devices})


@router.get("/candidates")
async def get_candidates(gateway=Depends(get_gateway)):
    """提供绑定候选：已登记设备 + 当前配置中已知的设备插件。"""
    raw = _load_raw(str(gateway.settings.device_config_path))
    plugins = sorted(
        {
            d.get("plugin")
            for ch in raw.get("channels", {}).values()
            for d in ch.get("devices", [])
            if d.get("plugin")
        }
    )
    return success({"registered_devices": registry.snapshot(), "known_plugins": plugins})


@router.post("/reload")
async def reload_bindings(gateway=Depends(get_gateway)):
    """把已保存的 devices.yaml 重新加载并重建通道。失败不回滚已保存配置。"""
    try:
        await _rebuild_channel_manager(gateway)
        return success({"reloaded": True})
    except Exception as exc:
        return success({"reloaded": False, "detail": str(exc)})