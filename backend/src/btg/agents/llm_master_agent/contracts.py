"""Strict LLM output contract and local fail-closed safety boundary."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .context import TelemetryContext


class ControlContractError(ValueError):
    """Untrusted LLM output did not satisfy the control contract."""


@dataclass(frozen=True)
class UnifiedControlCommand:
    """The only LLM command shape accepted by this agent."""

    action: Literal["set", "pause", "stop"]
    channel: str | None = None
    intensity: int | None = None
    duration_ms: int | None = None

    @classmethod
    def from_llm(cls, data: Any) -> "UnifiedControlCommand":
        if not isinstance(data, dict):
            raise ControlContractError("control must be a JSON object")
        allowed = {"action", "channel", "intensity", "duration_ms"}
        if set(data) - allowed:
            raise ControlContractError("control contains unknown fields")
        action = data.get("action")
        if action not in {"set", "pause", "stop"}:
            raise ControlContractError("action must be set, pause, or stop")
        if action != "set":
            if set(data) != {"action"}:
                raise ControlContractError("pause/stop cannot carry output parameters")
            return cls(action=action)
        channel = data.get("channel")
        intensity = data.get("intensity")
        duration_ms = data.get("duration_ms")
        if not isinstance(channel, str) or channel not in {"A", "B"}:
            raise ControlContractError("set channel must be A or B")
        if type(intensity) is not int or not 0 <= intensity <= 100:
            raise ControlContractError("intensity must be an integer in [0, 100]")
        if type(duration_ms) is not int or not 1 <= duration_ms <= 30_000:
            raise ControlContractError("duration_ms must be an integer in [1, 30000]")
        return cls(action="set", channel=channel, intensity=intensity, duration_ms=duration_ms)


class SafetyWrapper:
    """Convert a validated command to a safe gateway payload.

    This is intentionally non-escalating: LLM output can stop, pause, retain,
    or reduce an already-active channel only. It cannot turn on an idle channel,
    increase intensity, lengthen duration, create consent, or resume output.
    """

    def __init__(self, *, max_system_intensity: int) -> None:
        if not 0 <= max_system_intensity <= 100:
            raise ValueError("max_system_intensity must be in [0, 100]")
        self._max_system_intensity = max_system_intensity

    def to_gateway_payload(self, command: UnifiedControlCommand, context: TelemetryContext) -> dict[str, Any] | None:
        if not context.session_authorized or not context.session_id:
            return None
        if command.action == "stop":
            return {"action": "stop", "session_id": context.session_id, "reason": "llm_requested_stop"}
        if command.action == "pause":
            return {"action": "pause", "session_id": context.session_id, "reason": "llm_requested_pause"}

        assert command.channel is not None and command.intensity is not None and command.duration_ms is not None
        current_intensity = context.current_intensities.get(command.channel, 0)
        if current_intensity <= 0 or context.current_duration_ms <= 0:
            return None
        return {
            "channel": command.channel,
            "intensity": min(command.intensity, current_intensity, self._max_system_intensity),
            "duration_ms": min(command.duration_ms, context.current_duration_ms),
            "session_id": context.session_id,
        }
