"""core 模块冒烟测试：事件总线订阅/发布、遥测环形缓冲。

独立运行：``python tests/test_core.py``
pytest 运行：``pytest tests/``
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "sdk"))
sys.path.insert(0, str(_ROOT / "backend" / "src"))

from btg.core import EventBus, TelemetryRingBuffer  # noqa: E402
from btg_sdk import Reading  # noqa: E402


def test_telemetry_ring_buffer() -> None:
    buf = TelemetryRingBuffer(capacity=2)

    r1 = Reading(channel="heart_rate", sensor_id="s1", value=80.0, unit="bpm", timestamp=1.0)
    r2 = Reading(channel="heart_rate", sensor_id="s1", value=90.0, unit="bpm", timestamp=2.0)
    r3 = Reading(channel="heart_rate", sensor_id="s1", value=100.0, unit="bpm", timestamp=3.0)

    buf.push(r1)
    buf.push(r2)
    buf.push(r3)

    assert buf.latest("heart_rate") is r3
    # capacity=2 时最旧样本被覆盖
    assert buf.history("heart_rate") == [r2, r3]
    assert buf.total_pushed == 3
    assert buf.channels() == ["heart_rate"]


def test_event_bus_pubsub() -> None:
    bus = EventBus()
    received = []

    @bus.on("state_change")
    async def _on_state(state: str, confidence: float) -> None:
        received.append((state, confidence))

    asyncio.run(bus.publish("state_change", state="estop", confidence=1.0))
    assert received == [("estop", 1.0)]


if __name__ == "__main__":
    test_telemetry_ring_buffer()
    test_event_bus_pubsub()
    print("core smoke ok")