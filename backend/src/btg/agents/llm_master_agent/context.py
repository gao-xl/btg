"""Structured multimodal context collection for the LLM master agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class TelemetryContext:
    """One bounded snapshot. No image bytes are retained in this object."""

    heart_rate_bpm: float | None
    imu_struggling: bool
    current_intensities: dict[str, int]
    current_duration_ms: int
    session_id: str | None
    session_authorized: bool
    image_path: Path | None = None
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def prompt_data(self) -> dict[str, Any]:
        return {
            "heart_rate_bpm": self.heart_rate_bpm,
            "imu_struggling": self.imu_struggling,
            "current_intensities": self.current_intensities,
            "current_duration_ms": self.current_duration_ms,
            "session_id": self.session_id,
            "session_authorized": self.session_authorized,
            "captured_at": self.captured_at.isoformat(),
        }


class TelemetrySource(Protocol):
    async def fetch(self) -> TelemetryContext: ...


class WebSocketTelemetrySource:
    """Fetch a JSON snapshot from a trusted local telemetry WebSocket.

    Expected JSON keys are ``heart_rate_bpm``, ``imu_struggling``,
    ``current_intensities``, ``current_duration_ms``, ``session_id`` and
    ``session_authorized``. Session authorization must come from the gateway;
    it is never inferred from sensor data or an LLM response.
    """

    def __init__(self, ws_url: str, *, image_path: Path | None = None) -> None:
        self._ws_url = ws_url
        self._image_path = image_path

    async def fetch(self) -> TelemetryContext:
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - deployment dependency
            raise RuntimeError("Install 'websockets' to use WebSocketTelemetrySource") from exc
        async with websockets.connect(self._ws_url, open_timeout=5, close_timeout=2) as websocket:
            raw = await websocket.recv()
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("telemetry WebSocket returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("telemetry WebSocket JSON must be an object")
        raw_intensities = data.get("current_intensities", {})
        if not isinstance(raw_intensities, dict):
            raise ValueError("current_intensities must be an object")
        intensities = {str(channel): int(value) for channel, value in raw_intensities.items()}
        image = self._image_path if self._image_path and self._image_path.is_file() else None
        return TelemetryContext(
            heart_rate_bpm=float(data["heart_rate_bpm"]) if data.get("heart_rate_bpm") is not None else None,
            imu_struggling=bool(data.get("imu_struggling", False)),
            current_intensities=intensities,
            current_duration_ms=int(data.get("current_duration_ms", 0)),
            session_id=str(data["session_id"]) if data.get("session_id") else None,
            session_authorized=data.get("session_authorized") is True,
            image_path=image,
            captured_at=datetime.now(timezone.utc),
        )
