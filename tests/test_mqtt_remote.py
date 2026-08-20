"""主机↔板端 MQTT 传输与远程设备的相关测试。

不需要真 paho / broker：覆盖消息编解码、主题、插件注册，以及板端 mock 驱动。
"""
from __future__ import annotations

import time

import btg_sdk
from btg_sdk import Reading
from btg_sdk.transport import (
    ack_topic,
    command_topic,
    decode_command,
    decode_telemetry,
    encode_ack,
    encode_command,
    encode_event,
    encode_telemetry,
    event_topic,
    telemetry_topic,
)


def test_topic_functions():
    assert telemetry_topic("rk-01") == "btg/rk-01/telemetry"
    assert event_topic("rk-01") == "btg/rk-01/event"
    assert command_topic("rk-01") == "btg/rk-01/command"
    assert ack_topic("rk-01") == "btg/rk-01/ack"
    assert telemetry_topic("rk-01", prefix="iot") == "iot/rk-01/telemetry"


def test_telemetry_roundtrip():
    reading = Reading(
        channel="heart_rate",
        sensor_id="mock:rk-01:heart_rate",
        value=72.0,
        unit="bpm",
        timestamp=time.time(),
        extra={"board": "rk-01"},
    )
    payload = encode_telemetry("rk-01", [reading])
    board, readings = decode_telemetry(payload.encode())
    assert board == "rk-01"
    assert len(readings) == 1
    got = readings[0]
    assert got.channel == "heart_rate"
    assert got.sensor_id == "mock:rk-01:heart_rate"
    assert got.value == 72.0
    assert got.unit == "bpm"
    assert got.extra == {"board": "rk-01"}


def test_command_roundtrip():
    payload = encode_command("rk-01", "tens_intensity", 42.0, unit="%")
    cmd = decode_command(payload.encode())
    assert cmd["board"] == "rk-01"
    assert cmd["channel"] == "tens_intensity"
    assert cmd["action"] == "set"
    assert cmd["value"] == 42.0
    assert cmd["nonce"]


def test_command_stop_has_no_value():
    payload = encode_command("rk-01", "_all", None, action="stop")
    cmd = decode_command(payload.encode())
    assert cmd["action"] == "stop"
    assert cmd["value"] is None


def test_ack_and_event_encode():
    ack = encode_ack("rk-01", "nonce-1", ok=True)
    assert '"ok": true' in ack
    evt = encode_event("rk-01", "heartbeat")
    assert '"kind": "heartbeat"' in evt


def test_decode_event():
    from btg_sdk.transport import decode_event

    evt = decode_event(encode_event("rk-01", "heartbeat").encode())
    assert evt["board"] == "rk-01"
    assert evt["kind"] == "heartbeat"
    assert evt["ts"] > 0


def test_mqtt_bus_tracks_board_online():
    """心跳将板标记在线；仅登记（配置了但也无心跳）时为离线。"""
    from btg.hal.mqtt_bus import MqttBus

    bus = MqttBus()
    bus._register_board("rk-01")
    assert bus.boards()["rk-01"]["online"] is False

    bus._touch_board("rk-01", ts=1000.0)
    assert bus.boards()["rk-01"]["online"] is True
    assert bus.boards()["rk-01"]["last_seen"] == 1000.0
    assert bus.boards()["rk-01"]["first_seen"] == 1000.0


def test_mqtt_plugins_registered():
    """导入内置模块后，sensor/actuator 注册表均应含 mqtt_bridge 插件。"""
    import btg.modules.mqtt_bridge  # noqa: F401  # 触发设备登记副作用

    assert btg_sdk.get_sensor_class("mqtt_bridge").__name__ == "MqttRemoteSensor"
    assert btg_sdk.get_actuator_class("mqtt_bridge").__name__ == "MqttRemoteActuator"


def test_board_mock_drivers():
    from board_agent.config import ActuatorChannel, SensorChannel
    from board_agent.drivers import build_drivers

    sensors = build_drivers(
        "rk-01",
        [SensorChannel("heart_rate", "mock_hr", interval=1.0)],
        actuator=False,
    )
    actuators = build_drivers(
        "rk-01", [ActuatorChannel("tens_intensity", "mock_act")], actuator=True
    )
    reading = sensors["heart_rate"].read()
    assert reading is not None and reading.channel == "heart_rate"
    assert actuators["tens_intensity"].set_target(42.0) is True
    assert actuators["tens_intensity"].last_value == 42.0
    actuators["tens_intensity"].stop()
    assert actuators["tens_intensity"].last_value == 0.0