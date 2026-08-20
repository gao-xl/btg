"""模块抽象基类与登记装饰器。

一个"模块"是平台的最小可插拔单元：持有 manifest、实现核心生命周期
（``setup`` / ``start`` / ``stop`` / ``health``），并通过
:class:`btg.platform.context.PlatformContext` 访问平台能力。
"""
from __future__ import annotations

from abc import ABC
from typing import ClassVar, List, Optional, Type

from btg_sdk import get_actuator_class, get_provider_class, get_sensor_class

from .context import PlatformContext
from .manifest import ModuleKind, ModuleManifest

# 装饰器登记的模块类（发现期收集，运行期由 Kernel 实例化）。
_REGISTERED_MODULE_CLASSES: List[Type["Module"]] = []


def register_module(cls: Type["Module"]) -> Type["Module"]:
    """登记一个模块实现，供平台加载器发现。"""
    if not hasattr(cls, "manifest") or not isinstance(cls.manifest, ModuleManifest):
        raise TypeError(f"{cls.__name__} 必须定义 ModuleManifest 类型的 manifest")
    if cls not in _REGISTERED_MODULE_CLASSES:
        _REGISTERED_MODULE_CLASSES.append(cls)
    return cls


def registered_module_classes() -> List[Type["Module"]]:
    """返回装饰器登记的模块类副本。"""
    return list(_REGISTERED_MODULE_CLASSES)


def clear_registered_modules() -> None:
    """清空登记列表（测试隔离）。"""
    _REGISTERED_MODULE_CLASSES.clear()


class Module(ABC):
    """平台可插拔模块基类。

    子类必须定义 ``manifest``；``setup`` / ``start`` / ``stop`` 均须幂等。
    """

    manifest: ClassVar[ModuleManifest]

    def __init__(self, context: PlatformContext) -> None:
        self.context = context

    # ------------------------------------------------------------------ #
    # 识别
    # ------------------------------------------------------------------ #
    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def kind(self) -> ModuleKind:
        return self.manifest.kind

    @property
    def version(self) -> str:
        return self.manifest.version

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    async def setup(self) -> None:
        """初始化并校验模块贡献（幂等，可被重复调用）。"""

    async def start(self) -> None:
        """启动运行时（幂等）。"""

    async def stop(self) -> None:
        """停止运行时并释放资源（幂等）。"""

    async def health(self) -> dict:
        """返回轻量健康信息。"""
        return {"name": self.name, "kind": self.kind.value, "status": "ok"}

    # ------------------------------------------------------------------ #
    # 元数据
    # ------------------------------------------------------------------ #
    def describe(self) -> dict:
        """返回可 JSON 序列化的模块元数据。"""
        return {
            "name": self.name,
            "version": self.version,
            "kind": self.kind.value,
            "description": self.manifest.description,
            "capabilities": list(self.manifest.capabilities),
            "dependencies": list(self.manifest.dependencies),
        }


class DeviceModule(Module, ABC):
    """向 SDK 注册表贡献设备/平台实现的模块基类（sensor/actuator/provider）。

    约定：设备实现类在其模块被 import 时通过 ``@register_*`` 登记（副作用），
    本基类的 ``setup()`` 仅校验对应插件名确实已登记，未登记则抛 ``KeyError``。
    """

    plugin_names: ClassVar[List[str]] = []
    _kind_getter: ClassVar[Optional[object]] = None

    async def setup(self) -> None:
        getter = self._kind_getter
        if getter is None:
            return
        for name in self.plugin_names:
            getter(name)  # 未注册时抛出 KeyError


class SensorModule(DeviceModule):
    """传感器模块基类。"""

    _kind_getter = staticmethod(get_sensor_class)


class ActuatorModule(DeviceModule):
    """执行器模块基类。"""

    _kind_getter = staticmethod(get_actuator_class)


class ProviderModule(DeviceModule):
    """第三方平台模块基类。"""

    _kind_getter = staticmethod(get_provider_class)


class AgentModule(Module, ABC):
    """网关外独立进程代理模块基类。

    与设备模块不同，代理在独立进程中运行（``python -m btg.agents.*.main``）。
    平台内核仅登记其 manifest 与入口点，不在网关进程内托管其生命周期。
    """

    entrypoint: ClassVar[Optional[str]] = None