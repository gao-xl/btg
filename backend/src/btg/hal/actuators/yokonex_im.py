"""YOKONEX actuator bridge using the vendor's local IM-to-HTTP service.

The vendor app owns device pairing and the physical action associated with each
game event ID.  BTG only sends explicitly configured event IDs after the normal
safety pipeline has approved and clamped a normalized 0--100 target.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import math
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from btg_sdk import (
    BaseActuator,
    DeviceFeedback,
    FeedbackKind,
    register_actuator,
)
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

LOGGER = logging.getLogger(__name__)


class YokoNexCommandLevel(BaseModel):
    """One upper-bound bucket in the normalized BTG-to-event mapping."""

    model_config = ConfigDict(extra="forbid")

    max_value: float = Field(gt=0.0, le=100.0)
    command_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


class YokoNexImConfig(BaseModel):
    """Strict configuration boundary for the unauthenticated local bridge."""

    model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(default="yokonex_im", min_length=1)
    bridge_url: AnyHttpUrl = "http://127.0.0.1:3001"
    timeout_seconds: float = Field(default=5.0, gt=0.0, le=30.0)
    allow_remote_bridge: bool = False
    stop_command_id: str = Field(
        default="_stop_all",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    levels: list[YokoNexCommandLevel] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bridge_and_levels(self) -> "YokoNexImConfig":
        parsed = urlsplit(str(self.bridge_url))
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("bridge_url must not contain credentials, a query, or a fragment")
        if parsed.path not in ("", "/"):
            raise ValueError("bridge_url must be an origin without an API path")
        is_loopback = _is_loopback_host(parsed.hostname or "")
        if not self.allow_remote_bridge and not is_loopback:
            raise ValueError(
                "remote API-bridge is disabled because its HTTP API has no authentication; "
                "use localhost or explicitly set allow_remote_bridge=true behind a trusted tunnel"
            )
        if not is_loopback and parsed.scheme != "https":
            raise ValueError("a remote API-bridge requires HTTPS")

        bounds = [level.max_value for level in self.levels]
        if len(bounds) != len(set(bounds)):
            raise ValueError("levels must not contain duplicate max_value boundaries")
        if max(bounds) != 100.0:
            raise ValueError("levels must include max_value=100 so every non-zero target is mapped")
        return self


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@register_actuator("yokonex_im")
class YokoNexImActuator(BaseActuator):
    """Dispatch approved targets to YOKONEX game-event IDs via API-bridge.

    ``levels`` are inclusive upper bounds.  For example, boundaries 25, 50,
    and 100 map a target of 30 to the command at 50.  The actual waveform and
    physical output remain configured and capped by the user in the YOKONEX
    app.  A zero target always uses ``_stop_all`` (or the configured stop ID).
    """

    def __init__(self, config: Mapping[str, Any]) -> None:
        validated = YokoNexImConfig.model_validate(dict(config))
        self.instance_id = validated.instance_id
        self.bridge_url = str(validated.bridge_url).rstrip("/")
        self.timeout_seconds = validated.timeout_seconds
        self.stop_command_id = validated.stop_command_id
        self.levels = tuple(sorted(validated.levels, key=lambda item: item.max_value))
        marker = ":yokonex_im:"
        self.channel = (
            self.instance_id.rsplit(marker, 1)[0]
            if marker in self.instance_id
            else ""
        )
        self._client: Any | None = None
        self._connected = False
        self._lock = asyncio.Lock()

    async def connect(self) -> bool:
        """Require both the local bridge and its IM session to be ready."""
        async with self._lock:
            if self._connected:
                return True
            try:
                client = await self._get_client_locked()
                response = await client.get(f"{self.bridge_url}/health")
                response.raise_for_status()
                data = response.json()
                if data.get("status") != "ok" or data.get("imReady") is not True:
                    raise ConnectionError("YOKONEX API-bridge is running but IM is not ready")
            except asyncio.CancelledError:
                await self._close_client_locked()
                raise
            except Exception as exc:
                await self._close_client_locked()
                raise ConnectionError(f"YOKONEX API-bridge health check failed: {exc}") from exc
            self._connected = True
            return True

    async def disconnect(self) -> None:
        """Fail closed: request a global stop before releasing the HTTP client."""
        await self._stop_and_close()

    async def set_target(self, channel: str, value: float) -> bool:
        """Map a normalized safe target to one explicitly configured event ID."""
        if not math.isfinite(value) or not 0.0 <= value <= 100.0:
            raise ValueError("YOKONEX IM actuator accepts finite normalized values in [0, 100]")
        if self.channel and channel != self.channel:
            raise ValueError(
                f"YOKONEX actuator {self.instance_id!r} belongs to channel {self.channel!r}, "
                f"not {channel!r}"
            )
        async with self._lock:
            self._ensure_connected()
            command_id = self._command_for(value)
            try:
                await self._send_command_locked(command_id)
            except asyncio.CancelledError:
                await self._close_client_locked()
                raise
            except Exception as exc:
                self._connected = False
                raise ConnectionError(f"YOKONEX command {command_id!r} failed: {exc}") from exc
            return True

    async def stop(self) -> None:
        """Send the vendor global-stop event and close the bridge connection."""
        await self._stop_and_close()

    async def collect_feedback(self) -> list[DeviceFeedback]:
        return [
            DeviceFeedback(
                device_id=self.instance_id,
                kind=FeedbackKind.CONNECTION,
                channel=self.channel,
                value=1.0 if self._connected else 0.0,
                unit="bool",
                message="IM bridge ready" if self._connected else "IM bridge disconnected",
            )
        ]

    def _command_for(self, value: float) -> str:
        if value == 0.0:
            return self.stop_command_id
        for level in self.levels:
            if value <= level.max_value:
                return level.command_id
        raise AssertionError("validated levels did not cover target")

    async def _get_client_locked(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    async def _send_command_locked(self, command_id: str) -> None:
        client = await self._get_client_locked()
        response = await client.post(
            f"{self.bridge_url}/api/send-command",
            json={"commandId": command_id},
        )
        response.raise_for_status()
        data = response.json()
        if data.get("success") is not True:
            raise ConnectionError(str(data.get("message") or "API-bridge rejected the command"))

    async def _stop_and_close(self) -> None:
        async with self._lock:
            try:
                if self._connected:
                    await self._send_command_locked(self.stop_command_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    "%s could not confirm YOKONEX global stop", self.instance_id
                )
            finally:
                await self._close_client_locked()

    async def _close_client_locked(self) -> None:
        client, self._client = self._client, None
        self._connected = False
        if client is not None:
            try:
                await client.aclose()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.debug("YOKONEX HTTP client close failed", exc_info=True)

    def _ensure_connected(self) -> None:
        if not self._connected or self._client is None:
            raise ConnectionError("YOKONEX API-bridge is not connected and IM-ready")
