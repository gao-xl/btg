"""工作流编排器冒烟测试：模型校验、图遍历解释器、注册中心与运行时。

独立运行：``python tests/test_workflow.py``
pytest 运行：``pytest tests/``
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "sdk"))
sys.path.insert(0, str(_ROOT / "backend" / "src"))

import pytest  # noqa: E402

from btg.workflow import (  # noqa: E402
    Workflow,
    WorkflowEngine,
    WorkflowService,
    WorkflowServiceError,
    compare,
    resolve,
)


def _workflow(**overrides):
    data = {
        "id": "wf1",
        "name": "test wf",
        "nodes": [
            {"id": "hr", "kind": "heart_rate", "config": {"threshold": 150, "operator": "gte"}},
            {"id": "act", "kind": "set_actuator_intensity", "config": {"channel": "tens", "value": 40}},
        ],
        "edges": [{"source": "hr", "target": "act"}],
    }
    data.update(overrides)
    return Workflow.model_validate(data)


# ------------------------------------------------------------------ #
# 模型校验
# ------------------------------------------------------------------ #
def test_workflow_requires_action_node() -> None:
    with pytest.raises(ValueError):
        Workflow.model_validate({
            "id": "wf", "name": "n", "nodes": [{"id": "hr", "kind": "heart_rate", "config": {"threshold": 100}}],
            "edges": [],
        })


def test_workflow_rejects_unknown_node_kind() -> None:
    with pytest.raises(ValueError):
        _workflow(nodes=[
            {"id": "x", "kind": "nope", "config": {}},
            {"id": "act", "kind": "set_actuator_intensity", "config": {"channel": "t", "value": 1}},
        ], edges=[{"source": "x", "target": "act"}])


def test_workflow_rejects_duplicate_node_ids() -> None:
    with pytest.raises(ValueError):
        _workflow(nodes=[
            {"id": "a", "kind": "heart_rate", "config": {"threshold": 100}},
            {"id": "a", "kind": "set_actuator_intensity", "config": {"channel": "t", "value": 1}},
        ], edges=[])


# ------------------------------------------------------------------ #
# 解释器求值
# ------------------------------------------------------------------ #
def test_engine_emits_action_when_trigger_hits() -> None:
    engine = WorkflowEngine(_workflow())
    actions = engine.tick({"heart_rate": 160.0})
    assert len(actions) == 1
    assert actions[0]["kind"] == "set_actuator_intensity"
    assert actions[0]["value"] == 40.0


def test_engine_no_action_when_trigger_misses() -> None:
    engine = WorkflowEngine(_workflow())
    assert engine.tick({"heart_rate": 110.0}) == []


def test_engine_delta_bpm_trigger() -> None:
    wf = _workflow(nodes=[
        {"id": "hr", "kind": "heart_rate", "config": {"threshold": 200, "delta_bpm": 20}},
        {"id": "act", "kind": "set_actuator_intensity", "config": {"channel": "t", "value": 10}},
    ])
    engine = WorkflowEngine(wf)
    assert len(engine.tick({"heart_rate": 90.0, "heart_rate_delta": 25.0})) == 1
    assert engine.tick({"heart_rate": 90.0, "heart_rate_delta": 5.0}) == []


def test_engine_logic_and_gate() -> None:
    wf = _workflow(nodes=[
        {"id": "hr", "kind": "heart_rate", "config": {"threshold": 150}},
        {"id": "vis", "kind": "vision_score", "config": {"metric": "struggle", "threshold": 0.5}},
        {"id": "gate", "kind": "logic_and", "config": {}},
        {"id": "act", "kind": "set_actuator_intensity", "config": {"channel": "t", "value": 10}},
    ], edges=[{"source": "hr", "target": "gate"}, {"source": "vis", "target": "gate"},
              {"source": "gate", "target": "act"}])
    engine = WorkflowEngine(wf)
    ctx = {"heart_rate": 160.0, "vision": {"struggle": 0.8, "pain": 0.0}}
    assert len(engine.tick(ctx)) == 1
    assert engine.tick({"heart_rate": 160.0, "vision": {"struggle": 0.1, "pain": 0.0}}) == []


def test_engine_manual_trigger() -> None:
    wf = _workflow(nodes=[
        {"id": "mt", "kind": "manual_trigger", "config": {"key": "safeword"}},
        {"id": "act", "kind": "set_actuator_intensity", "config": {"channel": "t", "value": 0}},
    ], edges=[{"source": "mt", "target": "act"}])
    engine = WorkflowEngine(wf)
    assert engine.tick({"manual_triggers": {"safeword"}})
    assert engine.tick({"manual_triggers": set()}) == []


def test_trace_reports_states() -> None:
    engine = WorkflowEngine(_workflow())
    trace = engine.trace({"heart_rate": 160.0})
    assert trace["states"] == {"hr": True, "act": True}
    assert len(trace["actions"]) == 1


# ------------------------------------------------------------------ #
# 注册中心
# ------------------------------------------------------------------ #
def test_service_add_list_update_delete() -> None:
    service = WorkflowService()
    service.add(_workflow().model_dump())
    assert service.count() == 1
    assert service.list()[0]["id"] == "wf1"
    service.set_enabled("wf1", False)
    assert service.get("wf1").enabled is False
    service.delete("wf1")
    assert service.count() == 0
    with pytest.raises(WorkflowServiceError):
        service.get("wf1")


def test_service_rejects_duplicate() -> None:
    service = WorkflowService()
    service.add(_workflow().model_dump())
    with pytest.raises(WorkflowServiceError):
        service.add(_workflow().model_dump())


def test_compare_and_resolve_helpers() -> None:
    assert compare(10, "gte", 5) is True
    assert compare(None, "gte", 5) is False
    assert resolve({"a": {"b": 3}}, "a.b") == 3
    assert resolve({"a": 1}, "a.b") is None