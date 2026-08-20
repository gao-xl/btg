"""内置执行器模块。"""
from __future__ import annotations

from btg.platform.manifest import ModuleKind, ModuleManifest
from btg.platform.module import ActuatorModule, register_module

# 导入设备实现，触发 @register_actuator 登记。
from btg.hal.actuators.buttplug_bridge import ButtplugBridge  # noqa: F401
from btg.hal.actuators.coyote import CoyoteActuator  # noqa: F401
from btg.hal.actuators.mock_actuator import MockActuator  # noqa: F401
from btg.hal.actuators.yokonex_im import YokoNexImActuator  # noqa: F401


@register_module
class MockActuatorModule(ActuatorModule):
    """开发/联调用虚拟执行器（记录目标值，可模拟下发失败）。"""

    manifest = ModuleManifest(
        name="mock_actuator",
        version="0.1.0",
        kind=ModuleKind.ACTUATOR,
        description="记录目标值的虚拟执行器。",
        capabilities=["set_target"],
    )
    plugin_names = ["mock_actuator"]


@register_module
class CoyoteModule(ActuatorModule):
    """DG-LAB 郊狼（Pulse Host 2.0）BLE 电刺激执行器（可选依赖）。"""

    manifest = ModuleManifest(
        name="coyote",
        version="0.1.0",
        kind=ModuleKind.ACTUATOR,
        description="通过 BLE 直连驱动 DG-LAB 郊狼 V2 电刺激设备。",
        capabilities=["set_target", "collect_feedback"],
    )
    plugin_names = ["coyote"]


@register_module
class YokoNexImModule(ActuatorModule):
    """役次元（YOKONEX）IM 桥接执行器。"""

    manifest = ModuleManifest(
        name="yokonex_im",
        version="0.1.0",
        kind=ModuleKind.ACTUATOR,
        description="通过官方 API-bridge 将安全目标映射到役次元 App 事件 ID。",
        capabilities=["set_target", "collect_feedback"],
    )
    plugin_names = ["yokonex_im"]


@register_module
class ButtplugBridgeModule(ActuatorModule):
    """Buttplug.io / Intiface Central 桥接执行器（可选依赖）。"""

    manifest = ModuleManifest(
        name="buttplug_proxy",
        version="0.1.0",
        kind=ModuleKind.ACTUATOR,
        description="经 Intiface Central 控制 Buttplug 生态设备的桥接执行器。",
        capabilities=["set_target", "collect_feedback"],
    )
    plugin_names = ["buttplug_proxy"]