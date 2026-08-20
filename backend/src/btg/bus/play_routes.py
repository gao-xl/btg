"""REST facade for safe conversational play recommendations."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from btg.play.models import PlayDecisionRequest, StartPlaySessionRequest
from btg.play.service import PlaySessionError, PlaySessionManager

from .contracts import APIError, success
from .deps import get_gateway, require_feature

router = APIRouter(
    prefix="/api/v1/play",
    tags=["Conversational Play"],
    dependencies=[Depends(require_feature("play_waves"))],
)


def _manager(gateway=Depends(get_gateway)) -> PlaySessionManager:
    return gateway.play_sessions


@router.get("/waves")
async def list_waves(manager: PlaySessionManager = Depends(_manager)):
    return success(manager.catalog.public_list())


@router.post("/sessions", status_code=201)
async def start_session(payload: StartPlaySessionRequest, manager: PlaySessionManager = Depends(_manager)):
    try:
        session = manager.start(payload)
    except PlaySessionError as exc:
        raise APIError(400, "play_session_rejected", str(exc)) from exc
    return success(manager.public(session), status_code=201)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, manager: PlaySessionManager = Depends(_manager)):
    try:
        return success(manager.public(manager.get(session_id)))
    except PlaySessionError as exc:
        raise APIError(404, "play_session_not_found", str(exc)) from exc


@router.post("/sessions/{session_id}/decisions")
async def evaluate_decision(session_id: str, payload: PlayDecisionRequest, manager: PlaySessionManager = Depends(_manager)):
    try:
        return success(manager.evaluate(session_id, payload))
    except PlaySessionError as exc:
        raise APIError(400, "play_directive_rejected", str(exc)) from exc


@router.delete("/sessions/{session_id}")
async def stop_session(session_id: str, manager: PlaySessionManager = Depends(_manager)):
    try:
        session = manager.stop(session_id)
    except PlaySessionError as exc:
        raise APIError(404, "play_session_not_found", str(exc)) from exc
    return success({"id": session.id, "stopped": True, "actuated": False})
