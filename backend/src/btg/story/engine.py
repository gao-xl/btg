"""独立剧情执行引擎：章节化场景图 + 跨章分支转移的状态机。

与 :mod:`btg.agents.scenario_agent` 的 :class:`ScenarioRunner` 平级但独立：
剧情支持章节、每个场景的多条分支转移（可跨章节跳转）与超时出口。

引擎通过三个注入协议与外界交互（区别于直连硬件）：

- :class:`ActuatorWriter` 把场景执行指令发给安全的下行通道；
- :class:`EventSource` 提供归一化事件流（``telemetry`` / ``stt``）；
- :class:`EventSink` 广播剧情生命周期与 TTS 请求。

任一分支转移命中即跳到目标场景；无转移也不超时的场景视为终场，
引擎安全结束。
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Mapping
from enum import Enum
from typing import Any, Protocol

from .models import END, Story, StoryActuatorCommand, StoryScene


class ActuatorWriter(Protocol):
    """把一条剧情执行指令送达安全下行通道。"""

    async def send_actuator_command(self, command: StoryActuatorCommand, *, story_id: str, scene_id: str) -> None: ...


class EventSource(Protocol):
    """归一化事件流的异步迭代源。"""

    def events(self) -> AsyncIterator[dict[str, Any]]: ...


class EventSink(Protocol):
    """剧情生命周期与 TTS 事件广播。"""

    async def publish(self, event: Mapping[str, Any]) -> None: ...


class StoryState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class StoryEngine:
    """驱动一部剧情前进的独立状态机（每实例只运行一次）。"""

    def __init__(self, story: Story, writer: ActuatorWriter, event_source: EventSource, sink: EventSink) -> None:
        self.story = story
        self.writer = writer
        self.event_source = event_source
        self.sink = sink
        self.state = StoryState.IDLE
        self.current_scene_id: str | None = None
        self._stop_requested = asyncio.Event()

    def request_stop(self) -> None:
        self._stop_requested.set()

    async def run(self) -> StoryState:
        if self.state is not StoryState.IDLE:
            raise RuntimeError("a StoryEngine instance can only run once")
        self.state = StoryState.RUNNING
        self.current_scene_id = self.story.start_scene
        await self._publish("story.started")
        try:
            while self.current_scene_id and not self._stop_requested.is_set():
                scene = self.story.scenes[self.current_scene_id]
                await self._run_scene(scene)
                if self.current_scene_id == END:
                    self.current_scene_id = None
                    break
            self.state = StoryState.STOPPED if self._stop_requested.is_set() else StoryState.COMPLETED
        except Exception as exc:
            self.state = StoryState.FAILED
            await self._publish("story.failed", error=str(exc))
            raise
        finally:
            await self._publish("story.finished", state=self.state.value)
        return self.state

    async def _run_scene(self, scene: StoryScene) -> None:
        self.current_scene_id = scene.id
        await self._publish("story.scene_entered", scene_id=scene.id, chapter=scene.chapter)
        if scene.tts_text:
            await self._publish("tts.request", scene_id=scene.id, text=scene.tts_text)
        if scene.actor_text and scene.actor_text != scene.tts_text:
            await self._publish("story.actor", scene_id=scene.id, text=scene.actor_text)
        for command in scene.actuator_cmds:
            if self._stop_requested.is_set():
                self.current_scene_id = None
                return
            await self._publish(
                "story.actuate",
                scene_id=scene.id,
                channel=command.channel,
                value=command.value,
                unit=command.unit,
            )
            await self.writer.send_actuator_command(command, story_id=self.story.id, scene_id=scene.id)
        self.current_scene_id = await self._wait_for(scene)

    async def _wait_for(self, scene: StoryScene) -> str | None:
        """消费事件流直到命中分支、超时或收到停止请求，返回下一场景。

        返回 ``None`` 表示受停止/终场控制，外部循环据此结束。
        """
        if not scene.transitions and scene.timeout is None:
            return None  # 无出口的终场场景
        deadline: float | None = None
        timeout_target: str | None = None
        if scene.timeout is not None:
            deadline = time.monotonic() + scene.timeout.seconds
            timeout_target = scene.timeout.target
        async for event in self.event_source.events():
            if self._stop_requested.is_set():
                return None
            if event.get("type") in {"stop", "pause", "emergency_stop"}:
                self._stop_requested.set()
                return None
            if deadline is not None and time.monotonic() >= deadline:
                return timeout_target
            for transition in scene.transitions:
                if self._matches(transition, event):
                    return transition.target
        return None

    @classmethod
    def _matches(cls, transition: Any, event: Mapping[str, Any]) -> bool:
        """判定一条转移规则是否被事件命中（纯声明式，不执行代码）。"""
        if event.get("type") != transition.event_type or transition.field not in event:
            return False
        actual, expected = event[transition.field], transition.value
        try:
            return {
                "equals": lambda: actual == expected,
                "contains": lambda: isinstance(actual, str) and str(expected) in actual,
                "gt": lambda: actual > expected,
                "gte": lambda: actual >= expected,
                "lt": lambda: actual < expected,
                "lte": lambda: actual <= expected,
            }[transition.operator]()
        except TypeError:
            return False

    async def _publish(self, event_type: str, **payload: Any) -> None:
        await self.sink.publish({"type": event_type, "story_id": self.story.id, **payload})


__all__ = ["ActuatorWriter", "EventSource", "EventSink", "StoryState", "StoryEngine"]