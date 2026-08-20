"""内置 MQTT 远程设备模块（主机侧远程传感器/执行器）。

对应"主机 + 开发板"方案：真实硬件驱动跑在板端薄代理，本模块让同一
``mqtt_bridge`` 插件名同时提供远程传感器（收板端遥测）与远程执行器
（发指令到板端），从而把每块开发板变成网关里普通的一组设备，
复用既有通道冗余 / 安全层 / 热更新。
"""
from __future__ import annotations

from btg.platform.manifest import ModuleKind, ModuleManifest
from btg.platform.module import ActuatorModule, SensorModule, register_module

# 导入设备实现，触发 @register_* 登记（同一插件名分属 sensor/actuator 两个注册表）。
from btg.hal.sensors.mqtt_remote import MqttRemoteSensor  # noqa: F401
from btg.hal.actuators.mqtt_remote import MqttRemoteActuator  # noqa: F401


@register_module
class MqttRemoteSensorModule(SensorModule):
    """收开发板 MQTT 遥测的远程传感器通道。"""

    manifest = ModuleManifest(
        name="mqtt_remote_sensor",
        version="0.1.0",
        kind=ModuleKind.SENSOR,
        description="从开发板经 MQTT 订阅遥测，把板端采集纳入本机采集管线。",
        capabilities=["stream"],
        dependencies=["paho-mqtt"],
    )
    plugin_names = ["mqtt_bridge"]


@register_module
class MqttRemoteActuatorModule(ActuatorModule):
    """把执行目标发给开发板的远程执行器通道。"""

    manifest = ModuleManifest(
        name="mqtt_remote_actuator",
        version="0.1.0",
        kind=ModuleKind.ACTUATOR,
        description="把安全后的执行目标经 MQTT 转发给开发板本地驱动。",
        capabilities=["set_target"],
        dependencies=["paho-mqtt"],
    )
    plugin_names = ["mqtt_bridge"]