"""Tests for the BLE Heart Rate sensor plugin."""
from __future__ import annotations

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from btg.hal.sensors.ble_heart_rate import (
    HR_MEASUREMENT_UUID,
    HR_SERVICE_UUID,
    BleHeartRateSensor,
    XiaomiBleHeartRateSensor,
    _parse_heart_rate_measurement,
    _parse_xiaomi_mibeacon,
    connect_heart_rate_device,
)
from btg_sdk import Reading


# ── Packet Parser ─────────────────────────────────────────────────────────


class TestParseHeartRateMeasurement:
    """Bluetooth SIG Heart Rate Measurement 解析器测试。"""

    def test_8bit_heart_rate(self):
        """Flags bit 0 = 0 → 8-bit heart rate."""
        flags = 0x00
        bpm = 72
        data = bytearray([flags, bpm])
        assert _parse_heart_rate_measurement(data) == 72

    def test_16bit_heart_rate(self):
        """Flags bit 0 = 1 → 16-bit heart rate."""
        flags = 0x01
        bpm = 180
        data = bytearray([flags]) + struct.pack("<H", bpm)
        assert _parse_heart_rate_measurement(data) == 180

    def test_8bit_with_energy_expenditure(self):
        """8-bit HR + energy expended field (Flags bit 3)."""
        flags = 0x08
        bpm = 95
        energy = 500
        data = bytearray([flags, bpm]) + struct.pack("<H", energy)
        assert _parse_heart_rate_measurement(data) == 95

    def test_16bit_with_energy_and_rr(self):
        """16-bit HR + energy expended + RR intervals."""
        flags = 0x01 | 0x08 | 0x10
        bpm = 120
        energy = 1000
        rr1 = 800
        rr2 = 810
        data = bytearray([flags])
        data += struct.pack("<H", bpm)
        data += struct.pack("<H", energy)
        data += struct.pack("<H", rr1)
        data += struct.pack("<H", rr2)
        assert _parse_heart_rate_measurement(data) == 120

    def test_8bit_with_rr_intervals(self):
        """8-bit HR + RR intervals only."""
        flags = 0x10
        bpm = 65
        rr = 923
        data = bytearray([flags, bpm]) + struct.pack("<H", rr)
        assert _parse_heart_rate_measurement(data) == 65

    def test_empty_data_returns_none(self):
        assert _parse_heart_rate_measurement(bytearray()) is None

    def test_single_byte_returns_none(self):
        assert _parse_heart_rate_measurement(bytearray([0x00])) is None

    def test_16bit_truncated_returns_none(self):
        """16-bit flag set but only 2 bytes total (need 3)."""
        flags = 0x01
        data = bytearray([flags, 0x00])
        assert _parse_heart_rate_measurement(data) is None

    def test_out_of_range_high_returns_none(self):
        """Heart rate > 300 is physiologically impossible."""
        flags = 0x01
        data = bytearray([flags]) + struct.pack("<H", 301)
        assert _parse_heart_rate_measurement(data) is None

    def test_out_of_range_negative_returns_none(self):
        """Negative heart rate is invalid."""
        flags = 0x01
        data = bytearray([flags]) + struct.pack("<H", 0xFFFF)
        assert _parse_heart_rate_measurement(data) is None

    def test_zero_heart_rate_is_valid(self):
        """0 BPM is technically parseable (though physiologically odd)."""
        flags = 0x00
        data = bytearray([flags, 0])
        assert _parse_heart_rate_measurement(data) == 0

    def test_max_valid_heart_rate(self):
        """300 BPM is the upper bound."""
        flags = 0x01
        data = bytearray([flags]) + struct.pack("<H", 300)
        assert _parse_heart_rate_measurement(data) == 300


# ── MiBeacon Parser ──────────────────────────────────────────────────────


