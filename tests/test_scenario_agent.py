"""scenario_agent 冒烟测试：剧本 DSL 解析与状态机运行器。

独立运行：``python tests/test_scenario_agent.py``
pytest 运行：``pytest tests/``
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "sdk", _ROOT / "backend" / "src", _ROOT / "tests"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from btg.agents.scenario_agent.models import (  # noqa: E402
    ActuatorCommand,
    Scenario,
    ScenarioParser,
    Scene,
    WaitCondition,
)
from btg.agents.scenario_agent.runner import ScenarioRunner, ScenarioState  # noqa: E402


class FakeClient:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ActuatorCommand]] = []

    async def send_actuator_command(self, command, *, scenario_id, scene_id) -> None:
        self.commands.append((scene_id, command))


class FakeSource:
    def __init__(self, events) -> None:
        self._events = events

    async def events(self):
        for event in self._events:
            yield event


class FakePublisher:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, event) -> None:
        self.events.append(dict(event))


def test_transitions_on_telemetry_and_publishes_tts() -> None:
    scenario = Scenario(
        id="demo",
        start_scene="start",
        scenes={
            "start": Scene(
                id="start",
                tts_text="hello",
                actuator_cmds=(ActuatorCommand("tens_intensity", 1, "mA"),),
                wait_condition=WaitCondition("telemetry", "heart_rate_bpm", "gt", 120),
                on_success="done",
            ),
            "done": Scene(id="done", tts_text="finished"),
        },
    )
    client, publisher = FakeClient(), FakePublisher()

    async def scenario_run() -> ScenarioState:
        runner = ScenarioRunner(scenario, client, FakeSource([{"type": "telemetry", "heart_rate_bpm": 121}]), publisher)
        return await runner.run()

    assert asyncio.run(scenario_run()) is ScenarioState.COMPLETED
    assert client.commands[0][0] == "start"
    assert [e["text"] for e in publisher.events if e["type"] == "tts.request"] == ["hello", "finished"]


def test_pause_event_stops_without_transition() -> None:
    scenario = Scenario(
        id="demo",
        start_scene="start",
        scenes={
            "start": Scene(
                id="start",
                wait_condition=WaitCondition("stt", "text", "equals", "continue"),
                on_success="done",
            ),
            "done": Scene(id="done"),
        },
    )

    async def scenario_run() -> ScenarioState:
        runner = ScenarioRunner(scenario, FakeClient(), FakeSource([{"type": "pause"}]), FakePublisher())
        return await runner.run()

    assert asyncio.run(scenario_run()) is ScenarioState.STOPPED


def test_parser_loads_bundled_example_yaml() -> None:
    example = _ROOT / "backend" / "src" / "btg" / "agents" / "scenario_agent" / "examples" / "heart_rate_voice.yaml"
    scenario = ScenarioParser.load_file(example)
    assert scenario.start_scene in scenario.scenes


if __name__ == "__main__":
    test_transitions_on_telemetry_and_publishes_tts()
    test_pause_event_stops_without_transition()
    test_parser_loads_bundled_example_yaml()
    print("scenario agent smoke ok")
