"""分级安全闸（Guardrail）冒烟测试：软降级限幅、硬急停归零、黑盒因果链。

独立运行：``python tests/test_guardrail.py``
pytest 运行：``pytest tests/``
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "sdk"))
sys.path.insert(0, str(_ROOT / "backend" / "src"))

from btg.core import AuditBlackbox  # noqa: E402
from btg.safety import (  # noqa: E402
    ClampSet,
    Guardrail,
    GuardrailConfig,
    SafetyPolicy,
    Watchdog,
)
from btg_sdk import ActuatorCommand, Reading  # noqa: E402


def _reading(channel: str, value: float) -> Reading:
    return Reading(
        channel=channel,
        sensor_id=f"{channel}:mock:0",
        value=value,
        unit="bpm" if channel == "heart_rate" else "g",
        timestamp=0.0,
    )


def _command(value: float) -> ActuatorCommand:
    return ActuatorCommand(
        channel="tens_intensity",
        actuator_id="tens:mock:0",
        value=value,
        unit="mA",
        timestamp=0.0,
    )


async def _noop(reason: str = "") -> None:
    return None


def _guardrail(on_hard_stop=None, blackbox=None):
    return Guardrail(
        GuardrailConfig(),
        on_hard_stop=on_hard_stop or _noop,
        blackbox=blackbox,
    )


def test_over_warn_degrades_and_attenuates() -> None:
    guardrail = _guardrail()
    guardrail.ingest_reading(_reading("heart_rate", 135.0))
    assert guardrail.degraded is True
    assert guardrail.apply(40.0) == 20.0
    assert guardrail.hard_triggered is False


def test_drops_below_reset_restores() -> None:
    guardrail = _guardrail()
    guardrail.ingest_reading(_reading("heart_rate", 140.0))
    assert guardrail.degraded is True
    guardrail.ingest_reading(_reading("heart_rate", 100.0))
    assert guardrail.degraded is False
    assert guardrail.apply(40.0) == 40.0


def test_consecutive_critical_hard_stops() -> None:
    hits: list[str] = []

    async def _stop(reason: str) -> None:
        hits.append(reason)

    guardrail = _guardrail(on_hard_stop=_stop)
    for _ in range(3):
        guardrail.ingest_reading(_reading("heart_rate", 165.0))
    assert guardrail.hard_triggered is True
    assert "心率连续超限" in guardrail.hard_reason
    # 硬急停锁存后：即使后续心率正常，也不再解除，且强度归零
    guardrail.ingest_reading(_reading("heart_rate", 90.0))
    assert guardrail.hard_triggered is True
    assert guardrail.apply(40.0) == 0.0


def test_imu_fall_hard_stops() -> None:
    hits: list[str] = []

    async def _stop(reason: str) -> None:
        hits.append(reason)

    guardrail = _guardrail(on_hard_stop=_stop)
    guardrail.ingest_reading(_reading("imu_variance", 4.5))
    assert guardrail.hard_triggered is True
    assert "IMU" in guardrail.hard_reason


def test_reset_clears_latch() -> None:
    guardrail = _guardrail()
    for _ in range(3):
        guardrail.ingest_reading(_reading("heart_rate", 170.0))
    assert guardrail.hard_triggered is True
    guardrail.reset()
    assert guardrail.hard_triggered is False
    assert guardrail.degraded is False
    assert guardrail.apply(40.0) == 40.0


def test_policy_applies_attenuation() -> None:
    guardrail = _guardrail()
    guardrail.degrade("AI 激进输出", source="ai")
    policy = SafetyPolicy(
        ClampSet([]),
        Watchdog(timeout=30.0, on_timeout=_noop),
        guardrail=guardrail,
    )

    async def _run() -> ActuatorCommand:
        return await policy.check_command(_command(40.0))

    safe = asyncio.run(_run())
    assert safe.value == 20.0


def test_blackbox_records_causal_chain() -> None:
    blackbox = AuditBlackbox()
    guardrail = _guardrail(blackbox=blackbox)
    guardrail.ingest_reading(_reading("heart_rate", 145.0))
    guardrail.degrade("AI 激进输出", source="ai")
    for _ in range(3):
        guardrail.ingest_reading(_reading("heart_rate", 170.0))
    # 至少 2 帧：软降级 + 硬急停，且构成因果链
    assert len(blackbox) >= 2
    frames = blackbox.snapshot()
    events = [f["event"] for f in frames]
    assert "soft_degrade" in events
    assert "hard_interlock" in events


def test_heartbeat_timeout_schedules_hard_stop() -> None:
    hits: list[str] = []

    async def _stop(reason: str) -> None:
        hits.append(reason)

    async def _run() -> None:
        guardrail = Guardrail(
            GuardrailConfig(ws_heartbeat_timeout=0.02, poll_interval=0.01),
            on_hard_stop=_stop,
        )
        await guardrail.start()
        guardrail.feed_heartbeat()
        await asyncio.sleep(0.06)
        await guardrail.stop()
        assert guardrail.hard_triggered is True
        assert "心跳超时" in guardrail.hard_reason
        assert hits

    asyncio.run(_run())


if __name__ == "__main__":
    test_over_warn_degrades_and_attenuates()
    test_drops_below_reset_restores()
    test_consecutive_critical_hard_stops()
    test_imu_fall_hard_stops()
    test_reset_clears_latch()
    test_policy_applies_attenuation()
    test_blackbox_records_causal_chain()
    test_heartbeat_timeout_schedules_hard_stop()
    print("guardrail smoke ok")