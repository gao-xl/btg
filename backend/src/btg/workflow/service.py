"""工作流注册中心：存管、启停与逐 Tick 执行已导入的工作流。"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional

from .engine import WorkflowEngine
from .models import Workflow


class WorkflowServiceError(ValueError):
    """工作流注册中心的预期业务错误。"""


class WorkflowService:
    """内存版工作流注册中心（单机网关运行期存管）。

    ``add`` 接收 JSON 工作流（前端拖拽导出）并严格校验；每个启用工作流
    会在每个 Tick 经 :class:`WorkflowEngine` 求值，聚合全部命中动作。
    """

    def __init__(self, *, max_workflows: int = 512, clock: Optional[Callable[[], float]] = None) -> None:
        self._workflows: Dict[str, Workflow] = {}
        self._engines: Dict[str, WorkflowEngine] = {}
        self._max_workflows = max_workflows

    # ------------------------------------------------------------------ #
    # 存管
    # ------------------------------------------------------------------ #
    def add(self, data: Mapping[str, Any]) -> Workflow:
        """校验并登记一张工作流（同 id 已存在则报错）。"""
        if len(self._workflows) >= self._max_workflows:
            raise WorkflowServiceError("too many workflows")
        workflow = Workflow.model_validate(dict(data))
        if workflow.id in self._workflows:
            raise WorkflowServiceError(f"workflow already exists: {workflow.id}")
        self._workflows[workflow.id] = workflow
        self._engines[workflow.id] = WorkflowEngine(workflow)
        return workflow

    def update(self, workflow_id: str, data: Mapping[str, Any]) -> Workflow:
        """整体替换一张工作流（id 必须一致）。"""
        if workflow_id not in self._workflows:
            raise WorkflowServiceError(f"workflow not found: {workflow_id}")
        workflow = Workflow.model_validate(dict(data))
        if workflow.id != workflow_id:
            raise WorkflowServiceError("workflow id mismatch")
        self._workflows[workflow_id] = workflow
        self._engines[workflow_id] = WorkflowEngine(workflow)
        return workflow

    def delete(self, workflow_id: str) -> None:
        if workflow_id not in self._workflows:
            raise WorkflowServiceError(f"workflow not found: {workflow_id}")
        del self._workflows[workflow_id]
        del self._engines[workflow_id]

    def get(self, workflow_id: str) -> Workflow:
        try:
            return self._workflows[workflow_id]
        except KeyError as exc:
            raise WorkflowServiceError(f"workflow not found: {workflow_id}") from exc

    def set_enabled(self, workflow_id: str, enabled: bool) -> Workflow:
        if workflow_id not in self._workflows:
            raise WorkflowServiceError(f"workflow not found: {workflow_id}")
        workflow = self._workflows[workflow_id]
        self._workflows[workflow_id] = workflow.model_copy(update={"enabled": bool(enabled)})
        self._engines[workflow_id] = WorkflowEngine(self._workflows[workflow_id])
        return self._workflows[workflow_id]

    def list(self) -> List[dict]:
        """返回全部工作流的轻量元数据（保插入序）。"""
        return [w.metadata_digest() for w in self._workflows.values()]

    def count(self) -> int:
        return len(self._workflows)

    # ------------------------------------------------------------------ #
    # 执行
    # ------------------------------------------------------------------ #
    def tick(self, context: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """对全部启用工作流求值一次，返回命中动作列表。

        每条结果追加 ``workflow_id`` 供下游溯源。
        """
        actions: List[Dict[str, Any]] = []
        for workflow_id, engine in self._engines.items():
            if not self._workflows[workflow_id].enabled:
                continue
            for action in engine.tick(context):
                actions.append({"workflow_id": workflow_id, **action})
        return actions

    def trace(self, workflow_id: str, context: Mapping[str, Any]) -> Dict[str, Any]:
        """对单个工作流求值并返回节点命中观测（调试用）。"""
        engine = self._engines.get(workflow_id)
        if engine is None:
            raise WorkflowServiceError(f"workflow not found: {workflow_id}")
        return engine.trace(context)


__all__ = ["WorkflowService", "WorkflowServiceError"]