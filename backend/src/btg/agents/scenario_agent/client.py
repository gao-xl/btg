"""Gateway adapters; the agent never connects to physical hardware directly."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any, Literal
from urllib import error, request

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import ActuatorCommand


class ActuatorControlRequest(BaseModel):
    """Versioned internal-control request sent by the Scenario Agent."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    source: Literal["scenario_agent"]
    scenario_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    actuator_id: str | None = None
    value: float
    unit: str = Field(min_length=1)


class GatewayResponseEnvelope(BaseModel):
    """Minimal validation of BTG's standard successful REST envelope."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["success"]
    code: int = Field(ge=200, lt=300)
    timestamp: float
    data: Any


class BTGClient:
    """Small async REST client for the BTG safety-checked actuator endpoint.

    The gateway is the policy-enforcement point: it authenticates this agent,
    checks consent/control-session state, clamps values, and audits commands.
    """

    def __init__(self, base_url: str, token: str, *, session_id: str, timeout_seconds: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session_id = session_id
        self.timeout_seconds = timeout_seconds

    async def send_actuator_command(self, command: ActuatorCommand, *, scenario_id: str, scene_id: str) -> None:
        payload = ActuatorControlRequest(
            session_id=self.session_id,
            source="scenario_agent",
            scenario_id=scenario_id,
            scene_id=scene_id,
            channel=command.channel,
            actuator_id=command.actuator_id,
            value=command.value,
            unit=command.unit,
        ).model_dump(exclude_none=True)
        await asyncio.to_thread(self._post_json, "/api/v1/control/actuators", payload)

    def _post_json(self, path: str, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{path}", body,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"gateway rejected command with HTTP {response.status}")
                GatewayResponseEnvelope.model_validate_json(response.read())
        except ValidationError as exc:
            raise RuntimeError("gateway returned a non-standard REST envelope") from exc
        except error.HTTPError as exc:
            raise RuntimeError(f"gateway rejected command with HTTP {exc.code}") from exc
        except error.URLError as exc:
            raise ConnectionError(f"cannot reach BTG gateway: {exc.reason}") from exc


class GatewayWebSocketSource:
    """Reconnectable event source for normalized gateway telemetry/STT messages."""

    def __init__(self, url: str, token: str, *, reconnect_delay_seconds: float = 1.0) -> None:
        self.url, self.token, self.reconnect_delay_seconds = url, token, reconnect_delay_seconds

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        import websockets

        while True:
            try:
                async with websockets.connect(self.url, additional_headers={"Authorization": f"Bearer {self.token}"}) as ws:
                    async for message in ws:
                        event = json.loads(message)
                        if isinstance(event, dict):
                            yield event
            except asyncio.CancelledError:
                raise
            except (OSError, ValueError, websockets.WebSocketException):
                await asyncio.sleep(self.reconnect_delay_seconds)


class WebSocketEventPublisher:
    """Publishes scenario lifecycle and TTS events to the gateway event bus."""

    def __init__(self, url: str, token: str) -> None:
        self.url, self.token = url, token

    async def publish(self, event: Mapping[str, Any]) -> None:
        import websockets

        async with websockets.connect(self.url, additional_headers={"Authorization": f"Bearer {self.token}"}) as ws:
            await ws.send(json.dumps(dict(event), ensure_ascii=False))
