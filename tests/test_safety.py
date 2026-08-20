"""safety 层冒烟测试：数值截断、钩子拦截、看门狗超时归零。

独立运行：``python tests/test_safety.py``
pytest 运行：``pytest tests/``
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "sdk"))
sys.path.insert(0, str(_ROOT / "backend" / "src"))

from btg.core.exceptions import SafetyViolationError  # noqa: E402
from btg.safety import Clamp, ClampSet, SafetyConfig, SafetyPolicy, Watchdog  # noqa: E402
from btg_sdk import ActuatorCommand, hook  # noqa: E402


def _command(channel: str, value: float) -> ActuatorCommand:
    return ActuatorCommand(
        channel=channel,
        actuator_id=f"{channel}:mock:0",
        value=value,
        unit="mA",
        timestamp=0.0,
    )


def test_clamp_within_range() -> None:
    clamps = ClampSet([Clamp("tens_intensity", 0.0, 50.0, "mA")])
    value, clamped = clamps.clamp("tens_intensity", 30.0)
    assert value == 30.0
    assert clamped is False


def test_clamp_exceeds_max() -> None:
    clamps = ClampSet([Clamp("tens_intensity", 0.0, 50.0, "mA")])
    value, clamped = clamps.clamp("tens_intensity", 90.0)
    assert value == 50.0
    assert clamped is True


def test_clamp_unconfigured_channel_passthrough() -> None:
    clamps = ClampSet([Clamp("tens_intensity", 0.0, 50.0, "mA")])
    value, clamped = clamps.clamp("unknown_channel", 999.0)
    assert value == 999.0
    assert clamped is False


def test_config_from_dict() -> None:
    cfg = SafetyConfig.from_dict(
        {
            "watchdog": {"timeout": 3.5},
            "clamps": {"tens_intensity": {"min": 0, "max": 40, "unit": "mA"}},
        }
    )
    assert cfg.watchdog_timeout == 3.5
    assert len(cfg.clamps) == 1


def test_policy_clamps_and_feeds() -> None:
    hook.clear_hooks()
    clamps = ClampSet([Clamp("tens_intensity", 0.0, 50.0, "mA")])
    fired = {"n": 0}

    async def on_timeout() -> None:
        fired["n"] += 1

    watchdog = Watchdog(120.0, on_timeout)
    policy = SafetyPolicy(clamps, watchdog)

    async def scenario() -> None:
        await policy.start()
        out = await policy.check_command(_command("tens_intensity", 80.0))
        assert out.value == 50.0  # 被截断
        await watchdog.check_now()  # 刚喂狗，不应超时
        await policy.stop()

    asyncio.run(scenario())
    assert fired["n"] == 0


def test_hook_blocks_command() -> None:
    hook.clear_hooks()

    @hook.on_safety_check
    async def _forbid(reading: ActuatorCommand) -> None:
        if reading.value > 100.0:
            raise SafetyViolationError("值过大，钩子拦截")

    clamps = ClampSet([])

    async def _cb() -> None:
        pass

    policy = SafetyPolicy(clamps, Watchdog(120.0, _cb))

    async def scenario() -> None:
        await policy.start()
        try:
            await policy.check_command(_command("tens_intensity", 150.0))
        except SafetyViolationError:
            await policy.stop()
            return
        raise AssertionError("钩子未拦截越界指令")

    asyncio.run(scenario())


def test_watchdog_fires_on_timeout() -> None:
    fired = {"n": 0}

    async def on_timeout() -> None:
        fired["n"] += 1

    watchdog = Watchdog(0.05, on_timeout, poll_interval=0.01)

    async def scenario() -> None:
        await watchdog.start()
        await asyncio.sleep(0.12)
        await watchdog.stop()
        assert fired["n"] >= 1

    asyncio.run(scenario())


if __name__ == "__main__":
    test_clamp_within_range()
    test_clamp_exceeds_max()
    test_clamp_unconfigured_channel_passthrough()
    test_config_from_dict()
    test_policy_clamps_and_feeds()
    test_hook_blocks_command()
    test_watchdog_fires_on_timeout()
    print("safety smoke ok")