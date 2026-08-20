"""Tests for hot gain tuning and event cooldown behavior."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from btg.agents.game_agent.events import GameEvent
from btg.agents.game_agent.mapper import EventMapper, GameRules


def test_global_gain_changes_damage_intensity_without_reloading_rules() -> None:
    mapper = EventMapper(
        GameRules.from_mapping(
            {
                "global_gain": 1.0,
                "events": {
                    "player_damage": {
                        "base_intensity": 0,
                        "gain": 1.5,
                        "cooldown_ms": 0,
                        "duration_ms": 300,
                    }
                },
            }
        )
    )
    event = GameEvent(datetime.now(), "player_damage", {"damage_amount": 30})

    assert mapper.map(event, now_ms=0) == {"channel": "A", "intensity": 45, "duration_ms": 300}
    mapper.apply_gateway_update({"global_gain": 2.0})
    assert mapper.map(event, now_ms=1) == {"channel": "A", "intensity": 90, "duration_ms": 300}


def test_cooldown_drops_repeat_event() -> None:
    mapper = EventMapper(
        GameRules.from_mapping(
            {"events": {"player_damage": {"base_intensity": 0, "gain": 1, "cooldown_ms": 100, "duration_ms": 1}}}
        )
    )
    event = GameEvent(datetime.now(), "player_damage", {"damage_amount": 10})
    assert mapper.map(event, now_ms=0) is not None
    assert mapper.map(event, now_ms=99) is None
    assert mapper.map(event, now_ms=100) is not None
