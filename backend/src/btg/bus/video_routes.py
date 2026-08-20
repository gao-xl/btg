"""视频控制端点：相机定义 CRUD、启停、取流预览与算法切换。

对应前端「视频控制」页。底层由 :class:`btg.video.CameraRuntime` 提供
进程内运行态；OpenCV 未安装时仅清单管理可用，启动采集会返回 503。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from btg.video import CameraDef

from .contracts import APIError, success
from .deps import get_gateway

router = APIRouter(prefix="/api/v1/video", tags=["Video"])


def _runtime(gateway):
    return gateway.camera_runtime


class AlgorithmIn(BaseModel):
    mode: str


@router.get("/cameras")
async def list_cameras(gateway=Depends(get_gateway)):
    """返回全部相机的定义 + 运行态清单。"""
    return success(_runtime(gateway).cameras())


@router.post("/cameras")
async def add_camera(body: CameraDef, gateway=Depends(get_gateway)):
    """新增（或更新同名）一台相机定义，并返回合并后的运行态。"""
    _runtime(gateway).add_camera(body)
    return success(_runtime(gateway).state_of(body.name) | body.model_dump())


@router.put("/cameras/{name}")
async def update_camera(name: str, body: CameraDef, gateway=Depends(get_gateway)):
    existing = _runtime(gateway).get(name)
    if existing is None:
        raise APIError(404, "not_found", f"相机未定义: {name}")
    updated = body.model_copy(update={"name": name})
    _runtime(gateway).add_camera(updated)
    return success(_runtime(gateway).state_of(name) | updated.model_dump())


@router.delete("/cameras/{name}")
async def remove_camera(name: str, gateway=Depends(get_gateway)):
    if not _runtime(gateway).remove_camera(name):
        raise APIError(404, "not_found", f"相机未定义: {name}")
    return success({"removed": name})


@router.post("/cameras/{name}/start")
async def start_camera(name: str, gateway=Depends(get_gateway)):
    runtime = _runtime(gateway)
    if runtime.get(name) is None:
        raise APIError(404, "not_found", f"相机未定义: {name}")
    try:
        await runtime.start(name)
    except RuntimeError as exc:
        raise APIError(503, "vision_unavailable", str(exc)) from exc
    return success(runtime.state_of(name))


@router.post("/cameras/{name}/stop")
async def stop_camera(name: str, gateway=Depends(get_gateway)):
    runtime = _runtime(gateway)
    await runtime.stop(name)
    return success(runtime.state_of(name))


@router.get("/cameras/{name}/frame")
async def get_frame(name: str, gateway=Depends(get_gateway)):
    """返回最新一帧 JPEG（用于前端 <img> 轮询预览）。未取到帧则返回 204。"""
    frame = _runtime(gateway).latest_frame(name)
    if frame is None:
        return Response(status_code=204)
    return Response(content=frame, media_type="image/jpeg")


@router.get("/cameras/{name}/metrics")
async def get_metrics(name: str, gateway=Depends(get_gateway)):
    """返回最新一帧的算法指标（如运动强度 / 挣扎分数）。"""
    runtime = _runtime(gateway)
    metrics = runtime.metrics(name)
    return success({"metrics": metrics, **runtime.state_of(name)})


@router.put("/cameras/{name}/algorithm")
async def set_algorithm(name: str, body: AlgorithmIn, gateway=Depends(get_gateway)):
    runtime = _runtime(gateway)
    if runtime.state_of(name)["state"] not in ("running", "starting"):
        raise APIError(409, "camera_not_running", f"相机未运行: {name}")
    try:
        used = await runtime.set_algorithm(name, body.mode)
    except KeyError as exc:
        raise APIError(404, "not_found", str(exc)) from exc
    return success({"algorithm_used": used})