class TestParseXiaomiMibeacon:
    """小米 MiBeacon 广播数据解析器测试。"""

    def test_short_data_returns_none(self):
        """Too short data returns None."""
        assert _parse_xiaomi_mibeacon(bytearray([0x00] * 5)) is None

    def test_no_cumulative_flag_returns_none(self):
        """Frame without cumulative data flag returns None."""
        # Frame control bit 14 = 0
        frame_control = 0x000000
        data = bytearray(frame_control.to_bytes(3, "little"))
        data += bytearray(10)  # padding
        assert _parse_xiaomi_mibeacon(data) is None

    def test_valid_heart_rate_object(self):
        """Valid MiBeacon with heart rate object (0x1048)."""
        # Frame control: bit 14 = 1 (cumulative data)
        frame_control = 0x4000
        data = bytearray(frame_control.to_bytes(3, "little"))
        # MAC address (6 bytes)
        data += bytearray([0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC])
        # Capability (2 bytes)
        data += bytearray([0x00, 0x00])
        # Counter (1 byte)
        data += bytearray([0x01])
        # Object ID 0x1048 (heart rate)
        data += struct.pack("<H", 0x1048)
        # Object length
        data += bytearray([0x01])
        # Heart rate value
        data += bytearray([0x50])  # 80 BPM

        bpm = _parse_xiaomi_mibeacon(data)
        assert bpm == 80

    def test_invalid_object_id_returns_none(self):
        """Non-heart-rate object returns None."""
        frame_control = 0x4000
        data = bytearray(frame_control.to_bytes(3, "little"))
        data += bytearray([0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC])
        data += bytearray([0x00, 0x00])
        data += bytearray([0x01])
        # Object ID 0x1004 (temperature, not heart rate)
        data += struct.pack("<H", 0x1004)
        data += bytearray([0x02])
        data += bytearray([0x00, 0x01])

        assert _parse_xiaomi_mibeacon(data) is None

    def test_heart_rate_out_of_range_returns_none(self):
        """Heart rate > 300 returns None."""
        frame_control = 0x4000
        data = bytearray(frame_control.to_bytes(3, "little"))
        data += bytearray([0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC])
        data += bytearray([0x00, 0x00])
        data += bytearray([0x01])
        data += struct.pack("<H", 0x1048)
        data += bytearray([0x01])
        data += bytearray([0xFF])  # 255 BPM (valid)

        assert _parse_xiaomi_mibeacon(data) == 255


# ── Config Validation ─────────────────────────────────────────────────────


class TestBleHeartRateConfig:
    """配置模型校验。"""

    def test_default_config(self):
        sensor = BleHeartRateSensor({"instance_id": "test_hr"})
        assert sensor.instance_id == "test_hr"
        assert sensor._channel == "heart_rate"
        assert sensor._device_name_prefix == "Magene"
        assert sensor._device_address is None

    def test_custom_config(self):
        sensor = BleHeartRateSensor({
            "instance_id": "custom",
            "device_name_prefix": "Polar",
            "device_address": "AA:BB:CC:DD:EE:FF",
            "reconnect_delay_seconds": 5.0,
            "scan_timeout_seconds": 15.0,
            "channel": "hr_custom",
        })
        assert sensor.instance_id == "custom"
        assert sensor._device_name_prefix == "Polar"
        assert sensor._device_address == "AA:BB:CC:DD:EE:FF"
        assert sensor._reconnect_delay == 5.0
        assert sensor._scan_timeout == 15.0
        assert sensor._channel == "hr_custom"

    def test_empty_prefix_matches_all(self):
        sensor = BleHeartRateSensor({
            "instance_id": "any",
            "device_name_prefix": "",
        })
        assert sensor._device_name_prefix == ""


