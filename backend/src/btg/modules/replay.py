"""内置复盘曲线（Replay）扩展模块。

作为一个 ``extension`` 模块接入平台内核，将会话录制/回放注册中心
(:class:`btg.replay.service.ReplayService`) 暴露给网关与 REST；录制快路径
由网关在采集泵（遥测）与 AI 话术事件处调用。
"""
from __future__ import annotations

from btg.platform.manifest import ModuleKind, ModuleManifest
from btg.platform.module import Module, register_module
from btg.replay.service import ReplayService


@register_module
class ReplayLogModule(Module):
    """提供"会话录制 + 多维时空对齐回放 + 全息报告导出"的能力。"""

    manifest = ModuleManifest(
        name="replay_log",
        version="0.1.0",
        kind=ModuleKind.EXTENSION,
        description="复盘曲线：会话遥测录制、三轨道时间对齐回放与报告导出。",
        capabilities=["replay_record", "replay_query", "replay_export"],
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self.service = ReplayService()

    async def setup(self) -> None:
        self.context.logger.info("replay log ready: %d sessions", self.service.count())

    async def health(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "status": "ok",
            "sessions": self.service.count(),
            "active": self.service.active_session_id(),
        }