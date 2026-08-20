"""剧本人格市场（Persona & Scenario Marketplace）。

一键切换 AI 的灵魂与硬件策略。对外暴露稳定句柄：

- :class:`btg.persona.models.ScenarioManifest`：剧本元数据契约；
- :class:`btg.persona.service.PersonaService`：注册中心 + 社区工坊。
"""
from __future__ import annotations

from .models import HardwareStrategy, ScenarioManifest
from .service import PersonaActivateHook, PersonaService, PersonaServiceError, builtin_catalog

__all__ = [
    "ScenarioManifest",
    "HardwareStrategy",
    "PersonaService",
    "PersonaServiceError",
    "PersonaActivateHook",
    "builtin_catalog",
]