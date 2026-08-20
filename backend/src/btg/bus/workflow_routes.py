"""工作流编排器 REST 端点：排布、启停、触发与观测。

端点：

- ``GET  /api/v1/workflow``            列出全部工作流
- ``POST /api/v1/workflow``            导入一张 JSON 工作流
- ``GET  /api/v1/workflow/{id}``       查询单张工作流
- ``PUT  /api/v1/workflow/{id}``       整体替换
- ``DELETE /api/v1/workflow/{id}``     删除
- ``POST /api/v1/workflow/{id}/enable`` 启停（body: ``{"enabled": true}``）
- ``POST /api/v1/workflow/{id}/tick``   立即求值一轮（返回节点命中观测）
- ``POST /api/v1/workflow/trigger``     注入手动触发（前端快捷键/安全词）
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends

from btg.workflow.service import WorkflowService, WorkflowServiceError

from .contracts import APIError, success
from .deps import get_gateway, require_feature

router = APIRouter(
    prefix="/api/v1/workflow",
    tags=["Workflow"],
    dependencies=[Depends(require_feature("workflow"))],
)


def _service(gateway=Depends(get_gateway)) -> WorkflowService:
    service = getattr(gateway, "workflow_service", None)
    if service is None:
        raise APIError(503, "workflow_unavailable", "workflow engine is not available")
    return service


@router.get("")
async def list_workflows(service: WorkflowService = Depends(_service)):
    return success({"workflows": service.list(), "count": service.count()})


@router.post("", status_code=201)
async def create_workflow(payload: dict = Body(...), service: WorkflowService = Depends(_service)):
    try:
        workflow = service.add(payload)
    except (WorkflowServiceError, ValueError) as exc:
        raise APIError(400, "workflow_rejected", str(exc)) from exc
    return success(workflow.metadata_digest(), status_code=201)


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str, service: WorkflowService = Depends(_service)):
    try:
        return success(service.get(workflow_id))
    except WorkflowServiceError as exc:
        raise APIError(404, "workflow_not_found", str(exc)) from exc


@router.put("/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    payload: dict = Body(...),
    service: WorkflowService = Depends(_service),
):
    try:
        workflow = service.update(workflow_id, payload)
    except WorkflowServiceError as exc:
        raise APIError(404, "workflow_not_found", str(exc)) from exc
    except ValueError as exc:
        raise APIError(400, "workflow_rejected", str(exc)) from exc
    return success(workflow.metadata_digest())


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str, service: WorkflowService = Depends(_service)):
    try:
        service.delete(workflow_id)
    except WorkflowServiceError as exc:
        raise APIError(404, "workflow_not_found", str(exc)) from exc
    return success({"id": workflow_id, "deleted": True})


@router.post("/{workflow_id}/enable")
async def set_workflow_enabled(
    workflow_id: str,
    payload: dict = Body(...),
    service: WorkflowService = Depends(_service),
):
    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        raise APIError(422, "validation_error", "enabled must be a boolean")
    try:
        workflow = service.set_enabled(workflow_id, enabled)
    except WorkflowServiceError as exc:
        raise APIError(404, "workflow_not_found", str(exc)) from exc
    return success(workflow.metadata_digest())


@router.post("/{workflow_id}/tick")
async def tick_workflow(
    workflow_id: str,
    gateway=Depends(get_gateway),
    service: WorkflowService = Depends(_service),
):
    context = await gateway.workflow_context()
    try:
        return success(service.trace(workflow_id, context))
    except WorkflowServiceError as exc:
        raise APIError(404, "workflow_not_found", str(exc)) from exc


@router.post("/trigger")
async def inject_trigger(payload: dict = Body(...), gateway=Depends(get_gateway)):
    key = payload.get("key")
    if not isinstance(key, str) or not key:
        raise APIError(422, "validation_error", "key is required and must be a non-empty string")
    gateway.push_workflow_trigger(key)
    return success({"key": key, "accepted": True})