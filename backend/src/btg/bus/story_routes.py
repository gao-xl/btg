"""剧情（Story）导入与管理 REST 端点。"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from btg.story.importers import StoryImportError
from btg.story.service import StoryService, StoryServiceError

from .contracts import APIError, success
from .deps import get_gateway, require_feature

router = APIRouter(
    prefix="/api/v1/story",
    tags=["Story"],
    dependencies=[Depends(require_feature("story"))],
)


def _service(gateway=Depends(get_gateway)) -> StoryService:
    service = getattr(gateway, "story_service", None)
    if service is None:
        raise APIError(503, "story_unavailable", "story engine is not available")
    return service


@router.get("")
async def list_stories(service: StoryService = Depends(_service)):
    return success({"stories": service.list(), "count": len(service)})


@router.post("/import", status_code=201)
async def import_story(
    payload: dict = Body(...),
    service: StoryService = Depends(_service),
):
    text = payload.get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise APIError(422, "validation_error", "text is required and must be a non-empty string")
    story_id = payload.get("story_id")
    title = payload.get("title")
    try:
        story = await service.import_story(text, story_id=story_id, title=title)
    except (StoryImportError, StoryServiceError) as exc:
        raise APIError(400, "story_import_rejected", str(exc)) from exc
    return success(story.metadata_digest(), status_code=201)


@router.get("/{story_id}")
async def get_story(story_id: str, service: StoryService = Depends(_service)):
    try:
        return success(service.get(story_id))
    except StoryServiceError as exc:
        raise APIError(404, "story_not_found", str(exc)) from exc


@router.delete("/{story_id}")
async def delete_story(story_id: str, service: StoryService = Depends(_service)):
    try:
        await service.delete(story_id)
    except StoryServiceError as exc:
        raise APIError(404, "story_not_found", str(exc)) from exc
    return success({"id": story_id, "deleted": True})