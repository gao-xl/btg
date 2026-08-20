"""WebSocket 遥测流：向客户端实时推送遥测读数与状态迁移。

网关通过 :class:`TelemetryHub` 向所有已连接客户端广播 JSON 消息；本模块
仅负责连接生命周期与消息下发，不感知具体数据来源（解耦于 HAL/融合层）。

消息约定（JSON 对象，均为完整事件快照）：
- 连接建立后先发送一次全量快照（``gateway.snapshot_state()``）；
- 之后按事件到达顺序推送 ``{"type": "telemetry", ...}`` 或
  ``{"type": "state_change", ...}``。

端点：
- ``/ws``：前端遥测面板使用的标准遥测流；
- ``/ws/events``：网关内代理（scenario_agent 等）订阅的归一化事件流，
  消息格式与 ``/ws`` 一致；
- ``/ws/events/publish``：代理回传生命周期/TTS 等事件，转发到事件总线
  （topic=``agent_event``）并广播给全部事件订阅者。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from btg.core.logging import get_logger

router = APIRouter()

logger = get_logger(__name__)


class TelemetryHub:
    """面向单事件循环的广播枢纽，维护一组客户端订阅队列。

    队列有界（``maxsize``），慢客户端不会无限堆积内存；客户端断开后由
    WebSocket 端点调用 :meth:`unsubscribe` 清理。
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self._maxsize = maxsize
        self._subscribers: Set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, message: Dict[str, Any]) -> None:
        """向所有订阅者广播一条消息（同步快速路径）。"""
        for queue in self._subscribers:
            queue.put_nowait(message)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """接受连接、发送初始快照并持续转发广播消息。"""
    await websocket.accept()
    gateway = websocket.app.state.gateway
    hub = gateway.telemetry_hub
    queue = hub.subscribe()
    try:
        await websocket.send_json(gateway.snapshot_state())
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(queue)


@router.websocket("/ws/events")
async def events_endpoint(websocket: WebSocket) -> None:
    """代理事件流：与 ``/ws`` 同源，供 scenario_agent 等订阅归一化事件。"""
    await websocket.accept()
    gateway = websocket.app.state.gateway
    hub = gateway.telemetry_hub
    queue = hub.subscribe()
    try:
        await websocket.send_json(gateway.snapshot_state())
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(queue)


@router.websocket("/ws/events/publish")
async def events_publish_endpoint(websocket: WebSocket) -> None:
    """接收代理回传事件：发布到事件总线并广播给全部事件订阅者。"""
    await websocket.accept()
    gateway = websocket.app.state.gateway
    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                continue
            gateway.telemetry_hub.publish(message)
            try:
                await gateway.event_bus.publish("agent_event", event=message)
            except Exception:  # noqa: BLE001 - 单条事件失败不终止回传连接
                logger.exception("agent_event 发布失败: %s", message.get("type"))
    except WebSocketDisconnect:
        pass


@router.websocket("/ws/heartbeat")
async def heartbeat_endpoint(websocket: WebSocket) -> None:
    """前端保活心跳：每收到一条消息即刷新分级安全闸的心跳时间戳。

    前端周期性发送任意消息（如 ``{"type": "heartbeat"}``）；一旦超时未刷新，
    分级安全闸将触发硬急停归零。连接建立即算一次心跳，避免握手间隙误触发。
    """
    await websocket.accept()
    gateway = websocket.app.state.gateway
    gateway.guardrail.feed_heartbeat()
    try:
        while True:
            message = await websocket.receive_json()
            gateway.guardrail.feed_heartbeat()
    except WebSocketDisconnect:
        pass