"""YoKoNex（役次元）异步回馈与状态监听适配器。

本模块通过 YoKoNex 的本地 "API-bridge"（IM 桥接服务，默认
``http://127.0.0.1:3001``）实时同步设备运行状态与遥测数据，并把归一化后的
结果转成系统的标准 :class:`ActuatorTelemetryFrame`，再桥接为现有反馈管线
使用的 :class:`DeviceFeedback`（电量 / 连接状态），从而：

- 前端仪表盘据 ``CONNECTION`` 反馈的 ``value`` 自动置灰/点亮设备；
- 融合引擎与安全规则订阅 ``device_feedback`` 事件，超时或离线触发安全告警。

真实桥接说明
------------
YoKoNex API-bridge 的 ``GET /api/status`` 与 ``/health`` 只暴露 IM 会话状态
（``isReady`` / ``config``），并不直接携带设备级 ``device_id`` /
``is_online`` / ``battery`` / ``state_payload``。设备状态实际经 WebSocket
``type:"message"`` 推送，其 ``data.messages[].payload.text`` 是内嵌
``code / id / payload`` 的 JSON 字符串。因此本模块把归一化（normalizer）设计成
**容错抽取**：能从真实 IM 载荷 / HTTP 状态中尽量提取上述字段，缺省字段安全
回退，而不是假设桥接必然返回理想字段。

两种事件源模式（``mode`` 配置）：

- ``poll``（默认）：周期 ``GET <bridge_url>/<poll_endpoint>``，适用于桥接提供
  静态状态端点或自建返回归一状态的轻量网关；
- ``websocket``：实时订阅桥接推送，自动重连、指数退避。

网络异常与断连保护：连续失败/离线达到 ``offline_alert_threshold`` 即回调
``on_alert`` 并发出离线反馈；轮询用指数退避，恢复后自愈。
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field as dc_field
from typing import Any, Literal, Optional
from urllib.parse import urlsplit

from btg_sdk import DeviceFeedback, FeedbackKind
from pydantic import (
    AnyHttpUrl,
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 统一遥测帧（规范化契约）
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ActuatorTelemetryFrame:
    """归一化后的执行器状态遥测帧（来源无关的统一契约）。

    Attributes:
        device_id: 设备唯一标识（尽量来自桥接，缺失时回退配置）。
        is_online: 设备在线状态。
        battery: 电量百分比 0--100，未知为 None。
        state_payload: 与设备类型相关的具体执行状态（如智能锁开/锁、
            电铲/电玩设备的强度或位置进度）。
        source: 本次数据来源（``poll`` 或 ``websocket``）。
        timestamp: 遥测时间戳（Unix epoch 秒）。
        extra: 扩展键值对（含原始载荷摘要等）。
    """

    device_id: str
    is_online: bool
    battery: Optional[int] = None
    state_payload: dict[str, Any] = dc_field(default_factory=dict)
    source: str = "unknown"
    timestamp: float = dc_field(default_factory=time.time)
    extra: dict[str, Any] = dc_field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """返回可直接 JSON 序列化的字典。"""
        return {
            "device_id": self.device_id,
            "is_online": self.is_online,
            "battery": self.battery,
            "state_payload": self.state_payload,
            "source": self.source,
            "timestamp": self.timestamp,
            "extra": dict(self.extra),
        }

    def to_device_feedback(self) -> list[DeviceFeedback]:
        """把遥测帧拆成现有反馈管线所需的 ``DeviceFeedback``。

        - 每帧产出一条 ``CONNECTION``（在线 1.0 / 离线 0.0），供健康度置灰；
        - 若带电量，额外产出一条 ``BATTERY``。
        """
        feedback: list[DeviceFeedback] = [
            DeviceFeedback(
                device_id=self.device_id,
                kind=FeedbackKind.CONNECTION,
                channel=self.extra.get("channel", ""),
                value=1.0 if self.is_online else 0.0,
                unit="bool",
                message="device online" if self.is_online else "device offline",
                timestamp=self.timestamp,
            )
        ]
        if self.battery is not None:
            feedback.append(
                DeviceFeedback(
                    device_id=self.device_id,
                    kind=FeedbackKind.BATTERY,
                    channel=self.extra.get("channel", ""),
                    value=self.battery / 100.0,
                    unit="%",
                    message="battery",
                    timestamp=self.timestamp,
                    extra={"battery_percent": self.battery},
                )
            )
        return feedback


# --------------------------------------------------------------------------- #
# 配置边界
# --------------------------------------------------------------------------- #
_SOURCE_MODES = ("poll", "websocket")


class YoKoNexFeedbackConfig(BaseModel):
    """YoKoNex 回馈适配器的严格配置边界。"""

    model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(default="yokonex_im", min_length=1)
    channel: str = Field(default="")
    mode: Literal["poll", "websocket"] = "poll"

    bridge_url: AnyHttpUrl = "http://127.0.0.1:3001"
    poll_endpoint: str = Field(default="/api/status", min_length=1, max_length=200)
    poll_interval_seconds: float = Field(default=5.0, gt=0.0, le=600.0)
    timeout_seconds: float = Field(default=5.0, gt=0.0, le=30.0)
    allow_remote_bridge: bool = False
    ws_url: AnyUrl | None = None

    # 断连保护
    max_retries: int = Field(default=3, ge=1, le=60)
    backoff_base_seconds: float = Field(default=1.0, gt=0.0)
    offline_alert_threshold: int = Field(default=3, ge=1, le=3600)

    # 兜底设备标识：桥接无法给出 device_id 时使用
    device_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_bridge(self) -> "YoKoNexFeedbackConfig":
        parsed = urlsplit(str(self.bridge_url))
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("bridge_url must not contain credentials, a query, or a fragment")
        if parsed.path not in ("", "/"):
            raise ValueError("bridge_url must be an origin without an API path")
        is_loopback = _is_loopback_host(parsed.hostname or "")
        if not self.allow_remote_bridge and not is_loopback:
            raise ValueError(
                "remote API-bridge is disabled because its bridge has no authentication; "
                "set allow_remote_bridge=true only behind a trusted tunnel"
            )
        return self

    @property
    def resolved_ws_url(self) -> str:
        """从 ``ws_url`` 或 ``bridge_url`` 推导 WebSocket 地址。"""
        if self.ws_url is not None:
            return str(self.ws_url)
        base = str(self.bridge_url)
        return base.replace("http://", "ws://", 1).replace("https://", "wss://", 1)

    @property
    def resolved_poll_url(self) -> str:
        origin = str(self.bridge_url).rstrip("/")
        endpoint = self.poll_endpoint
        if endpoint.startswith("/"):
            return origin + endpoint
        return origin + "/" + endpoint


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# 容错归一化（从真实桥接载荷抽取标准字段）
# --------------------------------------------------------------------------- #
class YokoNexStatusNormalizer:
    """把桥接返回的任意 JSON 载荷尽量映射为标准 :class:`ActuatorTelemetryFrame`。

    字段抽取是容错且带回退的：优先目标字段名（如 ``is_online``、``battery``），
    兼收别名（``online``、``battery_percent``、``power``），并从 IM 消息结构
    中提取嵌套 ``payload``。缺失字段安全回退，不抛异常。
    """

    _ONLINE_KEYS = ("is_online", "online", "connected", "isOnline")
    _BATTERY_KEYS = ("battery", "battery_percent", "power", "batteryLevel")

    def normalize(
        self,
        raw: Mapping[str, Any],
        *,
        source: str,
        device_fallback: str,
        channel: str = "",
        now: float | None = None,
    ) -> ActuatorTelemetryFrame:
        ts = now if now is not None else time.time()
        head = self._head(raw)  # 剥离 IM 外层包装，得到真正"业务"载荷
        # 设备标识可能在"身份证"层（内嵌 JSON 的 {code, id, payload}），
        # 与最内层 status 分离，故用独立、可穿越 JSON 字符串的搜索单独抽取。
        device_id = self._first_str(head, "device_id", "deviceId", "uid", "id")
        if not device_id:
            device_id = self._find_identity(raw)
        if not device_id:
            device_id = device_fallback or f"{device_fallback}:unknown"
        # 在线：显式字段优先；收到 message/心跳且网络 CONNECTED 也视为在线。
        is_online = self._first_bool(
            head, "is_online", "online", "connected", "isOnline", "is_ready", "isReady"
        )
        if is_online is None:
            is_online = self._infer_online(head)
        battery = self._first_battery(head)
        payload = self._first_dict(head, "state_payload", "statePayload", "payload", "data")
        return ActuatorTelemetryFrame(
            device_id=device_id,
            is_online=bool(is_online),
            battery=battery,
            state_payload=payload,
            source=source,
            timestamp=ts,
            extra={"channel": channel, "raw": self._digest(raw)},
        )

    # ---- 内部抽取工具 -------------------------------------------------------- #
    @staticmethod
    def _digest(raw: Mapping[str, Any]) -> dict[str, Any]:
        """安全地把原始载荷转成可 JSON 的摘要（失败则给类型标记）。"""
        try:
            return dict(raw)
        except (TypeError, ValueError):
            return {"type": type(raw).__name__}

    @classmethod
    def _head(cls, raw: Mapping[str, Any]) -> dict[str, Any]:
        """剥离 IM 外层包装，定位到最内层的业务载荷。

        可穿越：``data / payload / message`` 映射、``messages[]`` 数组，以及
        承载内嵌 JSON 字符串的 ``payload.text``，从而在每个包裹层级都能往下钻。
        """
        current: Mapping[str, Any] = raw
        for _ in range(6):
            candidate = cls._payload_text(current)
            if candidate is None:
                return dict(current)
            if isinstance(candidate, str):
                parsed = cls._try_json(candidate)
                if parsed is not None:
                    current = parsed
                else:
                    return dict(current)
            elif isinstance(candidate, Mapping):
                current = candidate
            else:
                break
        return dict(current)

    @classmethod
    def _payload_text(cls, value: Mapping[str, Any]) -> Any:
        """返回下一个应下钻的包裹内容（映射或 JSON 字符串），否则 None。"""
        for key in ("data", "payload", "message"):
            child = value.get(key)
            if isinstance(child, Mapping):
                return child
        direct = value.get("payload")
        if isinstance(direct, str) and direct.strip():
            return direct
        for mkey in ("messages", "message"):
            items = value.get(mkey)
            if isinstance(items, list):
                for msg in items:
                    if isinstance(msg, Mapping):
                        inner = msg.get("payload")
                        if isinstance(inner, Mapping):
                            text = inner.get("text")
                            return text if isinstance(text, str) and text.strip() else inner
                        if isinstance(inner, str) and inner.strip():
                            return inner
                        text = msg.get("text")
                        if isinstance(text, str) and text.strip():
                            return text
                        return msg
        text = value.get("text")
        if isinstance(text, str) and text.strip().lstrip().startswith(("{", "[")):
            return text
        return None

    @classmethod
    def _find_identity(cls, root: Mapping[str, Any], *, depth: int = 6) -> str | None:
        """有界深度地穿越嵌套映射与内嵌 JSON 字符串，寻找设备标识。

        命中 ``device_id / deviceId / uid / id`` 中第一个非空字符串。用于 IM
        桥接包裹较深、身份与状态分居两层的场景；找不到返回 None。
        """
        if depth <= 0:
            return None
        for name in ("device_id", "deviceId", "uid", "id"):
            value = root.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key, value in root.items():
            if isinstance(value, str):
                parsed = cls._try_json(value)
                if parsed is not None:
                    found = cls._find_identity(parsed, depth=depth - 1)
                    if found:
                        return found
            elif isinstance(value, Mapping):
                # 自我引用很小，但用 depth 兜底防止递归失控。
                if value is root:
                    continue
                found = cls._find_identity(value, depth=depth - 1)
                if found:
                    return found
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, Mapping):
                        found = cls._find_identity(item, depth=depth - 1)
                        if found:
                            return found
        return None

    @classmethod
    def _infer_online(cls, head: Mapping[str, Any]) -> bool:
        network = head.get("network")
        if isinstance(network, Mapping):
            state = str(network.get("state", "")).upper()
            if state == "CONNECTED":
                return True
            if state.startswith("DISCONNECT"):
                return False
        if head.get("type") == "message" or head.get("type") == "heartbeat":
            return True
        return True  # 收到任何业务载荷即默认在线（离线由轮询失败/置灰处理）

    @classmethod
    def _first_str(cls, head: Mapping[str, Any], *names: str) -> str | None:
        for name in names:
            value = head.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @classmethod
    def _first_bool(cls, head: Mapping[str, Any], *names: str) -> bool | None:
        for name in names:
            value = head.get(name)
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)) and value in (0, 1):
                return bool(value)
            if isinstance(value, str):
                lowered = value.lower()
                if lowered in {"true", "yes", "online", "connected", "ready"}:
                    return True
                if lowered in {"false", "no", "offline", "disconnected"}:
                    return False
        return None

    @classmethod
    def _first_battery(cls, head: Mapping[str, Any]) -> int | None:
        for name in cls._BATTERY_KEYS:
            value = head.get(name)
            if value is None or isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                return max(0, min(100, int(round(float(value)))))
            if isinstance(value, str):
                try:
                    numeric = float(value.strip().rstrip("%"))
                except (TypeError, ValueError):
                    continue
                if math.isfinite(numeric):
                    return max(0, min(100, int(round(numeric))))
        return None

    @classmethod
    def _first_dict(cls, head: Mapping[str, Any], *names: str) -> dict[str, Any]:
        for name in names:
            value = head.get(name)
            if isinstance(value, Mapping):
                return dict(value)
        return {}

    @staticmethod
    def _try_json(text: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None


# --------------------------------------------------------------------------- #
# 适配器主类
# --------------------------------------------------------------------------- #
AsyncSink = Callable[[ActuatorTelemetryFrame], Awaitable[None]]
AsyncAlert = Callable[[str, ActuatorTelemetryFrame], Awaitable[None]]


class YoKoNexFeedbackAdapter:
    """异步回馈与状态监听适配器（轮询或 WebSocket 桥接）。

    用法（接入网关 feedback 管线）：

        adapter = YoKoNexFeedbackAdapter(
            YoKoNexFeedbackConfig(mode="websocket", channel="tens"),
            sink=lambda frame: gateway.feedback_collector 的事件/记录,
            on_alert=_trigger_safety_alert,
        )
        await adapter.start()

    ``sink`` 收到的是归一化遥测帧；模块同时提供
    :meth:`ActuatorTelemetryFrame.to_device_feedback`，把帧转成现有
    ``DeviceFeedback`` 供聚合器 / 事件总线 / 融合引擎消费。
    """

    def __init__(
        self,
        config: YoKoNexFeedbackConfig | Mapping[str, Any],
        *,
        sink: AsyncSink | None = None,
        on_alert: AsyncAlert | None = None,
        transport: Any = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = (
            config if isinstance(config, YoKoNexFeedbackConfig)
            else YoKoNexFeedbackConfig.model_validate(dict(config))
        )
        self._sink = sink
        self._on_alert = on_alert
        self._transport = transport
        self._clock = clock
        self._normalizer = YokoNexStatusNormalizer()
        self._client: Any | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._started = False
        # 健康与断连保护状态
        self.consecutive_failures = 0
        self.alerted = False
        self.last_frame: ActuatorTelemetryFrame | None = None

    @property
    def device_id(self) -> str:
        return self.config.device_id or f"{self.config.instance_id}"

    async def start(self) -> None:
        """启动监听或轮询后台任务（幂等）。"""
        async with self._lock:
            if self._started:
                return
            if self.config.mode == "websocket":
                await self._ensure_websockets_available()
                self._task = asyncio.create_task(self._run_websocket_loop())
            else:
                self._task = asyncio.create_task(self._run_poll_loop())
            self._started = True
            LOGGER.info("%s YoKoNex feedback adapter started (%s)", self.device_id, self.config.mode)

    async def stop(self) -> None:
        """停止后台任务并释放连接（幂等）。"""
        async with self._lock:
            if self._task is not None:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None
            await self._close_client()
            self._started = False

    # ---- 事件源：轮询 ------------------------------------------------------- #
    async def _run_poll_loop(self) -> None:
        backoff = self.config.backoff_base_seconds
        while True:
            try:
                frame = await self.poll_once()
                await self._handle_state(frame)
                backoff = self.config.backoff_base_seconds
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("%s YoKoNex poll failed: %s", self.device_id, exc)
                await self._note_failure("bridge_timeout")
                backoff = min(backoff * 2, self.config.backoff_base_seconds * 8)
            await asyncio.sleep(
                self.config.poll_interval_seconds
                if self.consecutive_failures == 0
                else backoff
            )

    async def poll_once(self) -> ActuatorTelemetryFrame:
        """发起一次 HTTP 状态请求并归一化（供手动/测试）。"""
        client = await self._get_client()
        response = await client.get(self.config.resolved_poll_url)
        response.raise_for_status()
        frame = self._normalizer.normalize(
            response.json(),
            source="poll",
            device_fallback=self.device_id,
            channel=self.config.channel,
            now=self._clock(),
        )
        self.last_frame = frame
        return frame

    # ---- 事件源：WebSocket ---- -------------------------------------------- #
    async def _run_websocket_loop(self) -> None:
        import websockets

        backoff = self.config.backoff_base_seconds
        url = self.config.resolved_ws_url
        while True:
            try:
                async with websockets.connect(url, ping_interval=self.config.poll_interval_seconds) as ws:
                    self._reset_failures()
                    async for raw in ws:
                        await self._handle_ws_message(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("%s YoKoNex WebSocket disconnected: %s", self.device_id, exc)
                await self._note_failure("bridge_disconnected")
                backoff = min(backoff * 2, self.config.backoff_base_seconds * 8)
            await asyncio.sleep(backoff)

    async def _handle_ws_message(self, raw: Any) -> None:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if isinstance(raw, Mapping):
                message = raw
            else:
                message = json.loads(raw)
        except (TypeError, ValueError):
            LOGGER.debug("%s dropped non-JSON WS message", self.device_id)
            return
        if not isinstance(message, Mapping):
            return
        if message.get("type") in {"error"}:
            LOGGER.warning("%s YoKoNex WS error: %s", self.device_id, message.get("message"))
            return
        try:
            frame = self._normalizer.normalize(
                message,
                source="websocket",
                device_fallback=self.device_id,
                channel=self.config.channel,
                now=self._clock(),
            )
        except Exception:  # noqa: BLE001
            LOGGER.exception("%s failed to normalize YoKoNex WS payload", self.device_id)
            return
        self.last_frame = frame
        # 显式离线也按断连处理（置灰 + 告警），但保持 WS 连接继续监听后续消息。
        if not frame.is_online:
            await self._note_failure("device_offline")
        else:
            await self._handle_state(frame)

    # ---- 分发 / 断连保护 ---------------------------------------------------- #
    async def _handle_state(self, frame: ActuatorTelemetryFrame) -> None:
        """设备的健康事件源：在线即恢复正常并广播；离线走断连保护。"""
        self.last_frame = frame
        if frame.is_online:
            self._reset_failures()
            await self._emit(frame)
            return
        await self._note_failure("device_offline")

    async def _emit(self, frame: ActuatorTelemetryFrame) -> None:
        if self._sink is not None:
            try:
                await self._sink(frame)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                LOGGER.exception("%s feedback sink error device=%s", self.device_id, frame.device_id)

    async def _note_failure(self, reason: str) -> None:
        """记录一次失败：下发离线帧置灰；首次达到阈值时触发安全告警。"""
        self.consecutive_failures += 1
        offline_frame = ActuatorTelemetryFrame(
            device_id=self.device_id,
            is_online=False,
            source=self.config.mode,
            timestamp=self._clock(),
            extra={"channel": self.config.channel, "reason": reason},
        )
        self.last_frame = offline_frame
        await self._emit(offline_frame)
        if self.consecutive_failures >= self.config.offline_alert_threshold and not self.alerted:
            self.alerted = True
            await self._fire_alert(reason, offline_frame)
        else:
            LOGGER.warning(
                "%s YoKoNex consecutive failures=%d (threshold=%d)",
                self.device_id, self.consecutive_failures, self.config.offline_alert_threshold,
            )

    def _reset_failures(self) -> None:
        self.consecutive_failures = 0
        self.alerted = False

    async def _fire_alert_maybe(self, frame: ActuatorTelemetryFrame, reconnect: float) -> None:
        # 退避重试期间仍失败才真正告警，避免抖动误报。
        if self.consecutive_failures >= self.config.offline_alert_threshold:
            await self._fire_alert("bridge_retry_failed", frame)

    async def _fire_alert(self, reason: str, frame: ActuatorTelemetryFrame) -> None:
        if self._on_alert is not None:
            try:
                await self._on_alert(reason, frame)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                LOGGER.exception("%s alert callback error reason=%s", self.device_id, reason)
        LOGGER.warning("%s YoKoNex safety alert raised: %s", self.device_id, reason)

    # ---- 基础设施 ----------------------------------------------------------- #
    async def _get_client(self) -> Any:
        if self._client is None:
            import httpx

            kwargs: dict[str, Any] = {"timeout": self.config.timeout_seconds}
            if self._transport is not None:
                kwargs["transport"] = self._transport
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def _close_client(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.aclose()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                LOGGER.debug("YoKoNex HTTP client close failed", exc_info=True)

    async def _ensure_websockets_available(self) -> None:
        try:
            import websockets  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise RuntimeError(
                "websocket mode requires the 'websockets' package "
                "(declared in btg-backend dependencies)"
            ) from exc


class _DeviceOfflineError(Exception):
    """桥接正常响应但设备处于离线状态。"""

    def __init__(self, frame: ActuatorTelemetryFrame) -> None:
        super().__init__(f"device offline: {frame.device_id}")
        self.frame = frame


__all__ = [
    "ActuatorTelemetryFrame",
    "YoKoNexFeedbackConfig",
    "YoKoNexStatusNormalizer",
    "YoKoNexFeedbackAdapter",
]