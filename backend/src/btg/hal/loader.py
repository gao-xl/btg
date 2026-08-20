"""插件加载器：导入插件模块以触发 SDK 注册表登记。

第三方插件只需被 import 一次（其模块顶层的 ``@register_*`` 即生效），
本模块负责按包路径批量发现并导入子模块。
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Iterable


def discover_and_load(packages: Iterable[str]) -> None:
    """导入给定包及其子模块，触发插件 ``@register_*`` 注册。

    Args:
        packages: 包名列表（如 ``["btg.hal.sensors", "btg.hal.actuators"]``）。
    """
    for pkg_name in packages:
        pkg = importlib.import_module(pkg_name)
        for info in pkgutil.walk_packages(pkg.__path__, prefix=pkg_name + "."):
            importlib.import_module(info.name)


def load_builtin_plugins() -> None:
    """加载内置 mock 插件（开发/无硬件联调用）。"""
    discover_and_load(["btg.hal.sensors", "btg.hal.actuators"])