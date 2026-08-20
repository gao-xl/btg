"""内置剧本人格市场（Persona）扩展模块。

作为一个 ``extension`` 模块接入平台内核，将剧本人格注册中心
(:class:`btg.persona.service.PersonaService`) 暴露给网关与 REST。
装上内置演示剧本，启动即具备"一键切换人格"的离线体验。
"""
from __future__ import annotations

from btg.persona.service import PersonaService
from btg.platform.manifest import ModuleKind, ModuleManifest
from btg.platform.module import Module, register_module


@register_module
class PersonaMarketModule(Module):
    """提供"剧本包安装 + 一键切换人格 + 社区工坊"的能力。"""

    manifest = ModuleManifest(
        name="persona_market",
        version="0.1.0",
        kind=ModuleKind.EXTENSION,
        description="剧本/人格市场：scenario_manifest 契约 + 硬件映射策略 + 社区工坊。",
        capabilities=["persona_list", "persona_install", "persona_activate", "persona_workshop"],
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self.service = PersonaService()
        self.service.install_builtin()

    async def setup(self) -> None:
        self.context.logger.info("persona market ready: %d personas", self.service.count())

    async def health(self) -> dict:
        active = self.service.active()
        return {
            "name": self.name,
            "kind": self.kind.value,
            "status": "ok",
            "personas": self.service.count(),
            "active": active.scenario_id if active else None,
        }