"""动态设备工作流编排器（Node-RED 极简版）。

对外暴露稳定句柄：

- :class:`btg.workflow.models.Workflow`：工作流 JSON 契约（含图校验）；
- :class:`btg.workflow.engine.WorkflowEngine`：图遍历解释器；
- :class:`btg.workflow.service.WorkflowService`：工作流注册中心；
- :class:`btg.workflow.runtime.WorkflowRuntime`：按 Tick 驱动启用工作流的运行时。
"""
from __future__ import annotations

from .engine import WorkflowEngine, compare, resolve
from .models import (
    ACTION_KINDS,
    COMPARABLE_FIELDS,
    COMPARISON_OPERATORS,
    CONDITION_KINDS,
    TRIGGER_KINDS,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    node_type,
    validate_config,
)
from .runtime import ActionExecutor, ContextProvider, WorkflowRuntime
from .service import WorkflowService, WorkflowServiceError

__all__ = [
    "Workflow",
    "WorkflowNode",
    "WorkflowEdge",
    "WorkflowEngine",
    "WorkflowService",
    "WorkflowServiceError",
    "WorkflowRuntime",
    "ContextProvider",
    "ActionExecutor",
    "TRIGGER_KINDS",
    "CONDITION_KINDS",
    "ACTION_KINDS",
    "COMPARISON_OPERATORS",
    "COMPARABLE_FIELDS",
    "node_type",
    "validate_config",
    "compare",
    "resolve",
]