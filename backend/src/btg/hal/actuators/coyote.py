"""DG-LAB Coyote (Pulse Host 2.0) actuator via BLE.

Connects to the device over BLE using ``bleak`` and mirrors the official V2
protocol: intensity is written to ``PWM_AB2`` (persists until changed), while the
waveform (X, Y, Z) is only effective for 0.1s and therefore re-written at 10Hz
while connected.  BTG's safety layer remains the only authority that decides
whether a target is allowed; this class only accepts normalized 0..100 values.

Hardware acceptance gate: the byte layout follows the official bit numbering,
but this driver has not been validated against physical hardware.  Keep
intensity conservative and verify before live use.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any, Literal, Optional

from btg_sdk import BaseActuator, DeviceFeedback, FeedbackKind, register_actuator
from pydantic import BaseModel, ConfigDict, Field

from .coyote_packets import (
    BATTERY_CHAR_UUID,
    DEVICE_NAME,
    PWM_AB2_UUID,
    PWM_A34_UUID,
    PWM_B34_UUID,
    intensity_from_percent,
    pack_intensity,
    pack_waveform,
)

try:  # Keep module discovery possible when the optional BLE dependency is absent.
    from bleak import BleakClient, BleakScanner
except ImportError as exc:  # pragma: no cover - depends on deployment extras.
    BleakClient = BleakScanner = None  # type: ignore[assignment,misc]
    _BLEAK_IMPORT_ERROR: Optional[ImportError] = exc
else:
    _BLEAK_IMPORT_ERROR = None

LOGGER = logging.getLogger(__name__)

# Official naming is inverted: PWM_B34 carries the A channel waveform.
_WAVEFORM_CHAR_FOR_CHANNEL = {"A": PWM_B34_UUID, "B": PWM_A34_UUID}


class CoyoteConfig(BaseModel):
    """Strict configuration boundary for the Coyote BLE plugin."""

    model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(default="coyote", min_length=1)
    address: Optional[str] = Field(default=None, min_length=1)
    name: str = Field(default=DEVICE_NAME, min_length=1)
    channel: Literal["A", "B"] = "A"
    x: int = Field(default=1, ge=0, le=31)
    y: int = Field(default=9, ge=0, le=1023)
    z: int = Field(default=20, ge=0, le=31)
    scan_timeout: float = Field(default=5.0, gt=0.0, le=60.0)
    connect_timeout: float = Field(default=10.0, gt=0.0, le=60.0)
    wave_interval: float = Field(default=0.1, gt=0.0, le=1.0)


@register_actuator("coyote")
class CoyoteActuator(BaseActuator):
    """Drive one Coyote electrical channel with normalized 0..100 targets.

    Configuration keys:
    - ``address``: BLE MAC address; when omitted, discovery matches ``name``.
    - ``channel``: physical channel to drive (``A`` or ``B``).
    - ``x``/``y``/``z``: waveform parameters (default ``1, 9, 20`` = 100Hz, 100us).
    """

    def __init__(self, config: Mapping[str, Any]) -> None:
        validated = CoyoteConfig.model_validate(dict(config))
        self.instance_id = validated.instance_id
        self.address = validated.address
        self.name = validated.name
        self.channel = validated.channel
        self.x = validated.x
        self.y = validated.y
        self.z = validated.z
        self.scan_timeout = validated.scan_timeout
        self.connect_timeout = validated.connect_timeout
        self.wave_interval = validated.wave_interval

        self._client: Any | None = None
        self._connected = False
        self._streaming = False
        self._stream_task: Optional[asyncio.Task] = None
        self._intensity_a = 0
        self._intensity_b = 0
        self._battery: Optional[int] = None
        self._write_lock = asyncio.Lock()

    async def connect(self) -> bool:
        """Connect BLE, subscribe battery notifications, and start the 10Hz loop."""
        self._require_bleak()
        async with self._write_lock:
            if self._connected:
                return True
            try:
                address = self.address
                if address is None:
                    address = await self._discover_address()
                client = BleakClient(address, timeout=self.connect_timeout)
                await client.connect()
                self._client = client
                self._connected = True
                await self._start_battery_notify(client)
                self._streaming = True
                self._stream_task = asyncio.create_task(self._waveform_loop())
                LOGGER.info("Coyote %s connected at %s", self.instance_id, address)
                return True
            except asyncio.CancelledError:
                await self._teardown_client_locked()
                raise
            except Exception as exc:
                await self._teardown_client_locked()
                raise ConnectionError(f"Coyote BLE connect failed: {exc}") from exc

    async def disconnect(self) -> None:
        """Fail closed: zero intensity, stop the loop, and release the BLE link."""
        async with self._write_lock:
            await self._zero_and_disconnect_locked()

    async def set_target(self, channel: str, value: float) -> bool:
        """Write a normalized 0..100 target to the configured physical channel."""
        intensity = intensity_from_percent(value)
        async with self._write_lock:
            self._ensure_connected()
            if self.channel == "A":
                self._intensity_a = intensity
            else:
                self._intensity_b = intensity
            await self._write_intensity_locked()
        return True

    async def stop(self) -> None:
        """Immediately zero output and disconnect (watchdog / fail-safe path)."""
        await self.disconnect()

    async def collect_feedback(self) -> list[DeviceFeedback]:
        """Report connection state and battery level (when advertised)."""
        items = [
            DeviceFeedback(
                device_id=self.instance_id,
                kind=FeedbackKind.CONNECTION,
                value=1.0 if self._connected else 0.0,
                unit="bool",
                message="connected" if self._connected else "disconnected",
            )
        ]
        if self._battery is not None:
            items.append(
                DeviceFeedback(
                    device_id=self.instance_id,
                    kind=FeedbackKind.BATTERY,
                    value=float(self._battery),
                    unit="ratio",
                )
            )
        return items

    # ------------------------------------------------------------------ #
    # BLE helpers
    # ------------------------------------------------------------------ #
    async def _discover_address(self) -> str:
        devices = await BleakScanner.discover(timeout=self.scan_timeout)
        for device in devices:
            if device.name and device.name.strip() == self.name:
                return device.address
        raise ConnectionError(f"No Coyote device named {self.name!r} found")

    async def _start_battery_notify(self, client: Any) -> None:
        try:
            await client.start_notify(BATTERY_CHAR_UUID, self._on_battery)
        except Exception:  # noqa: BLE001 - battery is advisory, not required.
            LOGGER.debug("Coyote %s battery notify unavailable", self.instance_id)

    def _on_battery(self, _sender: Any, data: bytearray) -> None:
        if data:
            self._battery = data[0]

    async def _write_intensity_locked(self) -> None:
        if self._client is None or not self._connected:
            return
        await self._client.write_gatt_char(
            PWM_AB2_UUID, pack_intensity(self._intensity_a, self._intensity_b)
        )

    async def _waveform_loop(self) -> None:
        char = _WAVEFORM_CHAR_FOR_CHANNEL[self.channel]
        try:
            while self._streaming:
                if self._client is not None and self._connected:
                    try:
                        await self._client.write_gatt_char(
                            char, pack_waveform(self.x, self.y, self.z)
                        )
                    except Exception:  # noqa: BLE001 - a lost link must fail over.
                        LOGGER.exception("Coyote %s waveform write failed", self.instance_id)
                        self._connected = False
                        break
                await asyncio.sleep(self.wave_interval)
        except asyncio.CancelledError:
            raise
        finally:
            self._streaming = False

    async def _zero_and_disconnect_locked(self) -> None:
        self._streaming = False
        self._stop_stream_task()
        self._intensity_a = 0
        self._intensity_b = 0
        try:
            if self._client is not None and self._client.is_connected:
                await self._client.write_gatt_char(PWM_AB2_UUID, pack_intensity(0, 0))
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Coyote %s could not confirm zero intensity", self.instance_id)
        await self._teardown_client_locked()

    def _stop_stream_task(self) -> None:
        if self._stream_task is not None:
            self._stream_task.cancel()
            self._stream_task = None

    async def _teardown_client_locked(self) -> None:
        client, self._client = self._client, None
        self._connected = False
        self._streaming = False
        if client is not None:
            try:
                await client.disconnect()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.debug("Coyote %s BLE disconnect failed", self.instance_id, exc_info=True)

    def _ensure_connected(self) -> None:
        if not self._connected or self._client is None:
            raise ConnectionError("Coyote BLE link is not connected")

    @staticmethod
    def _require_bleak() -> None:
        if _BLEAK_IMPORT_ERROR is not None:
            raise RuntimeError(
                "bleak is required for coyote; install it with `pip install \"btg-backend[coyote]\"`"
            ) from _BLEAK_IMPORT_ERROR