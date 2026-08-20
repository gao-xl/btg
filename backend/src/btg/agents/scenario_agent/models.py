"""Validated scenario-file data model.  Conditions deliberately do not execute code."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


class ScenarioValidationError(ValueError):
    """Raised when a scenario file is structurally unsafe or incomplete."""


@dataclass(frozen=True, slots=True)
class ActuatorCommand:
    channel: str
    value: float
    unit: str
    actuator_id: str | None = None


@dataclass(frozen=True, slots=True)
class WaitCondition:
    """One declarative event predicate.

    ``event_type`` normally is ``telemetry`` or ``stt``.  ``duration_seconds``
    requires a numeric predicate to remain true across incoming observations.
    """

    event_type: str
    field: str
    operator: str = "equals"
    value: Any = None
    duration_seconds: float = 0.0
    timeout_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class Scene:
    id: str
    tts_text: str | None = None
    actuator_cmds: tuple[ActuatorCommand, ...] = ()
    wait_condition: WaitCondition | None = None
    on_success: str | None = None
    on_timeout: str | None = None


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    start_scene: str
    scenes: Mapping[str, Scene]
    metadata: Mapping[str, Any] = field(default_factory=dict)


class ScenarioParser:
    """Loads and validates the limited YAML scenario DSL."""

    _OPERATORS = {"equals", "contains", "gt", "gte", "lt", "lte"}

    @classmethod
    def load_file(cls, path: str | Path) -> Scenario:
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise ScenarioValidationError(f"cannot read scenario file: {exc}") from exc
        except yaml.YAMLError as exc:
            raise ScenarioValidationError(f"invalid YAML: {exc}") from exc
        return cls.parse(raw)

    @classmethod
    def parse(cls, raw: Any) -> Scenario:
        if not isinstance(raw, dict):
            raise ScenarioValidationError("scenario root must be a mapping")
        scenario_id = cls._string(raw.get("id"), "id")
        start_scene = cls._string(raw.get("start_scene"), "start_scene")
        raw_scenes = raw.get("scenes")
        if not isinstance(raw_scenes, list) or not raw_scenes:
            raise ScenarioValidationError("scenes must be a non-empty list")

        scenes: dict[str, Scene] = {}
        for item in raw_scenes:
            scene = cls._parse_scene(item)
            if scene.id in scenes:
                raise ScenarioValidationError(f"duplicate scene id: {scene.id}")
            scenes[scene.id] = scene
        if start_scene not in scenes:
            raise ScenarioValidationError("start_scene must name an existing scene")
        for scene in scenes.values():
            for target in (scene.on_success, scene.on_timeout):
                if target is not None and target not in scenes:
                    raise ScenarioValidationError(
                        f"scene {scene.id} references unknown target {target}"
                    )
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ScenarioValidationError("metadata must be a mapping")
        return Scenario(scenario_id, start_scene, scenes, metadata)

    @classmethod
    def _parse_scene(cls, raw: Any) -> Scene:
        if not isinstance(raw, dict):
            raise ScenarioValidationError("every scene must be a mapping")
        scene_id = cls._string(raw.get("id"), "scene.id")
        tts_text = raw.get("tts_text")
        if tts_text is not None and not isinstance(tts_text, str):
            raise ScenarioValidationError(f"scene {scene_id}.tts_text must be a string")
        commands_raw = raw.get("actuator_cmds", [])
        if not isinstance(commands_raw, list):
            raise ScenarioValidationError(f"scene {scene_id}.actuator_cmds must be a list")
        commands = tuple(cls._parse_command(scene_id, cmd) for cmd in commands_raw)
        condition = raw.get("wait_condition")
        return Scene(
            id=scene_id,
            tts_text=tts_text,
            actuator_cmds=commands,
            wait_condition=cls._parse_condition(scene_id, condition) if condition else None,
            on_success=cls._optional_string(raw.get("on_success"), f"scene {scene_id}.on_success"),
            on_timeout=cls._optional_string(raw.get("on_timeout"), f"scene {scene_id}.on_timeout"),
        )

    @classmethod
    def _parse_command(cls, scene_id: str, raw: Any) -> ActuatorCommand:
        if not isinstance(raw, dict):
            raise ScenarioValidationError(f"scene {scene_id} command must be a mapping")
        value = raw.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScenarioValidationError(f"scene {scene_id} command value must be numeric")
        return ActuatorCommand(
            channel=cls._string(raw.get("channel"), "command.channel"),
            value=float(value),
            unit=cls._string(raw.get("unit"), "command.unit"),
            actuator_id=cls._optional_string(raw.get("actuator_id"), "command.actuator_id"),
        )

    @classmethod
    def _parse_condition(cls, scene_id: str, raw: Any) -> WaitCondition:
        if not isinstance(raw, dict):
            raise ScenarioValidationError(f"scene {scene_id}.wait_condition must be a mapping")
        operator = raw.get("operator", "equals")
        if operator not in cls._OPERATORS:
            raise ScenarioValidationError(f"unsupported operator: {operator}")
        duration = raw.get("duration_seconds", 0.0)
        timeout = raw.get("timeout_seconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration < 0:
            raise ScenarioValidationError("duration_seconds must be a non-negative number")
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0):
            raise ScenarioValidationError("timeout_seconds must be a positive number")
        return WaitCondition(
            event_type=cls._string(raw.get("event_type"), "wait_condition.event_type"),
            field=cls._string(raw.get("field"), "wait_condition.field"),
            operator=operator,
            value=raw.get("value"),
            duration_seconds=float(duration),
            timeout_seconds=float(timeout) if timeout is not None else None,
        )

    @staticmethod
    def _string(value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ScenarioValidationError(f"{field_name} must be a non-empty string")
        return value

    @classmethod
    def _optional_string(cls, value: Any, field_name: str) -> str | None:
        return None if value is None else cls._string(value, field_name)
