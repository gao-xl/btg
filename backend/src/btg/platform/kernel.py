"""平台内核：模块发现、实例化与生命周期编排。

``Kernel`` 是插件平台的唯一装配入口：它统一执行三种发现轨道，实例化模块，
并按 ``setup → start → stop`` 的顺序编排生命周期。网关（:mod:`btg.gateway`）
只依赖内核公开的发现结果，不再硬编码任何插件包路径。
"""
from __future__ import annotations

from typing import List

from .context import PlatformContext
from .loader import (
    DEFAULT_ENTRY_POINT_GROUP,
    dedupe,
    load_builtin_classes,
    load_directory_classes,
    load_entry_point_classes,
)
from .registry import ModuleRegistry


class Kernel:
    """插件平台内核。"""

    def __init__(self, context: PlatformContext, settings=None) -> None:
        self.context = context
        self.settings = settings
        self.registry = ModuleRegistry()
        self._disabled: set = set()

    def discover(self) -> "Kernel":
        """发现并实例化全部模块（同步：import 触发设备/平台类登记）。"""
        classes: list = []
        classes += load_builtin_classes()
        if self.settings is not None:
            group = getattr(self.settings, "plugin_entry_point_group", DEFAULT_ENTRY_POINT_GROUP)
            classes += load_entry_point_classes(group)
            classes += load_directory_classes(getattr(self.settings, "plugins_dir", None))
        for cls in dedupe(classes):
            self.registry.register(cls(self.context))
        return self

    # ------------------------------------------------------------------ #
    # 模块启停（功能开关）
    # ------------------------------------------------------------------ #
    def is_enabled(self, name: str) -> bool:
        """模块是否处于启用状态。"""
        return name not in self._disabled

    def set_enabled(self, name: str, enabled: bool) -> None:
        """仅更新启用标记（不触发生命周期，供启动前批量应用）。"""
        if enabled:
            self._disabled.discard(name)
        else:
            self._disabled.add(name)

    async def set_module_enabled(self, name: str, enabled: bool) -> bool:
        """启停单个模块（幂等）：启用走 setup→start，停用走 stop。

        Returns:
            bool: 模块存在且状态已按要求切换。
        """
        try:
            module = self.registry.get_by_name(name)
        except KeyError:
            return False
        if enabled:
            if self.is_enabled(name):
                return True
            self._disabled.discard(name)
            await module.setup()
            await module.start()
        else:
            if not self.is_enabled(name):
                return True
            self._disabled.add(name)
            await module.stop()
        return True

    async def setup(self) -> None:
        """依序调用全部启用模块的 ``setup``。"""
        for module in self.registry.all():
            if self.is_enabled(module.name):
                await module.setup()

    async def start(self) -> None:
        """依序启动全部启用模块。"""
        for module in self.registry.all():
            if self.is_enabled(module.name):
                await module.start()

    async def stop(self) -> None:
        """逆序停止全部启用模块。"""
        for module in reversed(self.registry.all()):
            if self.is_enabled(module.name):
                await module.stop()

    def snapshot(self) -> List[dict]:
        """返回已发现模块的元数据清单（供 REST 暴露）。"""
        return [
            {**module.describe(), "enabled": self.is_enabled(module.name)}
            for module in self.registry.all()
        ]