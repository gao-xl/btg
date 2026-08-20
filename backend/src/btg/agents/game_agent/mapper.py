"""Hot-reloadable, safety-bounded mapping from game telemetry to BTG requests.

This module does not communicate with devices.  It produces a requested
0--100 intensity only; BTG's integration, consent/session, clamp and watchdog
layers remain the final authority for every command.
"""
from __future__ import annotations

import asyncio
import math
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml


class GameEventLike(Protocol):
    """Minimal event contract, avoiding a dependency on the log parser module."""

    name: str
    fields: Mapping[str, Any]


class RulesValidationError(ValueError):
    """Raised when ``game_rules.yaml`` has an invalid tuning value."""


@dataclass(frozen=True, slots=True)
class EventRule:
    """Tuning parameters for one normalized game event."""

    base_intensity: int
    cooldown_ms: int
    duration_ms: int
    gain: float = 1.0
    channel: str | None = "A"
    mode: str | None = None


@dataclass(frozen=True, slots=True)
class GameRules:
    """Validated mutable-at-runtime mapping configuration snapshot."""

    global_gain: float = 1.0
    events: Mapping[str, EventRule] = field(default_factory=dict)

    @classmethod
    def load_file(cls, path: str | Path) -> "GameRules":
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise RulesValidationError(f"cannot read game rules: {exc}") from exc
        except yaml.YAMLError as exc:
            raise RulesValidationError(f"invalid game rules YAML: {exc}") from exc
        return cls.from_mapping(raw)

    @classmethod
    def from_mapping(cls, raw: Any) -> "GameRules":
        if not isinstance(raw, Mapping):
            raise RulesValidationError("game rules root must be a mapping")
        global_gain = _as_float(raw.get("global_gain", 1.0), "global_gain")
        _validate_global_gain(global_gain)
        raw_events = raw.get("events", {})
        if not isinstance(raw_events, Mapping):
            raise RulesValidationError("events must be a mapping")
        events: dict[str, EventRule] = {}
        for name, raw_rule in raw_events.items():
            if not isinstance(name, str) or not name.strip():
                raise RulesValidationError("event names must be non-empty strings")
            events[name.lower()] = _parse_event_rule(name, raw_rule)
        return cls(global_gain=global_gain, events=events)


class EventMapper:
    """Maps events using the current rules and enforces per-event cooldowns.

    ``reload_from_file`` atomically replaces all event rules.  For a fast
    gateway control path, ``apply_gateway_update`` updates only ``global_gain``
    without resetting event cooldown timestamps.  Call ``sync_global_gain`` in
    any periodic gateway polling task when a pull model is preferred.
    """

    def __init__(self, rules: GameRules | None = None) -> None:
        self._rules = rules or _default_rules()
        self._last_triggered_ms: dict[str, float] = {}
        self._lock = threading.RLock()

    @property
    def rules(self) -> GameRules:
        with self._lock:
            return self._rules

    def reload_from_file(self, path: str | Path) -> GameRules:
        """Hot-reload all rules after complete validation; failure keeps old rules."""
        new_rules = GameRules.load_file(path)
        with self._lock:
            self._rules = new_rules
        return new_rules

    def apply_gateway_update(self, update: float | Mapping[str, Any]) -> GameRules:
        """Apply a gateway/API ``global_gain`` update, validating 0.1--2.0."""
        raw_gain = update.get("global_gain") if isinstance(update, Mapping) else update
        gain = _as_float(raw_gain, "global_gain")
        _validate_global_gain(gain)
        with self._lock:
            self._rules = GameRules(global_gain=gain, events=self._rules.events)
            return self._rules

    async def sync_global_gain(
        self, fetch_update: Callable[[], Awaitable[float | Mapping[str, Any]]]
    ) -> GameRules:
        """Fetch and apply one gateway update; scheduling policy stays with caller."""
        return self.apply_gateway_update(await fetch_update())

    def map(self, event: GameEventLike, *, now_ms: float | None = None) -> dict[str, Any] | None:
        """Return a gateway payload or ``None`` for unknown, invalid, or cooled events.

        The preferred source field is ``damage_amount``.  ``value`` is accepted
        for compatibility with existing BTG log emitters.  If neither is present,
        ``base_intensity`` is used.  The requested intensity is calculated as:
        ``min(100, int(raw_value * event_rule.gain * global_gain))``.
        """
        event_name = event.name.lower()
        current_ms = time.monotonic() * 1000 if now_ms is None else now_ms
        with self._lock:
            rules = self._rules
            rule = rules.events.get(event_name)
            if rule is None:
                return None
            previous_ms = self._last_triggered_ms.get(event_name)
            if previous_ms is not None and current_ms - previous_ms < rule.cooldown_ms:
                return None

            raw_value = event.fields.get("damage_amount", event.fields.get("value", rule.base_intensity))
            if not _is_finite_number(raw_value) or raw_value < 0:
                return None
            intensity = min(100, int(raw_value * rule.gain * rules.global_gain))
            self._last_triggered_ms[event_name] = current_ms

        payload: dict[str, Any] = {"intensity": intensity, "duration_ms": rule.duration_ms}
        if rule.channel is not None:
            payload["channel"] = rule.channel
        if rule.mode is not None:
            payload["mode"] = rule.mode
        return payload


def _default_rules() -> GameRules:
    """Compatibility defaults used when no YAML file has been loaded yet."""
    return GameRules(
        global_gain=1.0,
        events={
            "player_damage": EventRule(base_intensity=0, gain=1.0, cooldown_ms=0, duration_ms=300),
            "player_death": EventRule(base_intensity=80, gain=1.0, cooldown_ms=0, duration_ms=1500, channel=None, mode="surge"),
        },
    )


def _parse_event_rule(name: str, raw: Any) -> EventRule:
    if not isinstance(raw, Mapping):
        raise RulesValidationError(f"events.{name} must be a mapping")
    base_intensity = _as_int(raw.get("base_intensity"), f"events.{name}.base_intensity")
    cooldown_ms = _as_int(raw.get("cooldown_ms"), f"events.{name}.cooldown_ms")
    duration_ms = _as_int(raw.get("duration_ms"), f"events.{name}.duration_ms")
    gain = _as_float(raw.get("gain", 1.0), f"events.{name}.gain")
    if not 0 <= base_intensity <= 100:
        raise RulesValidationError(f"events.{name}.base_intensity must be in [0, 100]")
    if cooldown_ms < 0 or duration_ms < 0:
        raise RulesValidationError(f"events.{name} cooldown_ms and duration_ms must be non-negative")
    if not 0 <= gain <= 100:
        raise RulesValidationError(f"events.{name}.gain must be in [0, 100]")
    channel = raw.get("channel", "A")
    mode = raw.get("mode")
    if not isinstance(channel, str) or not channel:
        raise RulesValidationError(f"events.{name}.channel must be a non-empty string")
    if mode is not None and (not isinstance(mode, str) or not mode):
        raise RulesValidationError(f"events.{name}.mode must be a non-empty string when provided")
    return EventRule(base_intensity, cooldown_ms, duration_ms, gain, channel, mode)


def _as_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RulesValidationError(f"{field_name} must be a finite number")
    return float(value)


def _as_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RulesValidationError(f"{field_name} must be an integer")
    return value


def _validate_global_gain(value: float) -> None:
    if not 0.1 <= value <= 2.0:
        raise RulesValidationError("global_gain must be in [0.1, 2.0]")


def _is_finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
