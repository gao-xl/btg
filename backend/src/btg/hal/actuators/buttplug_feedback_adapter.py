"""Buttplug.io 生态的设备反馈与能力同步适配器。

与 :mod:`btg.hal.actuators.buttplug_bridge`（下行指令桥）分工不同，本模块
专注 **上行反馈**：

- 捕获设备接入事件，解析并缓存其**能力矩阵**（振动/往复/旋转、通道数、
  档位数、电量查询是否可用）；
- 定期**异步轮询电量**（``device.battery()``），对廉价不支持电量的玩具
  施加超时保护；
- 监听设备移除与服务器断连，**看门狗**式触发网关安全回调，避免链路丢失
  后网关继续下发/误判健康；
- 将遥测与状态打包为统一的 :class:`ActuatorTelemetryFrame`，供融合引擎 /
  反馈聚合器消费（并可与既有 ``ActuatorStatusFrame`` / ``DeviceFeedback``
  互转）。

设计原则：
- Python 3.10+ ``asyncio``，所有 Buttplug I/O 均为异步且带独立超时；
- 任何单台设备/单个能力查询失败**只记录日志降级**，严禁导致网关崩溃；
- ``buttplug`` 采用惰性导入，未安装该可选依赖时模块仍可被导入与测试，
  直到真正调用连接时才抛出带安装提示的异常。

协议状态 == 物理安全：一旦服务器断开或设备移除，本适配器必须立刻触发
``on_disconnect`` 安全回调（默认由调用方注入，负责停机/降级），而非静默。
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from btg_sdk import DeviceFeedback, FeedbackKind
from pydantic import AnyUrl, BaseModel, ConfigDict, Field

try:  # 惰性导入：缺依赖时仅记录，调用时给出安装提示。
    from buttplug import ButtplugClient, InputType, OutputType
except ImportError as exc:  # pragma: no cover - 取决于部署 extra
    ButtplugClient = InputType = OutputType = None  # type: ignore[assignment,misc]
    _BUTTPLUG_IMPORT_ERROR: Optional[ImportError] = exc
else:
    _BUTTPLUG_IMPORT_ERROR = None

logger = logging.getLogger(__name__)

# Buttplug 规范输出能力名（OutputType 枚举名）。
_OUTPUT_CAPABILITIES = (
    "VIBRATE", "LINEAR", "ROTATE", "OSCILLATE", "CONSTANT", "PULSE",
)
# Buttplug 规范输入能力名（InputType 枚举名）。
_INPUT_CAPABILITIES = (
    "BATTERY", "RSSI", "PRESSURE", "ACCELEROMETER", "RAW_ACCELEROMETER", "KIDNEY_STIMULATOR",
)

_DEFAULT_BATTERY_TIMEOUT = 3.0


# ── 统一遥测帧 ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ButtplugCapability:
    """Buttplug 设备单项能力（能力矩阵中的一个条目）。

    Attributes:
        name: 能力名（如 ``"VIBRATE"``）。
        supported: 是否受支持。
        channels: 通道/特征数（多个马达各自独立计数）。
        step_count: 可调度档位数（None 表示未知或不适用）。
        value_range: 数值区间 (min, max)，None 表示未知。
        kind: ``"output"`` 或 ``"input"``。
    """

    name: str
    supported: bool
    channels: int = 0
    step_count: Optional[int] = None
    value_range: Optional[tuple[float, float]] = None
    kind: str = "output"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "supported": self.supported,
            "channels": self.channels,
            "step_count": self.step_count,
            "value_range": self.value_range,
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class ActuatorTelemetryFrame:
    """Buttplug 设备上行遥测/状态统一帧。

    上报给融合引擎（Fusion Engine）与反馈聚合器的标准结构。建立在
    ``DeviceFeedback`` 的连接/电量基础信息之上，额外承载能力矩阵
    （``capabilities``）与厂商扩展（``vendor_meta``）。

    Attributes:
        device_id: 设备标识（``<instance_id>:<设备名>``），网关内唯一。
        timestamp: 采样时间戳，Unix epoch 秒（float，UTC）。
        connected: 当前连接状态。
        battery_pct: 电量百分比 0--100（设备支持时），否则 None。
        signal_quality: 信号质量 0.0--1.0（仅连接/断开时按 1.0/0.0）。
        capabilities: 能力矩阵（name -> :class:`ButtplugCapability`）。
        vendor_meta: 厂商私有扩展字段。
    """

    device_id: str
    timestamp: float
    connected: bool
    battery_pct: Optional[float] = None
    signal_quality: Optional[float] = None
    capabilities: Dict[str, ButtplugCapability] = field(default_factory=dict)
    vendor_meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "timestamp": self.timestamp,
            "connected": self.connected,
            "battery_pct": self.battery_pct,
            "signal_quality": self.signal_quality,
            "capabilities": {k: v.to_dict() for k, v in self.capabilities.items()},
            "vendor_meta": dict(self.vendor_meta),
        }

    def to_device_feedback(self) -> DeviceFeedback:
        """转换为标准 :class:`DeviceFeedback`（连接状态 + 电量 + 能力摘要）。"""
        battery_extra = {}
        if self.battery_pct is not None:
            battery_extra["battery_pct"] = self.battery_pct
        return DeviceFeedback(
            device_id=self.device_id,
            kind=FeedbackKind.CONNECTION,
            value=1.0 if self.connected else 0.0,
            unit="bool",
            message="connected" if self.connected else "disconnected",
            timestamp=self.timestamp,
            extra={
                **battery_extra,
                "capabilities": {k: v.to_dict() for k, v in self.capabilities.items()},
                **self.vendor_meta,
            },
        )

    def to_status_frame(self) -> "ActuatorStatusFrame":
        """转换为既有 :class:`ActuatorStatusFrame`（供现有采集器/仪表盘复用）。"""
        from .actuator_feedback import ActuatorStatusFrame

        return ActuatorStatusFrame(
            device_id=self.device_id,
            timestamp=self.timestamp,
            connected=self.connected,
            battery_pct=self.battery_pct,
            signal_quality=self.signal_quality,
            vendor_meta={
                **self.vendor_meta,
                "capabilities": {k: v.to_dict() for k, v in self.capabilities.items()},
            },
        )


# 遥测帧消费者 / 断连安全回调。
TelemetrySink = Callable[[ActuatorTelemetryFrame], Awaitable[None]]
AsyncSafetyCallback = Callable[[ActuatorTelemetryFrame], Awaitable[None]]


# ── 能力矩阵解析（纯函数，可单测，无 Buttplug I/O）────────────────────────


def inspect_capabilities(device: Any) -> Dict[str, ButtplugCapability]:
    """解析单个 Buttplug 设备的能力矩阵，绝对不抛出异常。

    优先遍历 ``device.inputs`` / ``device.outputs`` 字典（buttplug-py 的
    特征目录）；若当前库版本不暴露该结构，则回退到
    ``message_attributes()`` / ``has_input()`` / ``has_output()`` 探测。
    每种查询独立 try-except，任何单项失败只跳过该项。
    """
    caps: Dict[str, ButtplugCapability] = {}
    if device is None:
        return caps

    _inspect_from_maps(device, caps)
    _inspect_from_api(device, caps)
    _approx_from_cap_queries(device, caps)
    return caps


def _inspect_from_maps(device: Any, caps: Dict[str, ButtplugCapability]) -> None:
    """从 devices.inputs / outputs 特征目录解析（buttplug-py 较新版本）。"""
    for kind, attr in (("output", "outputs"), ("input", "inputs")):
        feature_map: Any = getattr(device, attr, None)
        if feature_map is None:
            continue
        try:
            items = feature_map.items()
        except AttributeError:  # 某些版本为序列而非映射
            _inspect_from_api(device, caps)
            continue
        for name, features in items:
            cap_name = str(name).upper()
            features = list(features) if features is not None else []
            caps[cap_name] = ButtplugCapability(
                name=cap_name,
                supported=bool(features),
                channels=len(features),
                kind=kind,
                step_count=_safe_max_step_count(features),
            )


def _safe_max_step_count(features: List[Any]) -> Optional[int]:
    """取一组特征的最大档位数（未知则 None），不抛异常。"""
    if not features:
        return None
    steps: List[int] = []
    for feat in features:
        s = getattr(feat, "step_count", None)
        if isinstance(s, int) and s > 0:
            steps.append(s)
    return max(steps) if steps else None


def _inspect_from_api(device: Any, caps: Dict[str, ButtplugCapability]) -> None:
    """通过 ``message_attributes()`` 探测已识别的输出能力。"""
    message_attributes = getattr(device, "message_attributes", None)
    if message_attributes is None:
        return
    for name in list(_OUTPUT_CAPABILITIES) + list(_INPUT_CAPABILITIES):
        cap_name = str(name).upper()
        if cap_name in caps:
            continue
        attrs: Any = None
        try:
            attr_obj = getattr(OutputType if name in _OUTPUT_CAPABILITIES else InputType, name, None)
            if attr_obj is None:
                continue
            attrs = message_attributes(attr_obj)
        except Exception:  # noqa: BLE001 - 单项探测失败跳过
            continue
        attrs = list(attrs) if attrs else []
        if not attrs:
            continue
        caps[cap_name] = ButtplugCapability(
            name=cap_name,
            supported=True,
            channels=len(attrs),
            kind="output" if name in _OUTPUT_CAPABILITIES else "input",
            step_count=_safe_max_step_count(attrs),
            value_range=_safe_value_range(attrs),
        )


def _safe_value_range(attrs: List[Any]) -> Optional[tuple[float, float]]:
    """从首个带 range 的特征提取 (min, max)，未知则 None。"""
    for attr in attrs:
        rng = getattr(attr, "range", None)
        if rng is not None and len(rng) == 2:
            try:
                return (float(rng[0]), float(rng[1]))
            except (TypeError, ValueError):
                return None
    return None


def _approx_from_cap_queries(device: Any, caps: Dict[str, ButtplugCapability]) -> None:
    """最终兜底：以 ``has_output`` / ``has_input`` 给出布尔能力标记。"""
    has_out = getattr(device, "has_output", None)
    has_in = getattr(device, "has_input", None)
    if has_out is None and has_in is None:
        return
    for name in _OUTPUT_CAPABILITIES:
        key = str(name).upper()
        if key in caps:
            continue
        try:
            enum = getattr(OutputType, name, None)
            supported = bool(has_out and enum is not None and has_out(enum))
        except Exception:  # noqa: BLE001
            supported = False
        caps[key] = ButtplugCapability(name=key, supported=supported, kind="output")
    for name in _INPUT_CAPABILITIES:
        key = str(name).upper()
        if key in caps:
            continue
        try:
            enum = getattr(InputType, name, None)
            supported = bool(has_in and enum is not None and has_in(enum))
        except Exception:  # noqa: BLE001
            supported = False
        caps[key] = ButtplugCapability(name=key, supported=supported, kind="input")


# ── 电量查询（超时保护）────────────────────────────────────────────────────


async def query_battery_safe(device: Any, timeout: float = _DEFAULT_BATTERY_TIMEOUT) -> Optional[float]:
    """安全查询单个 Buttplug 设备电量百分比（0--100）。

    Buttplug 规范中 ``device.battery()`` 返回 0.0--1.0 比率。廉价硬件
    常不具备该能力或响应极慢，因此施加超时保护，任何失败返回 ``None``。
    """
    battery = getattr(device, "battery", None)
    if battery is None:
        return None
    try:
        value = await asyncio.wait_for(battery(), timeout=timeout)
        return round(float(value) * 100.0, 1) if value is not None else None
    except asyncio.TimeoutError:
        logger.debug("Buttplug 电量查询超时 device=%s", getattr(device, "name", "<unknown>"))
        return None
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.debug(
            "Buttplug 电量查询失败 device=%s", getattr(device, "name", "<unknown>"),
            exc_info=True,
        )
        return None


# ── 配置边界 ──────────────────────────────────────────────────────────────


class ButtplugFeedbackAdapterConfig(BaseModel):
    """Buttplug 反馈适配器的严格配置边界。

    仅在需要时显式设置 ``allow_remote_server`` 以连接到非本机 Intiface；
    出于安全考虑默认要求本机或显式放行。此处 URL 本身不携带凭据。
    """

    model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(default="buttplug_feedback", min_length=1)
    server_url: AnyUrl = "ws://127.0.0.1:12345"
    scan_duration_seconds: float = Field(default=5.0, ge=0.0, le=60.0)
    poll_interval_seconds: float = Field(default=10.0, ge=0.5, le=3600.0)
    battery_timeout: float = Field(default=_DEFAULT_BATTERY_TIMEOUT, gt=0.0, le=30.0)
    max_devices: int = Field(default=32, ge=1, le=256)


# ── 主适配器 ──────────────────────────────────────────────────────────────


class ButtplugFeedbackAdapter:
    """设备反馈与能力同步适配器。

    生命周期：``connect()`` → ``set_sink()`` / ``set_disconnect_callback()``
    → ``start()`` … ``stop()`` → ``disconnect()``。所有方法可安全重入。

    事件语义：
    - 设备接入：捕获并解析能力矩阵，随后推出一帧 `capabilities` 遥测。
    - 电量轮询：一个后台任务周期调用 :func:`query_battery_safe`。
    - 断连：设备移除或服务器断开时，立即以 ``connected=False`` 帧触发
      ``disconnect_callback``，并停用对应轮询。
    """

    def __init__(self, config: Mapping[str, Any]) -> None:
        validated = ButtplugFeedbackAdapterConfig.model_validate(dict(config))
        self.instance_id = validated.instance_id
        self.server_url = str(validated.server_url)
        self.scan_duration_seconds = validated.scan_duration_seconds
        self.poll_interval_seconds = validated.poll_interval_seconds
        self.battery_timeout = validated.battery_timeout
        self.max_devices = validated.max_devices

        self._client: Any | None = None
        self._connected = False
        self._sink: Optional[TelemetrySink] = None
        self._disconnect_callback: Optional[AsyncSafetyCallback] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._battery_cache: Dict[str, Optional[float]] = {}
        self._capabilities_cache: Dict[str, Dict[str, ButtplugCapability]] = {}
        self._tasks: list[asyncio.Task] = []
        self._command_lock = asyncio.Lock()

    # -- 回调注入 ---------------------------------------------------------
    def set_sink(self, sink: Optional[TelemetrySink]) -> None:
        """设置遥测帧消费者（异步回调）。可传 None 以取消。"""
        self._sink = sink

    def set_disconnect_callback(self, callback: Optional[AsyncSafetyCallback]) -> None:
        """设置断连安全回调（异步回调）。

        任一设备移除或服务器断开时调用，入参为 ``connected=False`` 的帧；
        调用方应在此停机/降级，落实故障安全。传 None 可取消。
        """
        self._disconnect_callback = callback

    # -- 生命周期 ---------------------------------------------------------
    async def connect(self) -> bool:
        """连接 Intiface 并扫描设备（幂等）。"""
        self._require_buttplug()
        async with self._command_lock:
            if self._connected:
                return True
            client = ButtplugClient(f"BTG Feedback Adapter ({self.instance_id})")
            client.on_device_added = self._on_device_added
            client.on_device_removed = self._on_device_removed
            client.on_server_disconnect = self._on_server_disconnect
            try:
                logger.info(
                    "连接反馈适配器 %s 到 Intiface %s", self.instance_id, self.server_url
                )
                await client.connect(self.server_url)
                self._client = client
                self._connected = True
                await client.start_scanning()
                if self.scan_duration_seconds > 0:
                    await asyncio.sleep(self.scan_duration_seconds)
                await client.stop_scanning()
                # 对扫描期间已接入的设备补发能力帧。
                for device in self._devices():
                    self._handle_device_joined(device)
                return True
            except asyncio.CancelledError:
                await self._disconnect_client(client)
                self._client = None
                self._connected = False
                raise
            except Exception as exc:  # noqa: BLE001
                await self._disconnect_client(client)
                self._client = None
                self._connected = False
                logger.exception(
                    "反馈适配器 %s 连接/扫描失败", self.instance_id
                )
                raise ConnectionError(
                    f"Buttplug 反馈连接/扫描失败: {exc}"
                ) from exc

    async def disconnect(self) -> None:
        """停止后台任务并断开连接（幂等，故障安全）。"""
        await self.stop()
        async with self._command_lock:
            if self._client is None:
                return
            client, self._client = self._client, None
            self._connected = False
            await self._disconnect_client(client)
            self._battery_cache.clear()

    async def start(self) -> None:
        """启动电量轮询任务（幂等）。"""
        if self._poll_task is None:
            self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """停止电量轮询任务（幂等）。"""
        task, self._poll_task = self._poll_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # -- 后台轮询 ---------------------------------------------------------
    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - 单轮失败不得终止循环
                logger.exception("反馈适配器 %s 电量轮询异常", self.instance_id)
            await asyncio.sleep(self.poll_interval_seconds)

    async def _poll_once(self) -> None:
        """对每个在册设备做一轮电量查询，并发推遥测帧。"""
        for device in self._devices():
            device_name = getattr(device, "name", "<unknown>")
            device_id = f"{self.instance_id}:{device_name}"
            try:
                battery_pct = await query_battery_safe(device, self.battery_timeout)
                self._battery_cache[device_id] = battery_pct
                capacities = self._capabilities_cache.get(device_id, {})
                frame = ActuatorTelemetryFrame(
                    device_id=device_id,
                    timestamp=time.time(),
                    connected=True,
                    battery_pct=battery_pct,
                    signal_quality=1.0,
                    capabilities=capacities,
                    vendor_meta={
                        "protocol": "buttplug",
                        "device_name": device_name,
                        "adapter": self.instance_id,
                    },
                )
                await self._emit(frame)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - 单设备失败跳过
                logger.debug(
                    "反馈适配器 %s 轮询设备异常 device=%s",
                    self.instance_id, device_id, exc_info=True,
                )

    # -- 事件处理 ---------------------------------------------------------
    def _handle_device_joined(self, device: Any) -> None:
        """同步记录设备能力并异步推出一帧能力遥测。"""
        device_name = getattr(device, "name", "<unknown>")
        device_id = f"{self.instance_id}:{device_name}"
        capacities = inspect_capabilities(device)
        self._capabilities_cache[device_id] = capacities

        battery_pct = self._battery_cache.get(device_id)
        frame = ActuatorTelemetryFrame(
            device_id=device_id,
            timestamp=time.time(),
            connected=True,
            battery_pct=battery_pct,
            signal_quality=1.0,
            capabilities=capacities,
            vendor_meta={
                "protocol": "buttplug",
                "device_name": device_name,
                "adapter": self.instance_id,
            },
        )
        self._spawn_background(self._emit(frame), f"emit-joined-{device_name}")

    def _on_device_added(self, device: Any) -> None:
        """Buttplug 接入回调（同步签名；异步工作入队）。"""
        logger.info("%s 发现 Buttplug 设备: %s", self.instance_id, getattr(device, "name", "<unknown>"))
        self._handle_device_joined(device)

    def _on_device_removed(self, device: Any) -> None:
        """Buttplug 移除回调 —— 看门狗触发点。"""
        device_name = getattr(device, "name", "<unknown>")
        device_id = f"{self.instance_id}:{device_name}"
        logger.warning("%s 设备掉线: %s", self.instance_id, device_name)
        self._capabilities_cache.pop(device_id, None)
        self._battery_cache.pop(device_id, None)
        self._trigger_disconnect(device_id, f"device removed: {device_name}")

    def _on_server_disconnect(self, *_: Any) -> None:
        """服务器断连回调 —— 全局看门狗触发点。"""
        logger.error("%s 失去 Intiface 服务器连接", self.instance_id)
        self._connected = False
        signal = getattr(self._client, "signal_disconnect", "server disconnected")
        self._trigger_disconnect(self.instance_id, signal)

    def _trigger_disconnect(self, device_id: str, reason: str) -> None:
        """构建断连帧并尽量投递给异步安全回调。"""
        frame = ActuatorTelemetryFrame(
            device_id=device_id,
            timestamp=time.time(),
            connected=False,
            battery_pct=None,
            signal_quality=0.0,
            capabilities=self._capabilities_cache.pop(device_id, {}),
            vendor_meta={"reason": reason, "adapter": self.instance_id},
        )
        callback = self._disconnect_callback
        if callback is not None:
            self._spawn_background(self._safe_invoke(callback, frame), f"disconnect-{device_id}")
        self._spawn_background(self._emit(frame), f"disconnect-frame-{device_id}")

    async def _safe_invoke(self, callback: AsyncSafetyCallback, frame: ActuatorTelemetryFrame) -> None:
        try:
            await callback(frame)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception(
                "断连安全回调异常 device=%s", frame.device_id
            )

    async def _emit(self, frame: ActuatorTelemetryFrame) -> None:
        """投递遥测帧到 sink（消费失败仅记录）。"""
        sink = self._sink
        if sink is None:
            return
        try:
            await sink(frame)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("遥测帧消费者异常 device=%s", frame.device_id)

    # -- 工具 -------------------------------------------------------------
    def _devices(self) -> List[Any]:
        if self._client is None:
            return []
        devices: Any = getattr(self._client, "devices", {})
        try:
            values = list(devices.values())
        except AttributeError:  # 序列而非映射
            values = list(devices)
        return values[: self.max_devices]

    def _spawn_background(self, coro: Awaitable[None], tag: str) -> None:
        """以受保护的后台任务运行异步工作，防止任务堆积 / 无循环时崩溃。"""
        if self._connected is False and tag.startswith("emit"):
            return
        if len(self._tasks) >= 64:  # 简单背压护栏
            logger.warning("反馈适配器 %s 后台任务过多，丢弃 %s", self.instance_id, tag)
            return
        try:
            task = asyncio.create_task(coro)
        except RuntimeError:  # 事件循环已关闭/未运行（进程收尾或跨线程回调）
            logger.warning(
                "反馈适配器 %s 无可用事件循环，丢弃 %s", self.instance_id, tag
            )
            return
        task.add_done_callback(lambda t: self._tasks.remove(t) if t in self._tasks else None)
        self._tasks.append(task)

    @staticmethod
    async def _disconnect_client(client: Any) -> None:
        try:
            await client.disconnect()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.debug("Intiface 断开过程出现错误", exc_info=True)

    @staticmethod
    def _require_buttplug() -> None:
        if _BUTTPLUG_IMPORT_ERROR is not None:
            raise RuntimeError(
                "buttplug 是反馈适配器所必需；请安装 `pip install buttplug`"
            ) from _BUTTPLUG_IMPORT_ERROR