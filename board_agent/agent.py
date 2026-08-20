"""板端薄代理：把本地采集/执行接入主机 MQTT 总线。

职责（薄，不做决策）：
- 周期采集各 ``SensorChannel`` → 批量 publish ``btg/{board_id}/telemetry``；
- 订阅 ``btg/{board_id}/command``，按 channel 映射到本地执行驱动并回 ACK；
- 周期 publish 心跳事件，便于主机侧健康监控；
- 断线自动重连（paho loop + 定时补传由上层可扩展）。

运行：``python -m board_agent.main --config config.yaml``
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from btg_sdk import Reading, transport

from .config import AgentConfig
from .drivers import BaseLocalActuator, BaseLocalSensor, build_drivers

logger = logging.getLogger("btg_agent")

try:
    import paho.mqtt.client as mqtt  # type: ignore
except ImportError:  # pragma: no cover - 可选依赖
    mqtt = None  # type: ignore[assignment]


class BoardAgent:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self._client: Any = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._command_queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self.sensors: Dict[str, BaseLocalSensor] = build_drivers(
            config.board_id, config.sensors, actuator=False
        )
        self.actuators: Dict[str, BaseLocalActuator] = build_drivers(
            config.board_id, config.actuators, actuator=True
        )

    # ------------------------------------------------------------------ #
    def _ensure_client(self) -> None:
        if mqtt is None:
            raise RuntimeError("未安装 paho-mqtt，请在板端 `pip install paho-mqtt`")
        if self._client is not None:
            return
        cfg = self.config.broker
        client = mqtt.Client(
            client_id=f"{cfg.client_id}-{self.config.board_id}",
            clean_session=True,
        )
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        if cfg.username:
            client.username_pw_set(cfg.username, cfg.password)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        self._client = client

    def _connect(self) -> None:
        cfg = self.config.broker
        logger.info("connecting %s:%s", cfg.host, cfg.port)
        self._client.connect(cfg.host, cfg.port, keepalive=30)
        self._client.loop_start()

    # ------------------------------------------------------------------ #
    # paho callbacks（运行在线程）
    # ------------------------------------------------------------------ #
    def _on_connect(self, client, userdata, flags, rc) -> None:  # type: ignore[no-untyped-def]
        if rc == 0:
            topic = transport.command_topic(self.config.board_id, self.config.broker.prefix)
            client.subscribe(topic, qos=1)
            logger.info("MQTT connected, subscribed %s", topic)
        else:
            logger.warning("MQTT connect failed rc=%s", rc)

    def _on_message(self, client, userdata, message) -> None:  # type: ignore[no-untyped-def]
        if self._loop is None:
            return
        try:
            cmd = transport.decode_command(message.payload)
        except Exception:  # noqa: BLE001
            logger.exception("命令解析失败")
            return
        self._loop.call_soon_threadsafe(self._command_queue.put_nowait, cmd)

    # ------------------------------------------------------------------ #
    # 协程
    # ------------------------------------------------------------------ #
    async def _telemetry_loop(self) -> None:
        while True:
            readings: List[Reading] = []
            for channel, sensor in self.sensors.items():
                r = sensor.read()
                if r is not None:
                    readings.append(r)
            if readings:
                payload = transport.encode_telemetry(self.config.board_id, readings)
                self._client.publish(
                    transport.telemetry_topic(
                        self.config.board_id, self.config.broker.prefix
                    ),
                    payload,
                    qos=1,
                )
            await asyncio.sleep(self._collect_interval())

    def _collect_interval(self) -> float:
        intervals = [s.interval for s in self.config.sensors]
        return min(intervals) if intervals else 1.0

    async def _command_loop(self) -> None:
        while True:
            cmd = await self._command_queue.get()
            action = cmd.get("action", "set")
            if action == "stop":
                for actuator in self.actuators.values():
                    actuator.stop()
                self._publish_ack(cmd, ok=True)
                continue
            actuator = self.actuators.get(cmd.get("channel"))
            if actuator is None:
                self._publish_ack(cmd, ok=False, error="unknown channel")
                continue
            ok = actuator.set_target(cmd.get("value"), cmd.get("unit", ""))
            self._publish_ack(cmd, ok=ok)

    def _publish_ack(self, cmd: Dict[str, Any], *, ok: bool, error: str = "") -> None:
        cfg = self.config.broker
        payload = transport.encode_ack(
            self.config.board_id, cmd.get("nonce", ""), ok=ok, error=error
        )
        self._client.publish(transport.ack_topic(self.config.board_id, cfg.prefix), payload)

    async def _heartbeat_loop(self) -> None:
        while True:
            payload = transport.encode_event(self.config.board_id, "heartbeat")
            self._client.publish(
                transport.event_topic(self.config.board_id, self.config.broker.prefix),
                payload,
                qos=1,
            )
            await asyncio.sleep(self.config.heartbeat_interval)

    # ------------------------------------------------------------------ #
    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._ensure_client()
        self._connect()
        tasks = [
            asyncio.create_task(self._telemetry_loop()),
            asyncio.create_task(self._command_loop()),
            asyncio.create_task(self._heartbeat_loop()),
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            for sensor in self.sensors.values():
                sensor.close()
            for actuator in self.actuators.values():
                actuator.close()
            if self._client is not None:
                self._client.loop_stop()
                self._client.disconnect()

    async def stop(self) -> None:
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for t in tasks:
            t.cancel()
        # 交由 run() 的 finally 收尾