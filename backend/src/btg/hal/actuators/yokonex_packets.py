"""Pure YOKONEX BLE packet encoders.

These helpers perform no scanning or device I/O.  They intentionally cover
only packet layouts that agree with the vendor documents and multiple public
implementations.  Hardware output remains behind a separate, unimplemented
acceptance gate.
"""
from __future__ import annotations

from typing import Literal


def checksum(payload: bytes | bytearray) -> int:
    """Return the protocol's unsigned 8-bit additive checksum."""
    return sum(payload) & 0xFF


def _bounded(name: str, value: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
    return value


def _with_checksum(payload: list[int]) -> bytes:
    frame = bytearray(payload)
    frame.append(checksum(frame))
    return bytes(frame)


def estim_v1_fixed(
    channel: Literal["A", "B", "AB"],
    intensity: int,
    mode: int,
) -> bytes:
    """Build a first-generation fixed-mode channel frame.

    ``intensity`` is limited to the conservative 0--180 range used by the
    independently tested SLK implementation, below the protocol's wider raw
    field capacity.  Zero intensity encodes an explicit closed channel.
    """
    channel_codes = {"A": 0x01, "B": 0x02, "AB": 0x03}
    if channel not in channel_codes:
        raise ValueError("channel must be A, B, or AB")
    intensity = _bounded("intensity", intensity, 0, 180)
    mode = _bounded("mode", mode, 1, 16)
    return _with_checksum([
        0x35,
        0x11,
        channel_codes[channel],
        0x01 if intensity else 0x00,
        intensity >> 8,
        intensity & 0xFF,
        mode,
        0x00,
        0x00,
    ])


def estim_v2_fixed(
    intensity_a: int,
    mode_a: int,
    intensity_b: int,
    mode_b: int,
) -> bytes:
    """Build a second-generation dual-channel fixed-mode frame."""
    intensity_a = _bounded("intensity_a", intensity_a, 0, 180)
    intensity_b = _bounded("intensity_b", intensity_b, 0, 180)
    mode_a = _bounded("mode_a", mode_a, 1, 16)
    mode_b = _bounded("mode_b", mode_b, 1, 16)
    return _with_checksum([
        0x35,
        0x11,
        0x01,
        intensity_a >> 8,
        intensity_a & 0xFF,
        mode_a,
        intensity_b >> 8,
        intensity_b & 0xFF,
        mode_b,
    ])


def estim_v2_realtime(
    intensity_a: int,
    frequency_a: int,
    pulse_width_a: int,
    intensity_b: int,
    frequency_b: int,
    pulse_width_b: int,
) -> bytes:
    """Build a second-generation dual-channel real-time frame."""
    intensity_a = _bounded("intensity_a", intensity_a, 0, 180)
    intensity_b = _bounded("intensity_b", intensity_b, 0, 180)
    frequency_a = _bounded("frequency_a", frequency_a, 1, 100)
    frequency_b = _bounded("frequency_b", frequency_b, 1, 100)
    pulse_width_a = _bounded("pulse_width_a", pulse_width_a, 0, 100)
    pulse_width_b = _bounded("pulse_width_b", pulse_width_b, 0, 100)
    return _with_checksum([
        0x35,
        0x11,
        0x02,
        intensity_a >> 8,
        intensity_a & 0xFF,
        frequency_a,
        pulse_width_a,
        intensity_b >> 8,
        intensity_b & 0xFF,
        frequency_b,
        pulse_width_b,
    ])


def toy_rate(motor_a: int, motor_b: int, motor_c: int) -> bytes:
    """Build a cup/egg three-motor rate frame using the common safe subset."""
    motor_a = _bounded("motor_a", motor_a, 0, 20)
    motor_b = _bounded("motor_b", motor_b, 0, 20)
    motor_c = _bounded("motor_c", motor_c, 0, 20)
    return _with_checksum([0x35, 0x12, motor_a, motor_b, motor_c])


def toy_stop() -> bytes:
    """Build the explicit all-motors-zero cup/egg frame."""
    return toy_rate(0, 0, 0)
