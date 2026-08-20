"""Coyote V2 包编码的确定性单元测试（无硬件依赖）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "sdk", _ROOT / "backend" / "src"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from btg.hal.actuators.coyote_packets import (  # noqa: E402
    BATTERY_CHAR_UUID,
    PWM_AB2_UUID,
    full_uuid,
    intensity_from_percent,
    pack_intensity,
    pack_waveform,
    waveform_from_frequency_hz,
)


def test_full_uuid_is_stable():
    assert full_uuid(0x1504) == "955A1504-0FE2-F5AA-A094-84B8D4F3E8AD"
    assert PWM_AB2_UUID == full_uuid(0x1504)
    assert BATTERY_CHAR_UUID == full_uuid(0x1500)


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (0, 0, b"\x00\x00\x00"),
        (2047, 0, b"\x3f\xf8\x00"),
        (0, 2047, b"\x00\x07\xff"),
        (1, 1, b"\x00\x08\x01"),
        (2047, 2047, b"\x3f\xff\xff"),
    ],
)
def test_pack_intensity(a, b, expected):
    assert pack_intensity(a, b) == expected


@pytest.mark.parametrize(
    "x,y,z,expected",
    [
        (0, 0, 0, b"\x00\x00\x00"),
        (1, 9, 20, b"\x0a\x01\x21"),
        (31, 1023, 31, b"\x0f\xff\xff"),
    ],
)
def test_pack_waveform(x, y, z, expected):
    assert pack_waveform(x, y, z) == expected


def test_pack_intensity_rejects_out_of_range():
    with pytest.raises(ValueError):
        pack_intensity(2048, 0)
    with pytest.raises(ValueError):
        pack_intensity(0, -1)


def test_pack_waveform_rejects_out_of_range():
    with pytest.raises(ValueError):
        pack_waveform(32, 0, 0)
    with pytest.raises(ValueError):
        pack_waveform(0, 1024, 0)
    with pytest.raises(ValueError):
        pack_waveform(0, 0, 32)


def test_intensity_from_percent_pins_ends():
    assert intensity_from_percent(0.0) == 0
    assert intensity_from_percent(100.0) == 2047


def test_intensity_from_percent_rejects_out_of_range():
    with pytest.raises(ValueError):
        intensity_from_percent(-0.1)
    with pytest.raises(ValueError):
        intensity_from_percent(100.1)


def test_waveform_from_frequency_hz_maps_100hz():
    x, y = waveform_from_frequency_hz(100.0)
    assert x + y == 10  # period of 10ms -> 100Hz
    assert 0 <= x <= 31 and 0 <= y <= 1023