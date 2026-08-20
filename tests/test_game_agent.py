"""Unit tests for the standalone Game Agent parser and event mapping."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from btg.agents.game_agent.events import EventMapper, parse_event_line


def test_parse_and_map_damage() -> None:
    event = parse_event_line("[2026-08-19 12:00:00] EVENT: player_damage | value: 45\n")
    assert event is not None
    assert EventMapper().map(event) == {"channel": "A", "intensity": 45, "duration_ms": 300}


def test_map_death() -> None:
    event = parse_event_line("[2026-08-19 12:00:00] EVENT: player_death")
    assert event is not None
    assert EventMapper().map(event) == {"mode": "surge", "intensity": 80, "duration_ms": 1500}


def test_malformed_or_unsafe_damage_is_ignored() -> None:
    assert parse_event_line("not an event") is None
    event = parse_event_line("[2026-08-19 12:00:00] EVENT: player_damage | value: nan")
    assert event is not None
    assert EventMapper().map(event) is None
