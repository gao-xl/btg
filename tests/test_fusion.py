"""fusion 层冒烟测试：聚合器、规则集、状态机、融合引擎编排。

独立运行：``python tests/test_fusion.py``
pytest 运行：``pytest tests/``
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "sdk"))
sys.path.insert(0, str(_ROOT / "backend" / "src"))

from btg.core import EventBus  # noqa: E402
from btg.fusion import (  # noqa: E402
    FusionEngine,
    Rule,
    RuleSet,
    STATE_ALARM,
    STATE_RESTING,
    StateMachine,
    TelemetryAggregator,
)
from btg_sdk import ActuatorCommand, Reading, hook  # noqa: E402


def _reading(channel: str, value: float, ts: float, unit: str = "bpm") -> Reading:
    return Reading(channel=channel, sensor_id="s1", value=value, unit=unit, timestamp=ts)


def test_aggregator_window_and_mean() -> None:
    agg = TelemetryAggregator(window_seconds=1.0)
    agg.push(_reading("heart_rate", 80.0, 1.0))
    agg.push(_reading("heart_rate", 90.0, 1.2))
    agg.push(_reading("heart_rate", 100.0, 2.5))  # 早于 1.0s 窗口的样本被丢弃

    snap = agg.snapshot("heart_rate")
    assert snap is not None
    assert snap.mean == 100.0
    assert snap.count == 1
    assert snap.latest_value == 100.0
    assert snap.unit == "bpm"


def test_rule_set_priority_and_cooldown() -> None:
    hits: list[str] = []

    r1 = Rule("high", STATE_ALARM, lambda s: True, priority=1)
    r2 = Rule("low", STATE_RESTING, lambda _: True, cooldown=1.0)
    rules = RuleSet([r2, r1])  # 优先级：r1 先评估

    snapshots = {c: None for c in []}  # type: ignore[dict-item]
    res = rules.evaluate(snapshots)
    assert res.matched is not None and res.matched.name == "high"

    # 单独验证冷却：低优先级规则命中后进入冷却
    rules_low = RuleSet([Rule("low", STATE_RESTING, lambda _: hits.append("x") or True,
                              cooldown=1.0)])
    res1 = rules_low.evaluate({})
    res2 = rules_low.evaluate({})
    assert res1.matched is not None and res2.matched is None  # 冷却期内不再命中


def test_state_machine_transition_broadcasts() -> None:
    hook.clear_hooks()
    bus = EventBus()
    received: list[dict] = []
    hooked: list[str] = []

    @hook.on_state_change
    async def _on_state(state: str, previous: str, **kwargs) -> None:  # noqa: ANN003
        hooked.append(f"{previous}->{state}")

    @bus.on("state_change")
    async def _bus(state: str, previous: str, **kwargs) -> None:  # noqa: ANN003
        received.append({"state": state, "previous": previous})

    sm = StateMachine(bus, initial="init")

    async def scenario() -> None:
        assert await sm.transition("active", reason="test") is True
        assert await sm.transition("active", reason="dup") is False  # 同状态不广播
        assert sm.current == "active"

    asyncio.run(scenario())
    assert hooked == ["init->active"]
    assert received == [{"state": "active", "previous": "init"}]


def test_engine_ingest_rule_then_command() -> None:
    hook.clear_hooks()
    bus = EventBus()
    states: list[str] = []
    received: list[ActuatorCommand] = []

    @bus.on("state_change")
    async def _on_state(state: str, **kwargs) -> None:  # noqa: ANN003
        states.append(state)

    @bus.on("actuator_command")
    async def _on_cmd(commands: list, **kwargs) -> None:  # noqa: ANN003
        received.extend(commands)

    rule = Rule(
        name="tachycardia",
        target_state=STATE_ALARM,
        condition=lambda snaps: snaps["heart_rate"].latest_value > 120.0,
        commands=[ActuatorCommand(
            channel="tens_intensity", actuator_id="", value=30.0, unit="mA", timestamp=0.0
        )],
    )
    engine = FusionEngine(bus, [rule], initial_state="init")

    async def scenario() -> None:
        # 正常心率：不触发
        await engine.ingest(_reading("heart_rate", 80.0, 1.0))
        assert engine.state_machine.current == "init"

        # 心率超阈值：触发 ALARM + 下发指令
        out = await engine.ingest(_reading("heart_rate", 130.0, 2.0))
        assert engine.state_machine.current == STATE_ALARM
        assert len(out) == 1 and out[0].value == 30.0

    asyncio.run(scenario())
    assert states == [STATE_ALARM]
    assert len(received) == 1 and received[0].channel == "tens_intensity"


def test_engine_telemetry_hook_can_transform() -> None:
    hook.clear_hooks()

    @hook.on_telemetry_received
    async def _double(reading: Reading) -> Reading:
        return Reading(
            channel=reading.channel, sensor_id=reading.sensor_id,
            value=reading.value * 2, unit=reading.unit, timestamp=reading.timestamp,
        )

    bus = EventBus()
    rule = Rule("transformed", STATE_RESTING,
                condition=lambda snaps: snaps["heart_rate"].latest_value >= 200.0)
    engine = FusionEngine(bus, [rule], initial_state="init")

    async def scenario() -> None:
        await engine.ingest(_reading("heart_rate", 100.0, 1.0))
        assert engine.state_machine.current == STATE_RESTING  # 100*2=200 命中

    asyncio.run(scenario())


if __name__ == "__main__":
    test_aggregator_window_and_mean()
    test_rule_set_priority_and_cooldown()
    test_state_machine_transition_broadcasts()
    test_engine_ingest_rule_then_command()
    test_engine_telemetry_hook_can_transform()
    print("fusion smoke ok")