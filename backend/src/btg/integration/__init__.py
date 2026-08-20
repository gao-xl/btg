"""BTG 第三方接入层：Inbound 控制与 Outbound Webhook 推送。

- Outbound：:class:`btg.integration.manager.IntegrationManager` 订阅事件总线，
  将遥测与状态迁移转发给已注册的 :class:`btg_sdk.ThirdPartyProvider` 插件。
- Inbound：`POST /integration/v1/control` 接收第三方控制指令，转入内部安全
  管道（与 REST 手动指令、融合引擎共用同一条下发路径）。
"""
from .control_routes import router
from .manager import IntegrationManager

__all__ = ["IntegrationManager", "router"]