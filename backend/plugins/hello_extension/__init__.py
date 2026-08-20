"""示例插件：演示 BTG 插件平台的最小模块契约。

本包由内核的「目录双轨加载器」自动发现：它位于 ``backend/plugins`` 下，
通过 ``MODULES`` 导出要注册的模块类，不注册任何设备，仅展示契约写法。
"""
from __future__ import annotations

from btg.platform.manifest import ModuleKind, ModuleManifest
from btg.platform.module import Module


class HelloExtension(Module):
    """最小可插拔模块示例：仅回显一条健康信息。"""

    manifest = ModuleManifest(
        name="hello_extension",
        version="0.1.0",
        kind=ModuleKind.EXTENSION,
        description="演示插件平台最小模块契约的示例扩展。",
        capabilities=["echo"],
    )

    async def health(self) -> dict:
        base = await super().health()
        base["message"] = "hello from the plugins/ directory"
        return base


MODULES = [HelloExtension]