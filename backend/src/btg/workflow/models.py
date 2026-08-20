"""动态设备工作流编排器：Node-RED 极简版的数据契约。

一张工作流（:class:`Workflow`）是由「节点 + 有向边」组成的有向图：

- **触发节点 (trigger)**：从运行时上下文判定是否命中（心率/视觉/设备反馈/手动）；
- **条件节点 (condition)**：对上游信号做逻辑组合（AND/OR）或阈值比较；
- **动作节点 (action)**：命中后产出副作用（设强度/设位置/调用 AI 话术）。

工作流以精简 JSON 持久化，后端图遍历解释器在每个 Tick（默认 5Hz）执行。
所有模型字段严格校验（``extra="forbid"``），非法结构在导入阶段被拒绝。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: 触发节点种类。
TRIGGER_KINDS = frozenset({"heart_rate", "vision_score", "actuator_feedback", "manual_trigger"})
#: 条件节点种类。
CONDITION_KINDS = frozenset({"logic_and", "logic_or", "threshold_comparator"})
#: 动作节点种类。
ACTION_KINDS = frozenset({"set_actuator_intensity", "set_actuator_position", "invoke_ai_prompt"})
#: 全部节点种类。
NODE_KINDS = TRIGGER_KINDS | CONDITION_KINDS | ACTION_KINDS

#: 比较运算符（阈值比较与触发判定共用）。
COMPARISON_OPERATORS = frozenset({"gt", "gte", "lt", "lte", "eq", "neq"})

#: 阈值比较可引用的上下文字段（顶层或 ``点分`` 路径）。
COMPARABLE_FIELDS = frozenset({
    "heart_rate", "heart_rate_delta",
    "vision.pain", "vision.struggle",
    "actuator.battery", "actuator.position",
    "actuator.channel_a_level", "actuator.channel_b_level",
})


def node_type(kind: str) -> str:
    """返回节点类别（``trigger`` / ``condition`` / ``action``）。"""
    if kind in TRIGGER_KINDS:
        return "trigger"
    if kind in CONDITION_KINDS:
        return "condition"
    if kind in ACTION_KINDS:
        return "action"
    raise ValueError(f"unknown node kind: {kind}")


def _require_number(config: dict, key: str, kind: str) -> None:
    value = config.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"node {kind}: config.{key} must be a number, got {value!r}")


def _require_string(config: dict, key: str, kind: str, *, nonempty: bool = True) -> None:
    value = config.get(key)
    if not isinstance(value, str) or (nonempty and not value):
        raise ValueError(f"node {kind}: config.{key} must be a non-empty string")


def _check_operator(config: dict, kind: str) -> None:
    op = config.get("operator", "gte")
    if op not in COMPARISON_OPERATORS:
        raise ValueError(f"node {kind}: unsupported operator {op!r}")


def validate_config(kind: str, config: dict) -> None:
    """按节点种类校验 ``config`` 字段的必填项与类型。"""
    if kind == "heart_rate":
        _require_number(config, "threshold", kind)
        _check_operator(config, kind)
        if "delta_bpm" in config:
            _require_number(config, "delta_bpm", kind)
    elif kind == "vision_score":
        _require_number(config, "threshold", kind)
        _check_operator(config, kind)
        if config.get("metric", "pain") not in {"pain", "struggle"}:
            raise ValueError(f"node {kind}: config.metric must be pain|struggle")
    elif kind == "actuator_feedback":
        _require_number(config, "threshold", kind)
        _check_operator(config, kind)
        if config.get("metric", "battery") not in {"battery", "position"}:
            raise ValueError(f"node {kind}: config.metric must be battery|position")
    elif kind == "manual_trigger":
        _require_string(config, "key", kind)
    elif kind in {"logic_and", "logic_or"}:
        if config:
            raise ValueError(f"node {kind}: config must be empty")
    elif kind == "threshold_comparator":
        _require_string(config, "field", kind)
        _require_number(config, "threshold", kind)
        _check_operator(config, kind)
        if config["field"] not in COMPARABLE_FIELDS:
            raise ValueError(f"node {kind}: unsupported field {config['field']!r}")
    elif kind == "set_actuator_intensity":
        _require_string(config, "channel", kind)
        if "value" not in config and "value_field" not in config:
            raise ValueError(f"node {kind}: config requires value or value_field")
        if "value" in config:
            _require_number(config, "value", kind)
        for key in ("scale", "offset"):
            if key in config:
                _require_number(config, key, kind)
    elif kind == "set_actuator_position":
        _require_string(config, "channel", kind)
        _require_number(config, "position", kind)
    elif kind == "invoke_ai_prompt":
        _require_string(config, "prompt", kind)
    else:
        raise ValueError(f"unknown node kind: {kind}")


class WorkflowNode(BaseModel):
    """工作流图中的一个节点。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    kind: str
    config: dict[str, Any] = Field(default_factory=dict)

    @property
    def node_type(self) -> str:
        return node_type(self.kind)

    @model_validator(mode="after")
    def _validate(self) -> "WorkflowNode":
        validate_config(self.kind, self.config)
        return self


class WorkflowEdge(BaseModel):
    """一条有向边（``source -> target``）。"""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=64)


class Workflow(BaseModel):
    """一张完整工作流的只读契约。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    tick_hz: float = Field(default=5.0, gt=0.0, le=100.0)
    enabled: bool = True
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph(self) -> "Workflow":
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate node id")
        for edge in self.edges:
            if edge.source not in ids:
                raise ValueError(f"edge references unknown source {edge.source}")
            if edge.target not in ids:
                raise ValueError(f"edge references unknown target {edge.target}")
            if edge.source == edge.target:
                raise ValueError(f"edge self-loop on node {edge.source}")
        if not any(n.node_type == "action" for n in self.nodes):
            raise ValueError("workflow must contain at least one action node")
        return self

    def metadata_digest(self) -> dict[str, Any]:
        """供列表/健康检查使用的轻量元数据。"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "tick_hz": self.tick_hz,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
        }


__all__ = [
    "Workflow",
    "WorkflowNode",
    "WorkflowEdge",
    "TRIGGER_KINDS",
    "CONDITION_KINDS",
    "ACTION_KINDS",
    "NODE_KINDS",
    "COMPARISON_OPERATORS",
    "COMPARABLE_FIELDS",
    "node_type",
    "validate_config",
]