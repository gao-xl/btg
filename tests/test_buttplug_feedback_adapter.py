"""Buttplug 反馈适配器单元测试（无真实硬件 / 无需安装 buttplug）。

覆盖：
- 能力矩阵解析（map / message_attributes / has_output 三种路径 + 容错）；
- 电量查询安全化（正常 / 返回 None / 抛异常 / 超时）；
- 统一帧与既有 ``DeviceFeedback`` / ``ActuatorStatusFrame`` 的互转；
- 断连看门狗触发安全回调。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "sdk", _ROOT / "backend" / "src"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from btg.hal.actuators.buttplug_feedback_adapter import (  # noqa: E402
    ActuatorTelemetryFrame,
    ButtplugCapability,
    ButtplugFeedbackAdapter,
    ButtplugFeedbackAdapterConfig,
    inspect_capabilities,
    query_battery_safe,
)
from btg_sdk import FeedbackKind  # noqa: E402


# ── 假 Buttplug 设备 / 客户端 ─────────────────────────────────────────────

class _CapAttr:
    def __init__(self, step_count: int = 0, rng=None):
        self.step_count = step_count
        self.range = rng


class FakeDevice:
    """以 map 特征目录暴露能力的设备（buttplug-py 新版本形态）。"""

    def __init__(self, name="toy", outputs=None, inputs=None):
        self.name = name
        self.outputs = outputs or {}
        self.inputs = inputs or {}
        self.battery_calls = 0

    async def battery(self) -> float:
        self.battery_calls += 1
        return 0.42


class BadCapabilityDevice:
    """message_attributes 抛出异常的“刁钻”设备。"""

    name = "glitch"

    def has_input(self, *_):
        raise RuntimeError("boom")
    has_output = has_input


class NoBatteryDevice:
    name = "cheap"
    outputs = {"VIBRATE": [object()]}
    inputs = {}


class SlowBatteryDevice:
    name = "slow"
    outputs = {}
    inputs = {"BATTERY": []}

    async def battery(self):
        await asyncio.sleep(10.0)  # 远超超时。


# ── 能力矩阵解析 ──────────────────────────────────────────────────────────


def test_inspect_from_maps():
    device = FakeDevice(outputs={"VIBRATE": [_CapAttr(20), _CapAttr(10)]})
    caps = inspect_capabilities(device)
    vibe = caps["VIBRATE"]
    assert vibe.supported is True
    assert vibe.channels == 2
    assert vibe.step_count == 20  # 取最大
    assert vibe.kind == "output"


def test_inspect_tolerates_hostile_device():
    caps = inspect_capabilities(BadCapabilityDevice())
    # 不得抛出任何异常；能力矩阵可为空。
    assert isinstance(caps, dict)


def test_inspect_has_output_fallback():
    class OnOffDevice:
        name = "onoff"
        capabilities = {"VIBRATE": 4}
        def has_output(self, enum):
            return enum is not None
        has_input = has_output

    caps = inspect_capabilities(OnOffDevice())
    assert {"VIBRATE", "LINEAR", "ROTATE"}.issubset(caps.keys())
    assert all(isinstance(c, ButtplugCapability) for c in caps.values())


# ── 电量查询 ──────────────────────────────────────────────────────────────


def test_battery_safe_success():
    device = FakeDevice()
    assert asyncio.run(query_battery_safe(device, timeout=1.0)) == 42.0
    assert device.battery_calls == 1


def test_battery_safe_returns_none_for_unsupported():
    assert asyncio.run(query_battery_safe(NoBatteryDevice(), timeout=1.0)) is None


def test_battery_safe_swallows_error():
    class BoomDevice:
        name = "boom"
        async def battery(self):
            raise RuntimeError("nope")

    assert asyncio.run(query_battery_safe(BoomDevice(), timeout=1.0)) is None


def test_battery_safe_times_out():
    assert asyncio.run(query_battery_safe(SlowBatteryDevice(), timeout=0.05)) is None


# ── 统一帧转换 ────────────────────────────────────────────────────────────


def test_frame_to_device_feedback():
    frame = ActuatorTelemetryFrame(
        device_id="fb:toy", timestamp=1.0, connected=True, battery_pct=42.0,
    )
    feedback = frame.to_device_feedback()
    assert feedback.kind == FeedbackKind.CONNECTION
    assert feedback.value == 1.0
    assert feedback.extra["battery_pct"] == 42.0


def test_frame_to_status_frame():
    frame = ActuatorTelemetryFrame(
        device_id="fb:toy", timestamp=1.0, connected=False, signal_quality=0.0,
    )
    status = frame.to_status_frame()
    assert status.connected is False
    assert status.battery_pct is None


# ── 断连看门狗 ────────────────────────────────────────────────────────────


def test_disconnect_triggers_safety_callback():
    adapter = ButtplugFeedbackAdapter({"instance_id": "fb"})
    received: list[ActuatorTelemetryFrame] = []

    async def safety(frame: ActuatorTelemetryFrame) -> None:
        received.append(frame)

    async def scenario() -> None:
        adapter.set_disconnect_callback(safety)
        adapter._on_device_removed(FakeDevice(name="lost"))
        await _drain(adapter)

    asyncio.run(scenario())

    assert received, "断连安全回调必须触发"
    assert received[0].connected is False
    assert received[0].device_id == "fb:lost"


def test_disconnect_callback_exception_does_not_crash():
    adapter = ButtplugFeedbackAdapter({"instance_id": "fb"})

    async def exploding(_frame: ActuatorTelemetryFrame) -> None:
        raise RuntimeError("safety handler failed")

    async def scenario() -> None:
        adapter.set_disconnect_callback(exploding)
        adapter._on_device_removed(FakeDevice(name="lost"))
        await _drain(adapter)  # 不应抛到外部。

    asyncio.run(scenario())


# ── 配置校验 ──────────────────────────────────────────────────────────────


def test_config_defaults_and_validation():
    cfg = ButtplugFeedbackAdapterConfig.model_validate({})
    assert cfg.instance_id == "buttplug_feedback"
    with pytest.raises(Exception):
        ButtplugFeedbackAdapterConfig.model_validate({"poll_interval_seconds": 0.1})


async def _drain(adapter: ButtplugFeedbackAdapter) -> None:
    """等待适配器排空后台任务。"""
    for _ in range(50):
        if not adapter._tasks:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("后台任务未及时排空")