"""Parsing and mapping of the small, documented game-log format."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from .mapper import EventMapper


_EVENT_RE = re.compile(
    r"^\[(?P<timestamp>[^\]]+)\]\s*EVENT:\s*"
    r"(?P<name>[A-Za-z0-9_.-]+)(?P<fields>.*)$"
)


@dataclass(frozen=True)
class GameEvent:
    """A valid event extracted from one game log line."""

    timestamp: datetime
    name: str
    fields: dict[str, Any]


def _coerce_value(value: str) -> Any:
    value = value.strip()
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def parse_event_line(line: str) -> GameEvent | None:
    """Parse ``[timestamp] EVENT: name | key: value`` or return ``None``.

    Malformed and non-event lines are deliberately ignored so a noisy game log
    cannot terminate the long-running agent.
    """
    match = _EVENT_RE.match(line.strip())
    if not match:
        return None
    try:
        timestamp = datetime.fromisoformat(match.group("timestamp"))
    except ValueError:
        return None

    fields: dict[str, Any] = {}
    for chunk in match.group("fields").split("|"):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, separator, value = chunk.partition(":")
        if not separator or not key.strip():
            return None
        fields[key.strip().lower()] = _coerce_value(value)
    return GameEvent(timestamp=timestamp, name=match.group("name").lower(), fields=fields)
