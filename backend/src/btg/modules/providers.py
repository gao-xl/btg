"""内置第三方平台（Outbound 提供方）模块。"""
from __future__ import annotations

from btg.platform.manifest import ModuleKind, ModuleManifest
from btg.platform.module import ProviderModule, register_module

# 导入平台实现，触发 @register_provider 登记。
from btg.integration.providers.mock_provider import MockProvider  # noqa: F401
from btg.integration.providers.http_webhook import HttpWebhookProvider  # noqa: F401


@register_module
class MockProviderModule(ProviderModule):
    """开发/测试用第三方平台插件（内存记录推送事件）。"""

    manifest = ModuleManifest(
        name="mock_provider",
        version="0.1.0",
        kind=ModuleKind.PROVIDER,
        description="将推送事件追加到内存列表，供测试断言与本地联调。",
        capabilities=["push_telemetry"],
    )
    plugin_names = ["mock_provider"]


@register_module
class HttpWebhookModule(ProviderModule):
    """通用 HTTP Webhook 第三方平台插件。"""

    manifest = ModuleManifest(
        name="http_webhook",
        version="0.1.0",
        kind=ModuleKind.PROVIDER,
        description="以 JSON POST 将遥测/状态事件推送到外部 Webhook。",
        capabilities=["push_telemetry"],
    )
    plugin_names = ["http_webhook"]