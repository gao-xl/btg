"""双轨道插件加载器：内置模块 + pip 入口点 + 运行时插件目录。

- 轨道 1（内置）：导入 ``btg.modules.*``，触发 ``@register_module`` 登记；
- 轨道 2（分发）：读取 ``importlib.metadata`` 中 ``btg.plugins`` 入口点；
- 轨道 3（开发/热插拔）：扫描 ``plugins/`` 目录下的独立插件包。
"""
from __future__ import annotations

import importlib
import importlib.metadata
import logging
import pkgutil
import sys
from pathlib import Path
from typing import Iterable, List, Type

from .module import Module, registered_module_classes

LOGGER = logging.getLogger(__name__)

_BUILTIN_PACKAGES = [
    "btg.modules.sensors",
    "btg.modules.actuators",
    "btg.modules.providers",
    "btg.modules.agents",
    "btg.modules.story",
    "btg.modules.workflow",
    "btg.modules.persona",
    "btg.modules.replay",
]

DEFAULT_ENTRY_POINT_GROUP = "btg.plugins"


def dedupe(classes: Iterable[Type[Module]]) -> List[Type[Module]]:
    """按 (kind, name) 去重并保持首次出现顺序。"""
    seen: dict = {}
    for cls in classes:
        seen[(cls.manifest.kind.value, cls.manifest.name)] = cls
    return list(seen.values())


def load_builtin_classes() -> List[Type[Module]]:
    """导入内置模块包，返回装饰器登记的模块类。

    规划中尚未实现的内置包（如未来模块占位）会被跳过并记录告警，
    不阻断内核发现，避免单个缺失阻断整个网关启动。
    """
    for pkg in _BUILTIN_PACKAGES:
        try:
            importlib.import_module(pkg)
        except ModuleNotFoundError as exc:
            if exc.name != pkg:
                raise
            LOGGER.warning("跳过缺失的内置模块包: %s", pkg)
    return registered_module_classes()


def load_entry_point_classes(group: str = DEFAULT_ENTRY_POINT_GROUP) -> List[Type[Module]]:
    """从 ``importlib.metadata`` 入口点装载模块类。

    每个入口点解析结果可为：单个 ``Module`` 子类、``Module`` 子类列表、
    或 ``Module`` 实例列表。
    """
    classes: List[Type[Module]] = []
    eps = importlib.metadata.entry_points()
    selected = eps.select(group=group) if hasattr(eps, "select") else eps.get(group, [])
    for ep in selected:
        classes.extend(_coerce(ep.load()))
    return classes


def load_directory_classes(directory) -> List[Type[Module]]:
    """从运行期插件目录装载模块类。

    目录下每个顶层包被 import；包可用 ``MODULES`` 显式声明模块类，否则
    自动扫描包内定义的 ``Module`` 子类。
    """
    dir_path = Path(directory)
    if not dir_path.is_dir():
        return []
    if str(dir_path) not in sys.path:
        sys.path.insert(0, str(dir_path))

    classes: List[Type[Module]] = []
    for info in pkgutil.iter_modules([str(dir_path)]):
        mod = importlib.import_module(info.name)
        classes.extend(_collect_from_module(mod))
    return classes


def _coerce(obj) -> List[Type[Module]]:
    """将入口点解析结果规整为模块类列表。"""
    if isinstance(obj, type) and issubclass(obj, Module):
        return [obj]
    if isinstance(obj, (list, tuple)):
        return [x for x in obj if isinstance(x, type) and issubclass(x, Module)]
    if isinstance(obj, Module):
        return [type(obj)]
    return []


def _collect_from_module(mod) -> List[Type[Module]]:
    declared = getattr(mod, "MODULES", None)
    if declared is not None:
        return _coerce(declared)
    return [
        obj
        for obj in vars(mod).values()
        if isinstance(obj, type)
        and issubclass(obj, Module)
        and obj is not Module
        and getattr(obj, "__module__", "") == mod.__name__
    ]