class TestXiaomiBleHeartRateConfig:
    """小米 BLE 心率传感器配置测试。"""

    def test_xiaomi_config_defaults(self):
        sensor = XiaomiBleHeartRateSensor({
            "instance_id": "xiaomi_test",
        })
        assert sensor.instance_id == "xiaomi_test"
        assert sensor._device_name_prefix == "Mi Band"
        assert sensor._xiaomi_passive is True

    def test_xiaomi_config_with_auth_key(self):
        auth_key = "308b2eb4" + "0" * 24  # 16 bytes hex
        sensor = XiaomiBleHeartRateSensor({
            "instance_id": "xiaomi_test",
            "xiaomi_auth_key": auth_key,
            "xiaomi_device_model": "M2457B1",
            "xiaomi_passive": False,
        })
        assert sensor._xiaomi_auth_key == auth_key
        assert sensor._auth_key_bytes is not None
        assert len(sensor._auth_key_bytes) == 16
        assert sensor._xiaomi_device_model == "M2457B1"
        assert sensor._xiaomi_passive is False

    def test_xiaomi_invalid_auth_key_warning(self):
        """Invalid auth key length generates warning but doesn't crash."""
        sensor = XiaomiBleHeartRateSensor({
            "instance_id": "xiaomi_test",
            "xiaomi_auth_key": "001122",  # Only 3 bytes
        })
        assert sensor._auth_key_bytes is None


# ── SDK Registration ──────────────────────────────────────────────────────


class TestRegistration:
    """插件注册表与平台模块登记。"""

    def test_registered_in_sdk(self):
        from btg_sdk import get_sensor_class
        cls = get_sensor_class("ble_heart_rate")
        assert cls is BleHeartRateSensor

    def test_xiaomi_registered_in_sdk(self):
        from btg_sdk import get_sensor_class
        cls = get_sensor_class("xiaomi_heart_rate")
        assert cls is XiaomiBleHeartRateSensor

    def test_module_manifest(self):
        from btg.modules.sensors import BleHeartRateModule
        m = BleHeartRateModule.manifest
        assert m.name == "ble_heart_rate"
        assert m.kind.value == "sensor"
        assert "stream" in m.capabilities


# ── Notification Handler ──────────────────────────────────────────────────


class TestNotificationHandler:
    """Notification 回调解析与队列写入。"""

    def test_handler_writes_valid_bpm(self):
        sensor = BleHeartRateSensor({"instance_id": "test"})
        data = bytearray([0x00, 75])
        sensor._notification_handler(None, data)
        assert not sensor._notification_queue.empty()
        assert sensor._notification_queue.get_nowait() == 75

    def test_handler_ignores_malformed_data(self):
        sensor = BleHeartRateSensor({"instance_id": "test"})
        sensor._notification_handler(None, bytearray([0x01]))  # too short
        assert sensor._notification_queue.empty()

    def test_handler_discards_on_full_queue(self):
        sensor = BleHeartRateSensor({"instance_id": "test"})
        sensor._notification_queue = asyncio.Queue(maxsize=2)
        sensor._notification_handler(None, bytearray([0x00, 60]))
        sensor._notification_handler(None, bytearray([0x00, 70]))
        sensor._notification_handler(None, bytearray([0x00, 80]))  # drops 60
        assert sensor._notification_queue.qsize() == 2
        assert sensor._notification_queue.get_nowait() == 70

    def test_handler_parses_16bit(self):
        sensor = BleHeartRateSensor({"instance_id": "test"})
        data = bytearray([0x01]) + struct.pack("<H", 165)
        sensor._notification_handler(None, data)
        assert sensor._notification_queue.get_nowait() == 165


class TestXiaomiNotificationHandler:
    """小米 MiBeacon 回调解析与队列写入。"""

    def test_handler_writes_valid_bpm(self):
        sensor = XiaomiBleHeartRateSensor({"instance_id": "test"})
        # 构造有效的 MiBeacon 心率广播
        frame_control = 0x4000
        data = bytearray(frame_control.to_bytes(3, "little"))
        data += bytearray([0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC])
        data += bytearray([0x00, 0x00])
        data += bytearray([0x01])
        data += struct.pack("<H", 0x1048)
        data += bytearray([0x01])
        data += bytearray([0x48])  # 72 BPM

        sensor._xiaomi_notification_handler(None, data)
        assert not sensor._notification_queue.empty()
        assert sensor._notification_queue.get_nowait() == 72


