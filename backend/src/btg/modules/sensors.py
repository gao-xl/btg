"""内置传感器模块。"""
from __future__ import annotations

from btg.platform.manifest import ModuleKind, ModuleManifest
from btg.platform.module import SensorModule, register_module

# 导入设备实现，触发 @register_sensor 登记。
from btg.hal.sensors.mock_sensor import MockSensor  # noqa: F401

try:
    from btg.hal.sensors.ble_heart_rate import BleHeartRateSensor  # noqa: F401
except ImportError:
    BleHeartRateSensor = None  # type: ignore[assignment,misc]

try:
    from btg.hal.sensors.ble_heart_rate import XiaomiBleHeartRateSensor  # noqa: F401
except ImportError:
    XiaomiBleHeartRateSensor = None  # type: ignore[assignment,misc]


@register_module
class MockSensorModule(SensorModule):
    """开发/联调用虚拟传感器（周期产出可配置读数，支持模拟断连）。"""

    manifest = ModuleManifest(
        name="mock_sensor",
        version="0.1.0",
        kind=ModuleKind.SENSOR,
        description="周期产出可配置读数的虚拟传感器。",
        capabilities=["stream"],
    )
    plugin_names = ["mock_sensor"]


@register_module
class BleHeartRateModule(SensorModule):
    """BLE 标准心率带传感器（Magene / Polar / Garmin 等兼容设备）。"""

    manifest = ModuleManifest(
        name="ble_heart_rate",
        version="0.1.0",
        kind=ModuleKind.SENSOR,
        description="通过 BLE 连接标准心率带，实时解析心率数据。",
        capabilities=["stream"],
        dependencies=["bleak"],
    )
    plugin_names = ["ble_heart_rate"]


@register_module
class XiaomiBleHeartRateModule(SensorModule):
    """小米 BLE 心率传感器（Mi Band 5/6/7/8/9/10 等）。

    通过被动嗅探 MiBeacon 广播数据获取心率，无需主动连接设备。
    需要提供 16 字节认证密钥（auth_key）以解密广播数据。
    """

    manifest = ModuleManifest(
        name="xiaomi_heart_rate",
        version="0.1.0",
        kind=ModuleKind.SENSOR,
        description="通过被动嗅探小米 MiBeacon 广播获取心率数据。",
        capabilities=["stream"],
        dependencies=["bleak", "xiaomi-ble"],
    )
    plugin_names = ["xiaomi_heart_rate"]
