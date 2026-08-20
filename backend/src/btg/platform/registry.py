"""模块注册表：运行期收纳已实例化的插件模块。"""
from __future__ import annotations

from typing import Dict, List

from .module import Module


class ModuleRegistry:
    """按 (kind, name) 收纳模块实例。"""

    def __init__(self) -> None:
        self._modules: Dict[tuple, Module] = {}

    def register(self, module: Module) -> None:
        """登记模块实例；重复登记抛 :class:`ValueError`。"""
        key = (module.kind.value, module.name)
        if key in self._modules:
            raise ValueError(f"模块已存在: {module.kind.value}:{module.name}")
        self._modules[key] = module

    def get(self, kind: str, name: str) -> Module:
        """按 (kind, name) 返回模块实例。"""
        return self._modules[(kind, name)]

    def get_by_name(self, name: str) -> Module:
        """按名称返回模块实例（名称在平台内唯一，返回首个匹配）。"""
        for module in self._modules.values():
            if module.name == name:
                return module
        raise KeyError(name)

    def all(self) -> List[Module]:
        """返回全部模块实例。"""
        return list(self._modules.values())

    def of_kind(self, kind: str) -> List[Module]:
        """返回指定 kind 的模块实例。"""
        return [m for m in self._modules.values() if m.kind.value == kind]