# ── Disconnect Callback ───────────────────────────────────────────────────


class TestDisconnectCallback:
    """断连回调设置 connected 标志。"""

    def test_on_disconnect_clears_flag(self):
        sensor = BleHeartRateSensor({"instance_id": "test"})
        sensor._connected = True
        sensor._on_disconnect(None)
        assert sensor._connected is False

    def test_xiaomi_on_disconnect_clears_flag(self):
        sensor = XiaomiBleHeartRateSensor({"instance_id": "test"})
        sensor._connected = True
        sensor._on_disconnect(None)
        assert sensor._connected is False


# ── BaseSensor Contract ───────────────────────────────────────────────────


class TestBaseSensorContract:
    """确保实现满足 BaseSensor 接口。"""

    def test_is_subclass(self):
        from btg_sdk import BaseSensor
        assert issubclass(BleHeartRateSensor, BaseSensor)

    def test_xiaomi_is_subclass(self):
        from btg_sdk import BaseSensor
        assert issubclass(XiaomiBleHeartRateSensor, BaseSensor)

    def test_has_required_methods(self):
        assert hasattr(BleHeartRateSensor, "connect")
        assert hasattr(BleHeartRateSensor, "disconnect")
        assert hasattr(BleHeartRateSensor, "read_stream")

    def test_xiaomi_has_required_methods(self):
        assert hasattr(XiaomiBleHeartRateSensor, "connect")
        assert hasattr(XiaomiBleHeartRateSensor, "disconnect")
        assert hasattr(XiaomiBleHeartRateSensor, "read_stream")

    @pytest.mark.asyncio
    async def test_disconnect_is_idempotent(self):
        sensor = BleHeartRateSensor({"instance_id": "test"})
        await sensor.disconnect()
        await sensor.disconnect()  # should not raise
        assert sensor._connected is False

    @pytest.mark.asyncio
    async def test_xiaomi_disconnect_is_idempotent(self):
        sensor = XiaomiBleHeartRateSensor({"instance_id": "test"})
        await sensor.disconnect()
        await sensor.disconnect()  # should not raise
        assert sensor._connected is False


# ── Factory Function ──────────────────────────────────────────────────────


class TestConnectHeartRateDevice:
    """便捷工厂函数测试。"""

    @pytest.mark.asyncio
    async def test_factory_returns_ble_sensor_for_standard(self):
        sensor = await connect_heart_rate_device("Magene")
        assert isinstance(sensor, BleHeartRateSensor)

    @pytest.mark.asyncio
    async def test_factory_returns_xiaomi_sensor_for_auth_key(self):
        auth_key = "308b2eb4" + "0" * 24
        sensor = await connect_heart_rate_device(
            "Mi Band",
            auth_key=auth_key,
        )
        assert isinstance(sensor, XiaomiBleHeartRateSensor)

    @pytest.mark.asyncio
    async def test_factory_with_address(self):
        sensor = await connect_heart_rate_device(
            "Polar",
            device_address="AA:BB:CC:DD:EE:FF",
        )
        assert isinstance(sensor, BleHeartRateSensor)
        assert sensor._device_address == "AA:BB:CC:DD:EE:FF"

    @pytest.mark.asyncio
    async def test_factory_xiaomi_with_model(self):
        auth_key = "308b2eb4" + "0" * 24
        sensor = await connect_heart_rate_device(
            "Mi Band",
            auth_key=auth_key,
            device_model="M2457B1",
        )
        assert isinstance(sensor, XiaomiBleHeartRateSensor)
        assert sensor._xiaomi_device_model == "M2457B1"
