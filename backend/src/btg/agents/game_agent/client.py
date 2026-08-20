"""Minimal asynchronous client for BTG's public Integration API."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class GatewayUnavailable(ConnectionError):
    """The gateway did not accept a control request and should be retried."""


class IntegrationControlRequest(BaseModel):
    """Validated payload for ``POST /integration/v1/control``."""

    model_config = ConfigDict(extra="forbid")

    channel: str | None = Field(default=None, min_length=1)
    mode: str | None = Field(default=None, min_length=1)
    intensity: int = Field(ge=0, le=100)
    duration_ms: int = Field(gt=0, le=60_000)


class GatewayResponseEnvelope(BaseModel):
    """Minimal validation of BTG's standard successful REST envelope."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["success"]
    code: int = Field(ge=200, lt=300)
    timestamp: float
    data: Any


class BTGClient:
    """Async HTTP client for ``POST /integration/v1/control``.

    It uses the Python standard library so the standalone agent has no runtime
    dependency beyond Python 3.10+. Replace this class with the shared SDK
    client later without changing the tailing or retry pipeline.
    """

    def __init__(self, gateway_url: str, *, api_token: str | None = None, timeout_s: float = 5.0) -> None:
        self._control_url = f"{gateway_url.rstrip('/')}/integration/v1/control"
        self._api_token = api_token
        self._timeout_s = timeout_s

    async def send_control(self, payload: dict[str, Any]) -> None:
        try:
            request_payload = IntegrationControlRequest.model_validate(payload)
        except ValidationError as exc:
            raise ValueError("invalid integration control payload") from exc
        await asyncio.to_thread(self._send_control_sync, request_payload.model_dump(exclude_none=True))

    def _send_control_sync(self, payload: dict[str, Any]) -> None:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"
        request = Request(
            self._control_url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_s) as response:
                if not 200 <= response.status < 300:
                    raise GatewayUnavailable(f"gateway returned HTTP {response.status}")
                GatewayResponseEnvelope.model_validate_json(response.read())
        except HTTPError as exc:
            raise GatewayUnavailable(f"gateway returned HTTP {exc.code}") from exc
        except ValidationError as exc:
            raise GatewayUnavailable("gateway returned a non-standard REST envelope") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise GatewayUnavailable("gateway is unavailable") from exc
