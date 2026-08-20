"""复盘曲线 REST 端点：会话录制、回放查询与全息体征报告导出。

端点：

- ``POST   /api/v1/replay/sessions``          开启录制会话（body: ``{"tags": [...]}``）
- ``GET    /api/v1/replay/sessions``          列出全部会话
- ``POST   /api/v1/replay/sessions/{id}/end`` 结束录制
- ``GET    /api/v1/replay/sessions/{id}``     返回会话完整帧流
- ``GET    /api/v1/replay/sessions/{id}/series?kind=...`` 返回某指标数值序列
- ``GET    /api/v1/replay/sessions/{id}/svg`` 返回自包含 SVG 报告
- ``GET    /api/v1/replay/sessions/{id}/export`` 导出报告压缩包（zip）
- ``DELETE /api/v1/replay/sessions/{id}``     删除
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query, Response

from btg.replay.service import ReplayService, ReplayServiceError

from .contracts import APIError, success
from .deps import get_gateway, require_feature

router = APIRouter(
    prefix="/api/v1/replay",
    tags=["Replay"],
    dependencies=[Depends(require_feature("replay"))],
)


def _service(gateway=Depends(get_gateway)) -> ReplayService:
    service = getattr(gateway, "replay_service", None)
    if service is None:
        raise APIError(503, "replay_unavailable", "replay log is not available")
    return service


@router.post("/sessions", status_code=201)
async def start_session(payload: dict = Body(default={}), service: ReplayService = Depends(_service)):
    tags = payload.get("tags") or []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise APIError(422, "validation_error", "tags must be a list of strings")
    session = service.start_session(tags=tags)
    return success(session.summary(), status_code=201)


@router.get("/sessions")
async def list_sessions(service: ReplayService = Depends(_service)):
    return success({"sessions": service.list(), "count": service.count()})


@router.post("/sessions/{session_id}/end")
async def end_session(session_id: str, service: ReplayService = Depends(_service)):
    try:
        session = service.end_session(session_id)
    except ReplayServiceError as exc:
        raise APIError(404, "session_not_found", str(exc)) from exc
    return success(session.summary())


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    track: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    service: ReplayService = Depends(_service),
):
    try:
        frames = service.frames(session_id, track=track, kind=kind)
    except ReplayServiceError as exc:
        raise APIError(404, "session_not_found", str(exc)) from exc
    return success({"session_id": session_id, "frames": frames, "count": len(frames)})


@router.get("/sessions/{session_id}/series")
async def get_series(
    session_id: str,
    kind: str = Query(...),
    track: str | None = Query(default=None),
    service: ReplayService = Depends(_service),
):
    try:
        series = service.series(session_id, kind, track=track)
    except ReplayServiceError as exc:
        raise APIError(404, "session_not_found", str(exc)) from exc
    return success({"session_id": session_id, "kind": kind, "series": series})


@router.get("/sessions/{session_id}/svg")
async def get_svg(session_id: str, service: ReplayService = Depends(_service)):
    try:
        svg = service.render_svg(session_id)
    except ReplayServiceError as exc:
        raise APIError(404, "session_not_found", str(exc)) from exc
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/sessions/{session_id}/export")
async def export_report(
    session_id: str,
    gateway=Depends(get_gateway),
    service: ReplayService = Depends(_service),
):
    try:
        payload = service.export_report(session_id, blackbox_snapshot=gateway.blackbox.snapshot())
    except ReplayServiceError as exc:
        raise APIError(404, "session_not_found", str(exc)) from exc
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{session_id}_report.zip"'},
    )


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, service: ReplayService = Depends(_service)):
    try:
        service.delete_session(session_id)
    except ReplayServiceError as exc:
        raise APIError(404, "session_not_found", str(exc)) from exc
    return success({"id": session_id, "deleted": True})