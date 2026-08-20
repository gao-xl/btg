"""剧情运行端：连接网关的下行/事件适配器。

剧情引擎通过三个注入协议与网关交互，这里提供真实网络实现：

- :class:`GatewayActuatorWriter` 复用现有 ``/api/v1/control/actuators`` 受控
  端点下发执行指令（story_id 映射到 ``scenario_id`` 溯源字段，走同一安全层）；
- 事件源与事件发布复用 :mod:`scenario_agent.client` 的 WebSocket 适配器。

运行依赖可选包 ``websockets``；未安装时仅在真正连接时报错，不影响导入。
"""
from __future__ import annotations

import json
from typing import Any
from urllib import error as urlerror
from urllib.request import Request, urlopen

from .models import StoryActuatorCommand


class GatewayActuatorWriter:
    """把剧情执行指令安全下发到网关执行器（复用现有受控端点）。"""

    def __init__(self, base_url: str, token: str, *, session_id: str, timeout_seconds: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session_id = session_id
        self.timeout_seconds = timeout_seconds

    async def send_actuator_command(self, command: StoryActuatorCommand, *, story_id: str, scene_id: str) -> None:
        payload = {
            "session_id": self.session_id,
            "source": "scenario_agent",
            "scenario_id": story_id,
            "scene_id": scene_id,
            "channel": command.channel,
            "actuator_id": command.actuator_id,
            "value": command.value,
            "unit": command.unit,
        }
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}/api/v1/control/actuators", body,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"gateway rejected story command with HTTP {response.status}")
        except urlerror.HTTPError as exc:
            raise RuntimeError(f"gateway rejected story command with HTTP {exc.code}") from exc
        except urlerror.URLError as exc:
            raise ConnectionError(f"cannot reach BTG gateway: {exc.reason}") from exc


def gateway_event_source(url: str, token: str, *, reconnect_delay_seconds: float = 1.0) -> Any:
    """构造可重连的遥测/STT 事件源（复用 scenario_agent 的 WebSocket 适配器）。"""
    from btg.agents.scenario_agent.client import GatewayWebSocketSource

    return GatewayWebSocketSource(url, token, reconnect_delay_seconds=reconnect_delay_seconds)


def gateway_event_sink(url: str, token: str) -> Any:
    """构造事件发布器（复用 scenario_agent 的 WebSocket 发布器）。"""
    from btg.agents.scenario_agent.client import WebSocketEventPublisher

    return WebSocketEventPublisher(url, token)


class ScriptedEventSource:
    """本地/测试用事件源：依次产出预置事件，尽处自然结束。"""

    def __init__(self, events) -> None:
        self._events = list(events)

    async def events(self):
        for event in self._events:
            yield dict(event)


def scripted_source(events) -> ScriptedEventSource:
    """构造一个按给定事件序列驱动的脚本事件源。"""
    return ScriptedEventSource(events)


__all__ = ["GatewayActuatorWriter", "gateway_event_source", "gateway_event_sink", "scripted_source"]