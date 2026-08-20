"""HAL 层冒烟测试：插件加载、传感器冗余切换、执行器冗余切换。

独立运行：``python tests/test_hal.py``
pytest 运行：``pytest tests/``
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "sdk"))
sys.path.insert(0, str(_ROOT / "backend" / "src"))

from btg.hal import ChannelManager, discover_and_load, parse_channels  # noqa: E402

_PLUGIN_PACKAGES = ["btg.hal.sensors", "btg.hal.actuators"]


def _sensor_config():
    return parse_channels(
        {
            "heart_rate": {
                "type": "sensor",
                "devices": [
                    {
                        "plugin": "mock_sensor",
                        "priority": 1,
                        "config": {
                            "channel": "heart_rate",
                            "unit": "bpm",
                            "base_value": 80.0,
                            "interval": 0.01,
                            "cycles": 3,
                        },
                    },
                    {
                        "plugin": "mock_sensor",
                        "priority": 2,
                        "config": {
                            "channel": "heart_rate",
                            "unit": "bpm",
                            "base_value": 85.0,
                            "interval": 0.01,
                        },
                    },
                ],
            }
        }
    )


def _actuator_config():
    return parse_channels(
        {
            "tens": {
                "type": "actuator",
                "devices": [
                    {"plugin": "mock_actuator", "priority": 1, "config": {"fail_on_set": True}},
                    {"plugin": "mock_actuator", "priority": 2},
                ],
            }
        }
    )


def test_sensor_failover() -> None:
    discover_and_load(_PLUGIN_PACKAGES)
    queue: asyncio.Queue = asyncio.Queue()
    manager = ChannelManager(_sensor_config(), queue)

    async def scenario() -> None:
        await manager.start()
        group = manager.sensor_groups["heart_rate"]
        primary_id = "heart_rate:mock_sensor:0"
        backup_id = "heart_rate:mock_sensor:1"
        assert group.active is not None and group.active.instance_id == primary_id

        seen_primary = False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 3.0
        while loop.time() < deadline:
            try:
                reading = await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if reading.sensor_id == primary_id:
                seen_primary = True
            if reading.sensor_id == backup_id:
                break

        assert seen_primary, "未观察到主设备读数"
        assert group.active is not None and group.active.instance_id == backup_id
        await manager.stop()

    asyncio.run(scenario())


def test_actuator_failover() -> None:
    discover_and_load(_PLUGIN_PACKAGES)
    manager = ChannelManager(_actuator_config(), asyncio.Queue())

    async def scenario() -> None:
        await manager.start()
        group = manager.actuator_groups["tens"]
        ok = await group.set_target(120.0)
        assert ok is True
        # 主执行器 fail_on_set=True → 自动切换到备用（index 1）
        assert group.active is not None and group.active.instance_id == "tens:mock_actuator:1"
        targets = getattr(group.active.device, "targets", {})
        assert targets.get("tens") == 120.0
        await manager.stop()

    asyncio.run(scenario())


if __name__ == "__main__":
    test_sensor_failover()
    test_actuator_failover()
    print("hal smoke ok")