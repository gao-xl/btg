"""插件模块清单端点：返回平台内核已发现的插件模块。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .contracts import APIError, success
from .deps import get_gateway

router = APIRouter(prefix="/api/v1", tags=["Modules"])


@router.get("/modules")
async def get_modules(gateway=Depends(get_gateway)):
    """返回平台已发现的插件模块元数据清单。"""
    return success(gateway.modules())


def _module(gateway, name):
    try:
        return gateway.kernel.registry.get_by_name(name)
    except KeyError as exc:
        raise APIError(404, "not_found", f"模块未找到: {name}") from exc


@router.post("/modules/{name}/start")
async def start_module(name: str, gateway=Depends(get_gateway)):
    """启动单个模块（幂等；走 setup→start 生命周期）。"""
    ok = await gateway.kernel.set_module_enabled(name, True)
    if not ok:
        raise APIError(404, "not_found", f"模块未找到: {name}")
    return success({"name": name, "enabled": True})


@router.post("/modules/{name}/stop")
async def stop_module(name: str, gateway=Depends(get_gateway)):
    """停止单个模块（幂等；走 stop 生命周期）。"""
    ok = await gateway.kernel.set_module_enabled(name, False)
    if not ok:
        raise APIError(404, "not_found", f"模块未找到: {name}")
    return success({"name": name, "enabled": False})


@router.get("/modules/{name}/health")
async def module_health(name: str, gateway=Depends(get_gateway)):
    """查询单个模块的健康信息。"""
    module = _module(gateway, name)
    return success(await module.health())