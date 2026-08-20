"""Buttplug.io / Intiface Central bridge for BTG actuator channels.

This plugin deliberately does not implement any vendor protocol.  Intiface owns
device discovery and protocol translation; BTG's safety layer remains the only
authority that decides whether a command is allowed and clamps its value.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping
from typing import Any

from btg_sdk import BaseActuator, DeviceFeedback, FeedbackKind, register_actuator
from pydantic import AnyUrl, BaseModel, ConfigDict, Field

try:  # Keep plugin discovery possible when an optional hardware dependency is absent.
    from buttplug import ButtplugClient, DeviceOutputCommand, InputType, OutputType
except ImportError as exc:  # pragma: no cover - depends on deployment extras.
    ButtplugClient = DeviceOutputCommand = InputType = OutputType = None  # type: ignore[assignment,misc]
    _BUTTPLUG_IMPORT_ERROR: ImportError | None = exc
else:
    _BUTTPLUG_IMPORT_ERROR = None


LOGGER = logging.getLogger(__name__)


class ButtplugBridgeConfig(BaseModel):
    """Strict configuration boundary for the optional Intiface bridge plugin."""

    model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(default="buttplug_proxy", min_length=1)
    server_url: AnyUrl = "ws://127.0.0.1:12345"
    scan_duration_seconds: float = Field(default=5.0, ge=0.0, le=60.0)
    channel_output_types: dict[str, list[str]] = Field(default_factory=dict)


@register_actuator("buttplug_proxy")
class ButtplugBridge(BaseActuator):
    """Maps BTG's 0--100 actuator values onto Intiface output commands.

    Configuration keys:
    - ``server_url``: Intiface WebSocket URL (default ``ws://127.0.0.1:12345``).
    - ``scan_duration_seconds``: bounded discovery wait after connection
      (default ``5``).
    - ``channel_output_types``: optional mapping from BTG channel name to a
      list of Buttplug output enum names, e.g. ``{"vibration": ["VIBRATE"]}``.
      Unmapped channels use ``VIBRATE``.  Names not available in the installed
      buttplug library are ignored and logged rather than guessed.

    Intiface must be configured with the required device permissions.  This
    class only accepts values already approved by BTG's safety policy.
    """

    def __init__(self, config: Mapping[str, Any]) -> None:
        validated = ButtplugBridgeConfig.model_validate(dict(config))
        self.instance_id = validated.instance_id
        self.server_url = str(validated.server_url)
        self.scan_duration_seconds = validated.scan_duration_seconds
        raw_mapping = validated.channel_output_types
        self._channel_output_types = {
            str(channel): self._validate_output_names(channel, names)
            for channel, names in raw_mapping.items()
        }
        self._client: Any | None = None
        self._connected = False
        self._server_disconnect_reason: str | None = None
        self._command_lock = asyncio.Lock()

    async def connect(self) -> bool:
        """Connect, scan Intiface for a bounded period, and log discoveries.

        A lost server connection is recorded by ``on_server_disconnect``.  The
        next operation raises ``ConnectionError`` so BTG's redundancy router can
        fail over instead of treating a stale plugin as healthy.
        """
        self._require_buttplug()
        async with self._command_lock:
            if self._connected:
                return True
            client = ButtplugClient(f"BTG Buttplug Bridge ({self.instance_id})")
            client.on_device_added = self._on_device_added
            client.on_device_removed = self._on_device_removed
            client.on_scanning_finished = self._on_scanning_finished
            client.on_server_disconnect = self._on_server_disconnect
            try:
                LOGGER.info("Connecting %s to Intiface at %s", self.instance_id, self.server_url)
                await client.connect(self.server_url)
                self._client = client
                self._connected = True
                self._server_disconnect_reason = None
                await client.start_scanning()
                await asyncio.sleep(self.scan_duration_seconds)
                await client.stop_scanning()
                self._log_devices()
                return True
            except asyncio.CancelledError:
                await self._disconnect_client(client)
                self._client = None
                self._connected = False
                raise
            except Exception as exc:
                await self._disconnect_client(client)
                self._client = None
                self._connected = False
                LOGGER.exception("%s could not connect or scan Intiface", self.instance_id)
                raise ConnectionError(f"Intiface connection/scan failed: {exc}") from exc

    async def disconnect(self) -> None:
        """Zero outputs then release the Intiface connection (idempotent)."""
        async with self._command_lock:
            await self._zero_all_locked()
            await self._disconnect_current_locked()

    async def set_target(self, channel: str, value: float) -> bool:
        """Send a safety-approved BTG 0--100 value to compatible devices."""
        if not 0.0 <= value <= 100.0:
            raise ValueError("Buttplug bridge accepts normalized values in [0, 100]")
        async with self._command_lock:
            self._ensure_connected()
            dispatched = await self._send_to_matching_devices(channel, value / 100.0)
            if not dispatched:
                LOGGER.warning("%s found no device with output support for channel %s", self.instance_id, channel)
            return dispatched

    async def stop(self) -> None:
        """Immediately set discovered outputs to zero, then disconnect.

        Every device also receives its protocol-level ``stop()`` command.  The
        latter covers output types that were not configured in the channel map.
        Failures are logged per device so one bad device never prevents the
        remaining devices from being zeroed.
        """
        async with self._command_lock:
            await self._zero_all_locked()
            await self._disconnect_current_locked()

    async def collect_feedback(self) -> list:
        """Collect battery/connection feedback for every connected device.

        Reports each Intiface device as ``CONNECTION=connected`` plus its
        battery level when the device advertises battery input capability.
        Returns an empty list when disconnected.
        """
        if not self._connected or self._client is None:
            return []
        items: list[DeviceFeedback] = []
        for device in self._devices():
            device_id = f"{self.instance_id}:{getattr(device, 'name', '<unknown>')}"
            items.append(
                DeviceFeedback(
                    device_id=device_id,
                    kind=FeedbackKind.CONNECTION,
                    value=1.0,
                    unit="bool",
                    message="connected",
                )
            )
            if self._has_input(device, "BATTERY"):
                try:
                    battery = await device.battery()
                    items.append(
                        DeviceFeedback(
                            device_id=device_id,
                            kind=FeedbackKind.BATTERY,
                            value=battery,
                            unit="ratio",
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    LOGGER.debug("Failed to read battery for %s: %s", device_id, exc)
        return items

    @staticmethod
    def _has_input(device: Any, name: str) -> bool:
        if InputType is None:
            return False
        enum_value = getattr(InputType, name, None)
        if enum_value is None:
            return False
        return bool(device.has_input(enum_value))

    async def _send_to_matching_devices(self, channel: str, normalized_value: float) -> bool:
        output_types = self._output_types_for(channel)
        if not output_types:
            return False
        dispatched = False
        for device in self._devices():
            for output_type in output_types:
                if device.has_output(output_type):
                    await device.run_output(DeviceOutputCommand(output_type, normalized_value))
                    LOGGER.debug(
                        "%s sent %.3f to device %s via %s",
                        self.instance_id,
                        normalized_value,
                        getattr(device, "name", "<unknown>"),
                        getattr(output_type, "name", output_type),
                    )
                    dispatched = True
        return dispatched

    async def _zero_all_locked(self) -> None:
        if self._client is None:
            return
        output_types = self._all_configured_output_types()
        for device in self._devices():
            device_name = getattr(device, "name", "<unknown>")
            for output_type in output_types:
                try:
                    if device.has_output(output_type):
                        await device.run_output(DeviceOutputCommand(output_type, 0.0))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception("Failed to zero %s output %s", device_name, output_type)
            try:
                await device.stop()
                LOGGER.info("Stopped Buttplug device %s", device_name)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Protocol stop failed for Buttplug device %s", device_name)

    async def _disconnect_current_locked(self) -> None:
        client, self._client = self._client, None
        self._connected = False
        self._server_disconnect_reason = None
        if client is not None:
            await self._disconnect_client(client)

    @staticmethod
    async def _disconnect_client(client: Any) -> None:
        try:
            await client.disconnect()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.debug("Intiface disconnect completed with an error", exc_info=True)

    def _ensure_connected(self) -> None:
        if not self._connected or self._client is None:
            reason = self._server_disconnect_reason or "not connected"
            raise ConnectionError(f"Intiface server unavailable: {reason}")

    def _devices(self) -> list[Any]:
        return list(self._client.devices.values()) if self._client is not None else []

    def _output_types_for(self, channel: str) -> tuple[Any, ...]:
        names = self._channel_output_types.get(channel, ("VIBRATE",))
        return tuple(output_type for name in names if (output_type := getattr(OutputType, name, None)) is not None)

    def _all_configured_output_types(self) -> tuple[Any, ...]:
        names = {"VIBRATE"}
        for configured_names in self._channel_output_types.values():
            names.update(configured_names)
        return tuple(output_type for name in names if (output_type := getattr(OutputType, name, None)) is not None)

    @staticmethod
    def _validate_output_names(channel: Any, names: Any) -> tuple[str, ...]:
        if not isinstance(names, Iterable) or isinstance(names, (str, bytes)):
            raise ValueError(f"channel_output_types[{channel!r}] must be a list of enum names")
        result = tuple(str(name).upper() for name in names)
        if not result:
            raise ValueError(f"channel_output_types[{channel!r}] cannot be empty")
        return result

    def _log_devices(self) -> None:
        devices = self._devices()
        if devices:
            LOGGER.info("%s discovered %d Intiface device(s): %s", self.instance_id, len(devices), ", ".join(str(getattr(device, "name", "<unknown>")) for device in devices))
        else:
            LOGGER.warning("%s scan completed without Intiface devices", self.instance_id)

    def _on_device_added(self, device: Any) -> None:
        LOGGER.info("%s discovered Intiface device: %s", self.instance_id, getattr(device, "name", "<unknown>"))

    def _on_device_removed(self, device: Any) -> None:
        LOGGER.warning("%s lost Intiface device: %s", self.instance_id, getattr(device, "name", "<unknown>"))

    def _on_scanning_finished(self) -> None:
        LOGGER.info("%s Intiface scan finished", self.instance_id)

    def _on_server_disconnect(self, *_: Any) -> None:
        self._connected = False
        self._server_disconnect_reason = "server disconnected"
        LOGGER.error("%s lost its Intiface server connection; redundancy failover is required", self.instance_id)

    @staticmethod
    def _require_buttplug() -> None:
        if _BUTTPLUG_IMPORT_ERROR is not None:
            raise RuntimeError("buttplug is required for buttplug_proxy; install it with `pip install buttplug`") from _BUTTPLUG_IMPORT_ERROR
