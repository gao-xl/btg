"""Strict public contracts for conversational play sessions."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Channel = Literal["A", "B", "AB"]


class StartPlaySessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_session_id: str = Field(min_length=1, max_length=128)
    consent_confirmed: bool
    channels: Channel = "AB"
    part_a: str = Field(default="A 通道", min_length=1, max_length=80)
    part_b: str = Field(default="B 通道", min_length=1, max_length=80)
    cap_a: int = Field(default=0, ge=0, le=100)
    cap_b: int = Field(default=0, ge=0, le=100)


class PlayDirective(BaseModel):
    """A non-actuating directive produced by an untrusted model."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["recommend_wave", "recommend_random", "reduce", "pause", "stop", "clear"]
    channel: Channel | None = None
    wave: str | None = Field(default=None, min_length=1, max_length=64)
    target_strength: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_shape(self) -> "PlayDirective":
        if self.action == "recommend_wave":
            if self.channel is None or self.wave is None or self.target_strength is not None:
                raise ValueError("recommend_wave requires only channel and wave")
        elif self.action in {"recommend_random", "clear"}:
            if self.channel is None or self.wave is not None or self.target_strength is not None:
                raise ValueError(f"{self.action} requires only channel")
        elif self.action == "reduce":
            if self.channel not in {"A", "B"} or self.target_strength is None or self.wave is not None:
                raise ValueError("reduce requires channel A or B and target_strength")
        elif self.channel is not None or self.wave is not None or self.target_strength is not None:
            raise ValueError("pause/stop cannot carry output parameters")
        return self


class PlayDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dialogue: str = Field(min_length=1, max_length=2000)
    directive: PlayDirective
    current_strengths: dict[Literal["A", "B"], int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_strengths(self) -> "PlayDecisionRequest":
        if any(type(value) is not int or not 0 <= value <= 100 for value in self.current_strengths.values()):
            raise ValueError("current strengths must be integers in [0, 100]")
        return self
