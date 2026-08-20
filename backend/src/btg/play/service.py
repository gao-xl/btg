"""In-memory play session orchestration with a non-actuating AI boundary."""
from __future__ import annotations

from dataclasses import dataclass
import secrets
import time
from typing import Any, Callable
from uuid import uuid4

from .models import PlayDecisionRequest, StartPlaySessionRequest
from .waves import WaveformCatalog


class PlaySessionError(ValueError):
    pass


@dataclass(frozen=True)
class PlaySession:
    id: str
    control_session_id: str
    channels: str
    parts: dict[str, str]
    caps: dict[str, int]
    created_at: float


class PlaySessionManager:
    """Holds personalization and evaluates model suggestions.

    A play session is not a control lease.  Results are previews/advice and are
    never dispatched to the HAL from this class.
    """

    def __init__(
        self,
        catalog: WaveformCatalog | None = None,
        *,
        max_sessions: int = 128,
        session_ttl_seconds: float = 3600,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_sessions <= 0 or session_ttl_seconds <= 0:
            raise ValueError("session limits must be positive")
        self.catalog = catalog or WaveformCatalog()
        self._sessions: dict[str, PlaySession] = {}
        self._max_sessions = max_sessions
        self._session_ttl_seconds = session_ttl_seconds
        self._clock = clock

    def start(self, request: StartPlaySessionRequest) -> PlaySession:
        if request.consent_confirmed is not True:
            raise PlaySessionError("explicit consent confirmation is required")
        self._prune_expired()
        if len(self._sessions) >= self._max_sessions:
            raise PlaySessionError("too many active play sessions")
        session = PlaySession(
            id=str(uuid4()),
            control_session_id=request.control_session_id,
            channels=request.channels,
            parts={"A": request.part_a, "B": request.part_b},
            caps={"A": request.cap_a, "B": request.cap_b},
            created_at=self._clock(),
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> PlaySession:
        try:
            session = self._sessions[session_id]
        except KeyError as exc:
            raise PlaySessionError("play session not found") from exc
        if self._clock() - session.created_at >= self._session_ttl_seconds:
            del self._sessions[session_id]
            raise PlaySessionError("play session expired")
        return session

    def stop(self, session_id: str) -> PlaySession:
        session = self.get(session_id)
        del self._sessions[session_id]
        return session

    def evaluate(self, session_id: str, decision: PlayDecisionRequest) -> dict[str, Any]:
        session = self.get(session_id)
        directive = decision.directive
        result: dict[str, Any] = {
            "dialogue": decision.dialogue,
            "action": directive.action,
            "actuated": False,
            "operator_confirmation_required": directive.action.startswith("recommend_"),
        }
        if directive.action in {"pause", "stop", "clear"}:
            if directive.channel:
                self._ensure_channel(session, directive.channel)
                result["channel"] = directive.channel
            result["safety_only"] = True
            return result
        if directive.action == "reduce":
            assert directive.channel is not None and directive.target_strength is not None
            self._ensure_channel(session, directive.channel)
            current = decision.current_strengths.get(directive.channel)
            if current is None:
                raise PlaySessionError("reduce requires the current channel strength")
            if directive.target_strength > current:
                raise PlaySessionError("AI directives cannot increase strength")
            result.update(
                channel=directive.channel,
                target_strength=min(directive.target_strength, session.caps[directive.channel]),
                safety_only=True,
            )
            return result

        assert directive.channel is not None
        self._ensure_channel(session, directive.channel)
        wave_key = directive.wave if directive.action == "recommend_wave" else secrets.choice(self.catalog.keys())
        try:
            wave = self.catalog.get(wave_key)
        except KeyError as exc:
            raise PlaySessionError(str(exc)) from exc
        channels = ("A", "B") if directive.channel == "AB" else (directive.channel,)
        result.update(
            channel=directive.channel,
            wave={"key": wave.key, "name": wave.name, "description": wave.description},
            previews={channel: wave.preview(session.caps[channel]) for channel in channels},
            notice="Preview only. Apply manually through an authorized control path.",
        )
        return result

    @staticmethod
    def _ensure_channel(session: PlaySession, channel: str) -> None:
        allowed = {"A", "B"} if session.channels == "AB" else {session.channels}
        requested = {"A", "B"} if channel == "AB" else {channel}
        if not requested <= allowed:
            raise PlaySessionError("directive uses a channel outside this play session")

    def _prune_expired(self) -> None:
        now = self._clock()
        expired = [
            session_id for session_id, session in self._sessions.items()
            if now - session.created_at >= self._session_ttl_seconds
        ]
        for session_id in expired:
            del self._sessions[session_id]

    @staticmethod
    def public(session: PlaySession) -> dict[str, Any]:
        return {
            "id": session.id,
            "control_session_id": session.control_session_id,
            "channels": session.channels,
            "parts": session.parts,
            "caps": session.caps,
            "created_at": session.created_at,
            "actuation_enabled": False,
        }
