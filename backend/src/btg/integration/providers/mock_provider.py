"""开发/测试用第三方平台插件：记录收到的遥测/状态事件。"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

from btg_sdk import ThirdPartyProvider, register_provider


@register_provider("mock_provider")
class MockProvider(ThirdPartyProvider):
    """将推送事件追加到内存列表，供测试断言与本地联调。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.name = str(config.get("name", "mock_provider"))
        self.pushed: List[Dict[str, Any]] = []

    async def push_telemetry(self, data: dict) -> bool:
        self.pushed.append(dict(data))
        return True