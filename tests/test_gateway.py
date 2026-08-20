"""网关端到端冒烟测试：融合引擎 → 安全层 → 执行器 与 配置热更新接线。

独立运行：``python tests/test_gateway.py``
pytest 运行：``pytest tests/``
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "sdk", _ROOT / "backend" / "src", _ROOT / "tests"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from btg.fusion import Rule, STATE_ELEVATED  # noqa: E402
from btg_sdk import ActuatorCommand  # noqa: E402
from helpers import build_gateway  # noqa: E402


def _elevated_rule() -> Rule:
    return Rule(
        name="elevated_hr",
        target_state=STATE_ELEVATED,
        condition=lambda snaps: "heart_rate" in snaps
        and snaps["heart_rate"].latest_value > 100.0,
        commands=[ActuatorCommand(
            channel="tens_intensity", actuator_id="", value=30.0, unit="mA", timestamp=0.0
        )],
        priority=1,
    )


def test_fusion_to_actuator_pipeline() -> None:
    gateway = build_gateway(
        Path(tempfile.mkdtemp()),
        rules=[_elevated_rule()],
        base_value=120.0,  # 心率恒高于 100，规则立即命中
    )

    async def scenario() -> None:
        await gateway.start()
        try:
            deadline = asyncio.get_running_loop().time() + 2.0
            group = gateway.channel_manager.actuator_groups["tens_intensity"]
            while asyncio.get_running_loop().time() < deadline:
                if group.active is not None and group.active.device.targets.get("tens_intensity") == 30.0:
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("融合引擎未在超时内下发指令到执行器")

            assert gateway.fusion.state_machine.current == STATE_ELEVATED
            assert gateway.ring_buffer.latest("heart_rate") is not None
        finally:
            await gateway.stop()

    asyncio.run(scenario())


def test_config_reload_wires_to_safety() -> None:
    td = tempfile.mkdtemp()
    gateway = build_gateway(Path(td))

    assert gateway.safety_policy.global_max == 50.0
    assert gateway.watchdog.timeout == 30.0

    gateway.config_manager.update_settings({
        "max_system_intensity": 10,
        "watchdog_timeout_sec": 5.0,
    })

    assert gateway.safety_policy.global_max == 10.0
    assert gateway.watchdog.timeout == 5.0


if __name__ == "__main__":
    test_config_reload_wires_to_safety()
    test_fusion_to_actuator_pipeline()
    print("gateway smoke ok")