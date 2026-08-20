"""Pure DG-LAB Coyote (Pulse Host 2.0) BLE packet encoders.

Encoders mirror the official DG-LAB opensource protocol for Coyote V2.  They do
no scanning or device I/O.  Output values are byte-layout deterministic so the
bit packing can be unit-tested without hardware.

Protocol reference (non-commercial use; see upstream license):
https://github.com/DG-LAB-OpenSource/DG-LAB-Bluetooth-Protocol

Non-obvious decisions baked in here (verified in ``tests/test_coyote_packets.py``):

- The 3-byte fields are packed as **big-endian 24-bit words**, matching the
  documented bit numbering (bit 23 = MSB).  Confirm against hardware before use.
- Characteristic naming is inverted in the official table: ``PWM_A34`` carries
  the *B* channel waveform and ``PWM_B34`` carries the *A* channel waveform.
"""
from __future__ import annotations

# Replace the 16-bit short ID to form a full 128-bit UUID.
_BASE_UUID = "955A{short:04X}-0FE2-F5AA-A094-84B8D4F3E8AD"

DEVICE_NAME = "D-LAB ESTIM01"

SERVICE_BATTERY = 0x180A
CHAR_BATTERY = 0x1500
SERVICE_PWM = 0x180B
CHAR_PWM_AB2 = 0x1504  # combined A+B intensity
CHAR_PWM_A34 = 0x1505  # NOTE: carries *B* channel waveform
CHAR_PWM_B34 = 0x1506  # NOTE: carries *A* channel waveform

INTENSITY_MAX = 2047  # 11-bit intensity S
X_MAX = 31
Y_MAX = 1023
Z_MAX = 31

BATTERY_SERVICE_UUID = _BASE_UUID.format(short=SERVICE_BATTERY)
BATTERY_CHAR_UUID = _BASE_UUID.format(short=CHAR_BATTERY)
PWM_SERVICE_UUID = _BASE_UUID.format(short=SERVICE_PWM)
PWM_AB2_UUID = _BASE_UUID.format(short=CHAR_PWM_AB2)
PWM_A34_UUID = _BASE_UUID.format(short=CHAR_PWM_A34)
PWM_B34_UUID = _BASE_UUID.format(short=CHAR_PWM_B34)


def full_uuid(short_id: int) -> str:
    """Return the full 128-bit UUID for a DG-LAB 16-bit short ID."""
    return _BASE_UUID.format(short=short_id)


def _bounded(name: str, value: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
    return value


def pack_intensity(channel_a: int, channel_b: int) -> bytes:
    """Pack channel A/B intensity (0..2047) into the 3-byte ``PWM_AB2`` payload.

    Layout (24 bits, big-endian): bits 23-22 reserved, 21-11 = A, 10-0 = B.
    """
    a = _bounded("channel_a", channel_a, 0, INTENSITY_MAX)
    b = _bounded("channel_b", channel_b, 0, INTENSITY_MAX)
    return ((a << 11) | b).to_bytes(3, "big")


def pack_waveform(x: int, y: int, z: int) -> bytes:
    """Pack waveform (X, Y, Z) into the 3-byte ``PWM_A34``/``PWM_B34`` payload.

    Layout (24 bits, big-endian): bits 23-20 reserved, 19-15 = Z (pulse width),
    14-5 = Y (interval), 4-0 = X (burst length).
    """
    x = _bounded("x", x, 0, X_MAX)
    y = _bounded("y", y, 0, Y_MAX)
    z = _bounded("z", z, 0, Z_MAX)
    return ((z << 15) | (y << 5) | x).to_bytes(3, "big")


def intensity_from_percent(percent: float) -> int:
    """Map a normalized 0..100 value onto the 11-bit 0..2047 intensity range."""
    if not 0.0 <= percent <= 100.0:
        raise ValueError("percent must be in [0, 100]")
    return round(percent / 100.0 * INTENSITY_MAX)


def waveform_from_frequency_hz(frequency_hz: float) -> tuple[int, int]:
    """Derive (x, y) from a target pulse frequency using the official ratio.

    The device's ``X + Y`` is the pulse period in milliseconds, so a target
    frequency ``f`` (Hz) maps to period ``1000 / f``.  The official guidance
    keeps the best sensation at ``x = sqrt(period/1000) * 15``.
    """
    if not 1.0 <= frequency_hz <= 100.0:
        raise ValueError("frequency_hz must be in [1.0, 100.0]")
    period_ms = min(1000.0, max(10.0, 1000.0 / frequency_hz))
    x = (period_ms / 1000.0) ** 0.5 * 15.0
    y = period_ms - x
    return _bounded("x", round(x), 0, X_MAX), _bounded("y", round(y), 0, Y_MAX)