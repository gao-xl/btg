"""Known-vector tests for the non-actuating YOKONEX BLE encoders."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend" / "src"))

from btg.hal.actuators.yokonex_packets import (  # noqa: E402
    estim_v1_fixed,
    estim_v2_fixed,
    estim_v2_realtime,
    toy_rate,
    toy_stop,
)


def test_public_cross_checked_packet_vectors() -> None:
    assert estim_v1_fixed("AB", 180, 1).hex().upper() == "3511030100B4010000FF"
    assert (
        estim_v2_realtime(180, 1, 0, 180, 2, 0).hex().upper()
        == "35110200B4010000B40200B3"
    )
    assert toy_rate(5, 16, 20).hex().upper() == "351205101470"


def test_stop_frames_are_explicit_zero_output() -> None:
    assert estim_v1_fixed("AB", 0, 1).hex().upper() == "3511030000000100004A"
    assert estim_v2_fixed(0, 1, 0, 1).hex().upper() == "35110100000100000149"
    assert toy_stop().hex().upper() == "351200000047"


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: estim_v1_fixed("AB", 181, 1), "intensity"),
        (lambda: estim_v2_fixed(0, 0, 0, 1), "mode_a"),
        (lambda: estim_v2_realtime(1, 0, 0, 1, 1, 0), "frequency_a"),
        (lambda: toy_rate(21, 0, 0), "motor_a"),
    ],
)
def test_out_of_range_values_are_rejected_instead_of_clamped(call, message) -> None:
    with pytest.raises(ValueError, match=message):
        call()


def test_boolean_is_not_accepted_as_an_integer_level() -> None:
    with pytest.raises(TypeError, match="motor_a"):
        toy_rate(True, 0, 0)
