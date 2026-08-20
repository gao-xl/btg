"""Asynchronous scenario state machine."""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from enum import Enum
from typing import Any, Protocol

from .models import ActuatorCommand, Scenario, Scene, WaitCondition


class ActuatorClient(Protocol):
    async def send_actuator_command(self, command: ActuatorCommand, *, scenario_id: str, scene_id: str) -> None: ...


class EventSource(Protocol):
    def events(self) -> AsyncIterator[dict[str, Any]]: ...


class EventPublisher(Protocol):
    async def publish(self, event: Mapping[str, Any]) -> None: ...


class ScenarioState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class ScenarioRunner:
    """Runs one scenario and serializes all scene transitions.

    Event input is normalized JSON, e.g. ``{"type":"telemetry", "heart_rate_bpm": 123}``
    or ``{"type":"stt", "text":"continue"}``. A stop/pause event ends the
    agent safely without issuing a follow-up command.
    """

    def __init__(self, scenario: Scenario, client: ActuatorClient, event_source: EventSource, publisher: EventPublisher) -> None:
        self.scenario, self.client, self.event_source, self.publisher = scenario, client, event_source, publisher
        self.state = ScenarioState.IDLE
        self.current_scene_id: str | None = None
        self._stop_requested = asyncio.Event()

    def request_stop(self) -> None:
        self._stop_requested.set()

    async def run(self) -> ScenarioState:
        if self.state is not ScenarioState.IDLE:
            raise RuntimeError("a ScenarioRunner instance can only run once")
        self.state = ScenarioState.RUNNING
        self.current_scene_id = self.scenario.start_scene
        await self._publish("scenario.started")
        try:
            while self.current_scene_id and not self._stop_requested.is_set():
                scene = self.scenario.scenes[self.current_scene_id]
                next_scene = await self._run_scene(scene)
                self.current_scene_id = next_scene
            self.state = ScenarioState.STOPPED if self._stop_requested.is_set() else ScenarioState.COMPLETED
        except Exception as exc:
            self.state = ScenarioState.FAILED
            await self._publish("scenario.failed", error=str(exc))
            raise
        finally:
            await self._publish("scenario.finished", state=self.state.value)
        return self.state

    async def _run_scene(self, scene: Scene) -> str | None:
        await self._publish("scenario.scene_entered", scene_id=scene.id)
        if scene.tts_text:
            await self._publish("tts.request", scene_id=scene.id, text=scene.tts_text)
        for command in scene.actuator_cmds:
            if self._stop_requested.is_set():
                return None
            await self.client.send_actuator_command(command, scenario_id=self.scenario.id, scene_id=scene.id)
        if scene.wait_condition is None:
            return scene.on_success
        outcome = await self._wait_for(scene.wait_condition)
        return scene.on_success if outcome == "success" else scene.on_timeout

    async def _wait_for(self, condition: WaitCondition) -> str:
        deadline = time.monotonic() + condition.timeout_seconds if condition.timeout_seconds else None
        matched_since: float | None = None
        async for event in self.event_source.events():
            if self._stop_requested.is_set() or event.get("type") in {"stop", "pause", "emergency_stop"}:
                self._stop_requested.set()
                return "stopped"
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                return "timeout"
            if self._matches(condition, event):
                matched_since = matched_since or now
                if now - matched_since >= condition.duration_seconds:
                    return "success"
            else:
                matched_since = None
        return "timeout"

    @staticmethod
    def _matches(condition: WaitCondition, event: Mapping[str, Any]) -> bool:
        if event.get("type") != condition.event_type or condition.field not in event:
            return False
        actual, expected = event[condition.field], condition.value
        try:
            return {
                "equals": lambda: actual == expected,
                "contains": lambda: isinstance(actual, str) and str(expected) in actual,
                "gt": lambda: actual > expected,
                "gte": lambda: actual >= expected,
                "lt": lambda: actual < expected,
                "lte": lambda: actual <= expected,
            }[condition.operator]()
        except TypeError:
            return False

    async def _publish(self, event_type: str, **payload: Any) -> None:
        await self.publisher.publish({"type": event_type, "scenario_id": self.scenario.id, **payload})
