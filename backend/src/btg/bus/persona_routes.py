"""剧本人格市场 REST 端点：安装、切换、管理剧本包与社区工坊。

端点：

- ``GET  /api/v1/persona``            列出全部剧本包
- ``POST /api/v1/persona/install``    安装一个剧本包（scenario_manifest.json）
- ``GET  /api/v1/persona/workshop``   拉取社区工坊远端清单
- ``GET  /api/v1/persona/active``     查询当前激活剧本
- ``POST /api/v1/persona/{id}/activate``  一键切换
- ``POST /api/v1/persona/deactivate`` 清除激活
- ``GET  /api/v1/persona/{id}``       查询单个剧本包
- ``DELETE /api/v1/persona/{id}``     删除
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from btg.persona.service import PersonaService, PersonaServiceError

from .contracts import APIError, success
from .deps import get_gateway, require_feature

router = APIRouter(
    prefix="/api/v1/persona",
    tags=["Persona"],
    dependencies=[Depends(require_feature("persona"))],
)


def _service(gateway=Depends(get_gateway)) -> PersonaService:
    service = getattr(gateway, "persona_service", None)
    if service is None:
        raise APIError(503, "persona_unavailable", "persona market is not available")
    return service


@router.get("")
async def list_personas(service: PersonaService = Depends(_service)):
    return success({"personas": service.list(), "count": service.count()})


@router.post("/install", status_code=201)
async def install_persona(payload: dict = Body(...), service: PersonaService = Depends(_service)):
    try:
        manifest = service.install(payload)
    except (PersonaServiceError, ValueError) as exc:
        raise APIError(400, "persona_rejected", str(exc)) from exc
    return success(manifest.metadata_digest(), status_code=201)


@router.get("/active")
async def get_active(service: PersonaService = Depends(_service)):
    active = service.active()
    return success({"active": active.metadata_digest() if active else None})


@router.post("/deactivate")
async def deactivate(service: PersonaService = Depends(_service)):
    service.deactivate()
    return success({"active": None})


@router.get("/workshop")
async def list_workshop(service: PersonaService = Depends(_service), base_url: str = ""):
    if not base_url:
        return success({"source": "builtin", "personas": service.list()})
    try:
        remote = await service.fetch_workshop(base_url)
    except PersonaServiceError as exc:
        raise APIError(502, "workshop_unavailable", str(exc)) from exc
    return success({"source": base_url, "personas": remote})


@router.post("/{scenario_id}/activate")
async def activate(scenario_id: str, service: PersonaService = Depends(_service)):
    try:
        manifest = service.activate(scenario_id)
    except PersonaServiceError as exc:
        raise APIError(404, "persona_not_found", str(exc)) from exc
    return success(manifest.metadata_digest())


@router.get("/{scenario_id}")
async def get_persona(scenario_id: str, service: PersonaService = Depends(_service)):
    try:
        return success(service.get(scenario_id))
    except PersonaServiceError as exc:
        raise APIError(404, "persona_not_found", str(exc)) from exc


@router.delete("/{scenario_id}")
async def delete_persona(scenario_id: str, service: PersonaService = Depends(_service)):
    try:
        service.delete(scenario_id)
    except PersonaServiceError as exc:
        raise APIError(404, "persona_not_found", str(exc)) from exc
    return success({"id": scenario_id, "deleted": True})