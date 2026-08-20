"""内置工作流编排器（Workflow）扩展模块。

作为一个 ``extension`` 模块接入平台内核，将工作流注册中心
(:class:`btg.workflow.service.WorkflowService`) 暴露给网关与 REST。
后台 Tick 循环由网关按需装配（:class:`btg.workflow.runtime.WorkflowRuntime`）。
"""
from __future__ import annotations

from btg.platform.manifest import ModuleKind, ModuleManifest
from btg.platform.module import Module, register_module
from btg.workflow.service import WorkflowService


@register_module
class WorkflowEngineModule(Module):
    """提供"JSON 工作流排布 + 图遍历解释器 + 定时执行"的赛博闭环能力。"""

    manifest = ModuleManifest(
        name="workflow_engine",
        version="0.1.0",
        kind=ModuleKind.EXTENSION,
        description="Node-RED 极简版：触发/条件/动作节点 + 图遍历解释器，按 Tick 执行自定义逻辑。",
        capabilities=["workflow_define", "workflow_run"],
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self.service = WorkflowService()

    async def setup(self) -> None:
        self.context.logger.info("workflow engine ready: %d workflows", self.service.count())

    async def health(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "status": "ok",
            "workflows": self.service.count(),
        }