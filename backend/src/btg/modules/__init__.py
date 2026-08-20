"""BTG 内置插件模块包。

各子模块定义 :class:`btg.platform.module.Module` 实现，供平台内核发现与编排。
子模块不在此处聚合导入，由内核按需 import，以避免加载重量级可选依赖。
"""
from __future__ import annotations

__all__ = [
    "actuators",
    "agents",
    "mqtt_bridge",
    "persona",
    "providers",
    "replay",
    "sensors",
    "story",
    "workflow",
]