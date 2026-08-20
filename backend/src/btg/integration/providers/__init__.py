"""第三方平台插件实现（Outbound 提供方）。

内置两类：``mock_provider``（开发/测试记录）与 ``http_webhook``（异步
HTTP POST 推送）。第三方可仿照注册自有平台插件，见 SDK 的
``@register_provider``。
"""
from . import http_webhook, mock_provider  # noqa: F401  (导入触发注册)

__all__ = ["http_webhook", "mock_provider"]