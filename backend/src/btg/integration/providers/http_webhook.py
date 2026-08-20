"""通用 HTTP Webhook 第三方平台插件：异步 POST 遥测/状态事件。

配置项：
- ``url``（必填）：目标 Webhook 地址。
- ``headers``：可选附加请求头字典。
- ``timeout``：单次请求超时（秒），默认 5.0。

网络失败返回 False 并记录日志，由 ``IntegrationManager`` 隔离，不阻断
主流程；可自行扩展为重试/排队语义。
"""
from __future__ import annotations

import logging
from typing import Any, Mapping

from btg_sdk import ThirdPartyProvider, register_provider

logger = logging.getLogger(__name__)


@register_provider("http_webhook")
class HttpWebhookProvider(ThirdPartyProvider):
    """以 JSON 后段 POST 将事件推送到外部 Webhook。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.url = str(config["url"])
        self.headers = {str(k): str(v) for k, v in dict(config.get("headers", {})).items()}
        self.timeout = float(config.get("timeout", 5.0))
        self._client: Any = None

    async def _get_client(self) -> Any:
        if self._client is None:
            import httpx  # 延迟导入，允许无网络环境下加载插件
            self._client = httpx.AsyncClient(timeout=self.timeout, headers=self.headers)
        return self._client

    async def push_telemetry(self, data: dict) -> bool:
        client = await self._get_client()
        try:
            response = await client.post(self.url, json=data)
        except Exception:  # noqa: BLE001
            logger.exception("Webhook 推送失败 url=%s", self.url)
            return False
        ok = response.status_code < 400
        if not ok:
            logger.warning("Webhook 返回非成功状态 url=%s status=%s", self.url, response.status_code)
        return ok

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None