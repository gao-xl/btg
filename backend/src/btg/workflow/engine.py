"""工作流图遍历解释器：在每个 Tick 评估触发/条件并产出动作。

解释器对「触发 → 条件 → 动作」做数据流求值：

- 触发节点：由运行时上下文判定布尔信号；
- 条件节点：对上游信号做 AND/OR 组合或阈值比较；
- 动作节点：当且仅当其全部上游（直达入边）信号为真时触发。

求值带环保护（命中环视为假），纯声明式、无副作用，便于单元测试。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

from .models import Workflow


def resolve(context: Mapping[str, Any], path: str) -> Any:
    """按 ``点分`` 路径从上下文取值（如 ``vision.pain``）。"""
    current: Any = context
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def compare(actual: Any, operator: str, expected: Any) -> bool:
    """声明式比较，类型不兼容时返回 False。"""
    if actual is None or expected is None:
        return operator == "neq" and actual is not None and expected is not None
    try:
        if operator == "eq":
            return actual == expected
        if operator == "neq":
            return actual != expected
        return {
            "gt": lambda: actual > expected,
            "gte": lambda: actual >= expected,
            "lt": lambda: actual < expected,
            "lte": lambda: actual <= expected,
        }[operator]()
    except (TypeError, KeyError):
        return False


class WorkflowEngine:
    """驱动一张工作流的轻量图遍历解释器（无状态、每 Tick 求值一次）。"""

    def __init__(self, workflow: Workflow) -> None:
        self.workflow = workflow
        self._nodes = {n.id: n for n in workflow.nodes}
        self._incoming: Dict[str, List[str]] = {n.id: [] for n in workflow.nodes}
        for edge in workflow.edges:
            self._incoming[edge.target].append(edge.source)
        self._context: Mapping[str, Any] = {}

    # ------------------------------------------------------------------ #
    # 公开求值入口
    # ------------------------------------------------------------------ #
    def tick(self, context: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """求值一次，返回命中动作节点的参数列表（按节点出现顺序）。"""
        self._context = context
        memo: Dict[str, bool] = {}
        visiting: set = set()
        actions: List[Dict[str, Any]] = []
        for node in self.workflow.nodes:
            if node.node_type != "action":
                continue
            upstream = self._incoming[node.id]
            if upstream and all(self._active(s, memo, visiting) for s in upstream):
                actions.append(self._emit(node, context))
        return actions

    def trace(self, context: Mapping[str, Any]) -> Dict[str, Any]:
        """求值一次并附带各节点命中状态（供调试 / REST 观测）。"""
        self._context = context
        memo: Dict[str, bool] = {}
        visiting: set = set()
        states = {n.id: self._active(n.id, memo, visiting) for n in self.workflow.nodes}
        return {"states": states, "actions": self.tick(context)}

    # ------------------------------------------------------------------ #
    # 节点求值
    # ------------------------------------------------------------------ #
    def _active(self, node_id: str, memo: Dict[str, bool], visiting: set) -> bool:
        if node_id in memo:
            return memo[node_id]
        if node_id in visiting:
            return False  # 环保护
        node = self._nodes[node_id]
        visiting.add(node_id)
        value = self._evaluate(node, memo, visiting)
        visiting.discard(node_id)
        memo[node_id] = value
        return value

    def _evaluate(self, node, memo: Dict[str, bool], visiting: set) -> bool:
        kind = node.kind
        config = node.config
        if kind == "heart_rate":
            hr = self._context.get("heart_rate")
            hit = compare(hr, config.get("operator", "gte"), config["threshold"])
            if hit:
                return True
            delta = config.get("delta_bpm")
            if delta is not None:
                value = self._context.get("heart_rate_delta")
                if isinstance(value, (int, float)):
                    return abs(float(value)) > float(delta)
            return False
        if kind == "vision_score":
            metric = config.get("metric", "pain")
            return compare(
                resolve(self._context, f"vision.{metric}"),
                config.get("operator", "gte"),
                config["threshold"],
            )
        if kind == "actuator_feedback":
            metric = config.get("metric", "battery")
            return compare(
                resolve(self._context, f"actuator.{metric}"),
                config.get("operator", "lte"),
                config["threshold"],
            )
        if kind == "manual_trigger":
            key = config.get("key")
            triggers = self._context.get("manual_triggers", set())
            return bool(key) and key in triggers
        if kind == "logic_and":
            upstream = self._incoming.get(node.id, [])
            return bool(upstream) and all(self._active(s, memo, visiting) for s in upstream)
        if kind == "logic_or":
            upstream = self._incoming.get(node.id, [])
            return bool(upstream) and any(self._active(s, memo, visiting) for s in upstream)
        if kind == "threshold_comparator":
            value = resolve(self._context, config["field"])
            return compare(value, config.get("operator", "gte"), config["threshold"])
        # 动作节点作为上游输入时视为真（其副作用不参与条件链路）
        return True

    # ------------------------------------------------------------------ #
    # 动作产出
    # ------------------------------------------------------------------ #
    def _emit(self, node, context: Mapping[str, Any]) -> Dict[str, Any]:
        config = node.config
        if node.kind == "set_actuator_intensity":
            value = config.get("value")
            if value is None and config.get("value_field"):
                raw = resolve(context, config["value_field"])
                if isinstance(raw, (int, float)):
                    value = float(raw) * float(config.get("scale", 1.0)) + float(config.get("offset", 0.0))
            resolved = float(value) if isinstance(value, (int, float)) else 0.0
            return {
                "node_id": node.id,
                "kind": "set_actuator_intensity",
                "channel": config["channel"],
                "value": resolved,
                "unit": config.get("unit", ""),
            }
        if node.kind == "set_actuator_position":
            return {
                "node_id": node.id,
                "kind": "set_actuator_position",
                "channel": config["channel"],
                "position": float(config["position"]),
            }
        if node.kind == "invoke_ai_prompt":
            return {
                "node_id": node.id,
                "kind": "invoke_ai_prompt",
                "prompt": config["prompt"],
                "persona_hint": config.get("persona_hint", ""),
            }
        return {"node_id": node.id, "kind": node.kind}


__all__ = ["WorkflowEngine", "compare", "resolve"]