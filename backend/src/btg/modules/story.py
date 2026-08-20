"""内置剧情（Story）导入与执行模块。

作为一个 ``extension`` 模块接入平台内核，将剧情注册中心
(:class:`btg.story.service.StoryService`) 暴露给网关与 REST。
"""
from __future__ import annotations

from btg.platform.manifest import ModuleKind, ModuleManifest
from btg.platform.module import Module, register_module
from btg.story.service import StoryService


@register_module
class StoryEngineModule(Module):
    """提供"自然语言剧情 -> 章节化场景脚本 + 独立执行引擎"的能力。"""

    manifest = ModuleManifest(
        name="story_engine",
        version="0.1.0",
        kind=ModuleKind.EXTENSION,
        description="把自然语言剧情导入为章节化场景脚本，并提供独立剧情执行引擎。",
        capabilities=["story_import", "story_run"],
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self.service = StoryService()

    async def setup(self) -> None:
        self.context.logger.info("story engine ready: %d stories", len(self.service))

    async def health(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "status": "ok",
            "stories": len(self.service),
        }