"""主机侧共享 MQTT 客户端：一个连接服务所有 ``mqtt_bridge`` 设备。

网关进程内可能配置多块开发板的远程传感器/执行器；它们共享同一 broker 连接，
避免每块板/每个通道各自开一条 TCP。本模块提供：
- 订阅 ``btg/+/telemetry``，按 (board_id, channel) 分发到各传感器队列；
- 供执行器向 ``btg/{board_id}/command`` 发布指令。

paho-mqtt 为可选依赖；未安装时操作抛出 :class:`RuntimeError`，由冗余层
触发本地备用设备接管，而非崩溃。callbacks 工作在线程，向 asyncio 队列投递
必须经 ``call_soon_threadsafe``。
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set, Tuple

from btg.core.logging import get_logger
from btg_sdk.transport import command_topic, decode_event, decode_telemetry

logger = get_logger(__name__)

try:
    import paho.mqtt.client as mqtt  # type: ignore
except ImportError:  # pragma: no cover - 可选依赖
    mqtt = None  # type: ignore[assignment]


@dataclass
class BoardStatus:
    """一块开发板的健康状态（由心跳事件驱动，离线由定时清扫兜底）。"""

    board_id: str
    online: bool = False
    first_seen: Optional[float] = None
    last_seen: Optional[float] = None
    offline_after: float = 15.0


class MqttBus:
    """进程内共享的 MQTT 客户端封装（单实例）。

    首次 ``start`` 前可多次 ``configure`` 覆盖 broker 参数；已启动后忽略
    后续参数差异，以保证统计一致。
    """

    def __init__(self) -> None:
        self._cfg: Dict[str, Any] = {
            "host": "127.0.0.1",
            "port": 1883,
            "username": None,
            "password": None,
            "prefix": "btg",
            "client_id": "btg-host",
            "offline_after": 15.0,
        }
        self._client = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._started = False
        self._sinks: Dict[Tuple[str, str], Set[asyncio.Queue]] = {}
        self._lock = threading.Lock()
        self._subscribed = False
        self._boards: Dict[str, BoardStatus] = {}
        self._sweeper_started = False

    def configure(self, **kwargs: Any) -> None:
        if self._started:
            return
        self._cfg.update({k: v for k, v in kwargs.items() if v is not None})

    def start(self) -> None:
        if self._started:
            return
        if mqtt is None:
            raise RuntimeError("未安装 paho-mqtt，请通过 `pip install \"btg-backend[mqtt]\"` 安装")
        client = mqtt.Client(client_id=f"{self._cfg['client_id']}-{uuid.uuid4().hex[:6]}")
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        username = self._cfg.get("username")
        if username:
            client.username_pw_set(username, self._cfg.get("password"))
        self._client = client
        client.connect(self._cfg["host"], int(self._cfg["port"]), keepalive=30)
        client.loop_start()
        self._started = True
        logger.info(
            "MQTT bus connected to %s:%s", self._cfg["host"], self._cfg["port"]
        )

    def subscribe_reading(self, board_id: str, channel: str) -> asyncio.Queue:
        """登记一个 (board_id, channel) 的遥测接收队列并启动总线。"""
        self.start()
        self._loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        key = (board_id, channel)
        with self._lock:
            self._sinks.setdefault(key, set()).add(queue)
            if self._client is not None and not self._subscribed:
                self._subscribe_defaults(self._client)
        self._register_board(board_id)
        self._ensure_sweeper()
        return queue

    def unsubscribe_reading(self, board_id: str, channel: str, queue: asyncio.Queue) -> None:
        with self._lock:
            key = (board_id, channel)
            sinks = self._sinks.get(key)
            if sinks:
                sinks.discard(queue)
                if not sinks:
                    self._sinks.pop(key, None)

    def publish_command(self, board_id: str, payload: str) -> bool:
        self.start()
        if self._client is None:
            return False
        topic = command_topic(board_id, self._cfg["prefix"])
        info = self._client.publish(topic, payload, qos=1)
        return info.rc == 0

    # ------------------------------------------------------------------ #
    # 开发板健康状态
    # ------------------------------------------------------------------ #
    def _register_board(self, board_id: str) -> None:
        with self._lock:
            self._boards.setdefault(
                board_id,
                BoardStatus(board_id=board_id, offline_after=self._cfg["offline_after"]),
            )

    def _touch_board(self, board_id: str, ts: float) -> None:
        with self._lock:
            status = self._boards.get(board_id)
            if status is None:
                status = BoardStatus(
                    board_id=board_id, offline_after=self._cfg["offline_after"]
                )
                self._boards[board_id] = status
            status.online = True
            status.first_seen = status.first_seen if status.first_seen else ts
            status.last_seen = ts

    def boards(self) -> Dict[str, Dict[str, Any]]:
        """快照所有已知开发板的健康状态（供 /api/v1/state 使用）。"""
        with self._lock:
            return {
                board_id: {
                    "online": status.online,
                    "first_seen": status.first_seen,
                    "last_seen": status.last_seen,
                }
                for board_id, status in sorted(self._boards.items())
            }

    def _ensure_sweeper(self) -> None:
        if self._sweeper_started or self._loop is None:
            return
        self._sweeper_started = True

        async def _sweep() -> None:
            while True:
                await asyncio.sleep(1.0)
                now = time.time()
                with self._lock:
                    for status in list(self._boards.values()):
                        if status.last_seen and now - status.last_seen > status.offline_after:
                            status.online = False

        self._loop.create_task(_sweep())

    # ------------------------------------------------------------------ #
    # 主题订阅
    # ------------------------------------------------------------------ #
    def _subscribe_defaults(self, client) -> None:
        prefix = self._cfg["prefix"]
        for suffix in ("telemetry", "event"):
            client.subscribe(f"{prefix}/+/{suffix}", qos=1)
        self._subscribed = True
        logger.info(
            "subscribed MQTT topics: %s", ", ".join(f"{prefix}/+/{s}" for s in ("telemetry", "event"))
        )

    # ------------------------------------------------------------------ #
    # paho callbacks（运行在线程）
    # ------------------------------------------------------------------ #
    def _on_connect(self, client, userdata, flags, rc) -> None:  # type: ignore[no-untyped-def]
        if rc == 0:
            logger.info("MQTT connected rc=%s", rc)
            self._subscribe_defaults(client)
        else:
            logger.warning("MQTT connect failed rc=%s", rc)

    def _on_message(self, client, userdata, message) -> None:  # type: ignore[no-untyped-def]
        try:
            topic = message.topic
            prefix = self._cfg["prefix"] + "/"
            if not topic.startswith(prefix):
                return
            board_id = topic[len(prefix):].split("/", 1)[0]
            suffix = topic.rsplit("/", 1)[-1]
        except Exception:  # noqa: BLE001
            return
        if suffix == "event":
            try:
                evt = decode_event(message.payload)
                if evt["kind"] == "heartbeat":
                    self._touch_board(board_id, evt["ts"])
            except Exception:  # noqa: BLE001 - 单条坏事件不影响总线
                logger.exception("MQTT event 解析失败: %s", message.topic)
        elif suffix == "telemetry":
            self._dispatch_telemetry(board_id, message.payload)

    def _dispatch_telemetry(self, board_id: str, payload: bytes) -> None:
        try:
            _board, readings = decode_telemetry(payload)
            if _board != board_id:
                return
        except Exception:  # noqa: BLE001 - 单条坏消息不影响总线
            logger.exception("MQTT telemetry 解析失败")
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        for reading in readings:
            sinks = self._sinks.get((board_id, reading.channel))
            if not sinks:
                continue
            for queue in list(sinks):
                loop.call_soon_threadsafe(queue.put_nowait, reading)

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def stop(self) -> None:
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:  # noqa: BLE001 - 释放路径尽力而为
                logger.exception("MQTT bus stop error")
        self._client = None
        self._started = False
        self._subscribed = False


_BUS: Optional[MqttBus] = None


def get_mqtt_bus() -> MqttBus:
    global _BUS
    if _BUS is None:
        _BUS = MqttBus()
    return _BUS


def reset_mqtt_bus() -> None:
    global _BUS
    _BUS = None