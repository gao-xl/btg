"""BTG 插件平台内核：manifest / 模块契约 / 注册表 / 双轨加载器 / 内核编排。

平台负责把"核心网关"与"可插拔模块"解耦：核心只依赖本包定义的契约，
任何传感器、执行器、第三方平台或代理都以模块形式被统一发现与编排。
"""
from .context import PlatformContext
from .kernel import Kernel
from .loader import (
    DEFAULT_ENTRY_POINT_GROUP,
    load_builtin_classes,
    load_directory_classes,
    load_entry_point_classes,
)
from .manifest import ModuleKind, ModuleManifest
from .module import (
    ActuatorModule,
    AgentModule,
    DeviceModule,
    Module,
    ProviderModule,
    SensorModule,
    clear_registered_modules,
    register_module,
    registered_module_classes,
)
from .registry import ModuleRegistry

__all__ = [
    "ActuatorModule",
    "AgentModule",
    "DEFAULT_ENTRY_POINT_GROUP",
    "DeviceModule",
    "Kernel",
    "Module",
    "ModuleKind",
    "ModuleManifest",
    "ModuleRegistry",
    "PlatformContext",
    "ProviderModule",
    "SensorModule",
    "clear_registered_modules",
    "load_builtin_classes",
    "load_directory_classes",
    "load_entry_point_classes",
    "register_module",
    "registered_module_classes",
]