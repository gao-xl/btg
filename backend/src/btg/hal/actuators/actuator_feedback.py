"""硬件反向遥测与状态同步模块。

定期或事件驱动地从已连接的执行器（Buttplug、Coyote、YoKonex）中读取
电量（Battery）、连接状态以及当前硬件输出位置，并通过事件总线推送到
WebSocket 前端仪表盘。

本模块是 ``btg.feedback.collector.FeedbackCollector`` 的上层增强版本：
在标准 ``DeviceFeedback`` 基础上，追加 ``ActuatorStatusFrame`` 结构，
包含硬件物理位置/强度档位、电池百分比和信号质量，供 UI 更新电量图标
和位置进度条。

协议分工：
- **Buttplug**: 通过 ``InputType.BATTERY`` 能力检测 + ``device.battery()``
  异步查询；每个设备独立超时保护。
- **Coyote (DG-LAB)**: 读取 BLE 通知回调缓存的电池值，以及内部
  ``_intensity_a``/``_intensity_b`` 当前输出强度。
- **YoKonex**: 通过 HTTP API-bridge ``/health`` 端点获取连接状态。

容错原则：任何单台设备的读取超时或异常不得导致网关崩溃。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from btg_sdk import DeviceFeedback, FeedbackKind

logger = logging.getLogger(__name__)


# ── 状态帧定义 ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ActuatorStatusFrame:
    """执行器硬件反向遥测帧。

    在 ``DeviceFeedback`` 的连接/电量基础信息之上，额外承载：
    - ``battery_pct``: 电量百分比 0--100（若设备支持）；
    - ``channel_a_level`` / ``channel_b_level``: 当前输出强度档位
      （0--100 归一化百分比）；
    - ``physical_position``: 物理位置（0.0--1.0 归一化比例，适用于
      行程传感器或振动电机转速映射）；
    - ``signal_quality``: 信号质量（0.0--1.0，BLE RSSI 映射或
      仅连接/断开的 1.0/0.0）；
    - ``vendor_meta``: 厂商私有扩展字段。
    """

    device_id: str
    timestamp: float
    connected: bool
    battery_pct: Optional[float] = None
    channel_a_level: Optional[float] = None
    channel_b_level: Optional[float] = None
    physical_position: Optional[float] = None
    signal_quality: Optional[float] = None
    vendor_meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 可输出的字典。"""
        return {
            "device_id": self.device_id,
            "timestamp": self.timestamp,
            "connected": self.connected,
            "battery_pct": self.battery_pct,
            "channel_a_level": self.channel_a_level,
            "channel_b_level": self.channel_b_level,
            "physical_position": self.physical_position,
            "signal_quality": self.signal_quality,
            "vendor_meta": dict(self.vendor_meta),
        }

    def to_device_feedback(self) -> DeviceFeedback:
        """向下兼容转换为标准 ``DeviceFeedback``（连接状态）。"""
        return DeviceFeedback(
            device_id=self.device_id,
            kind=FeedbackKind.CONNECTION,
            value=1.0 if self.connected else 0.0,
            unit="bool",
            message="connected" if self.connected else "disconnected",
            timestamp=self.timestamp,
            extra=self.to_dict(),
        )


# ── 状态总线类型 ──────────────────────────────────────────────────────────

StatusSink = Callable[[ActuatorStatusFrame], Awaitable[None]]


# ── Buttplug 设备状态采集 ─────────────────────────────────────────────────

_BATTERY_TIMEOUT = 3.0


async def _collect_buttplug_device(device: Any, instance_id: str) -> ActuatorStatusFrame:
    """从单个 Buttplug 设备采集反向遥测。

    遍历设备的 ``InputType`` 能力，检测 ``BATTERY`` 并以超时保护调用
    ``device.battery()``。廉价玩具通常不具备电池读取能力或响应极慢，
    超时后返回 ``None`` 而非抛出异常。
    """
    device_name = getattr(device, "name", "<unknown>")
    device_id = f"{instance_id}:{device_name}"
    connected = True  # 能被遍历即视为已连接

    battery_pct: Optional[float] = None
    try:
        from buttplug import InputType as BPInputType
        if device.has_input(BPInputType.BATTERY):
            battery_val = await asyncio.wait_for(
                device.battery(), timeout=_BATTERY_TIMEOUT
            )
            # Buttplug 规范：battery() 返回 0.0--1.0 比率
            battery_pct = round(float(battery_val) * 100.0, 1)
    except asyncio.TimeoutError:
        logger.debug(
            "Buttplug 电量查询超时 device=%s", device_id
        )
    except Exception:  # noqa: BLE001
        logger.debug(
            "Buttplug 电量查询失败 device=%s", device_id, exc_info=True
        )

    return ActuatorStatusFrame(
        device_id=device_id,
        timestamp=time.time(),
        connected=connected,
        battery_pct=battery_pct,
        signal_quality=1.0,
        vendor_meta={"protocol": "buttplug", "device_name": device_name},
    )


# ── Coyote (DG-LAB) 设备状态采集 ─────────────────────────────────────────

def _collect_coyote(actuator: Any) -> ActuatorStatusFrame:
    """从 Coyote 执行器实例读取内部缓存状态。

    Coyote 通过 BLE 通知回调 ``_on_battery`` 持续更新 ``_battery``；
    强度值由 ``set_target()`` 写入时缓存在 ``_intensity_a``/``_intensity_b``。
    本函数仅读取内存中的缓存值，不发起 BLE I/O。
    """
    device_id = getattr(actuator, "instance_id", "coyote_unknown")
    connected = getattr(actuator, "_connected", False)
    battery_raw: Optional[int] = getattr(actuator, "_battery", None)
    intensity_a_raw: int = getattr(actuator, "_intensity_a", 0)
    intensity_b_raw: int = getattr(actuator, "_intensity_b", 0)

    battery_pct: Optional[float] = None
    if battery_raw is not None:
        battery_pct = float(battery_raw)

    # Coyote intensity 0--2047 映射到 0--100%
    from .coyote_packets import INTENSITY_MAX

    level_a = round(intensity_a_raw / INTENSITY_MAX * 100.0, 1) if INTENSITY_MAX else 0.0
    level_b = round(intensity_b_raw / INTENSITY_MAX * 100.0, 1) if INTENSITY_MAX else 0.0

    # 物理位置：取两通道强度的最大值作为当前输出位置的归一化比例
    physical_position = max(level_a, level_b) / 100.0

    return ActuatorStatusFrame(
        device_id=device_id,
        timestamp=time.time(),
        connected=connected,
        battery_pct=battery_pct,
        channel_a_level=level_a,
        channel_b_level=level_b,
        physical_position=physical_position,
        signal_quality=1.0 if connected else 0.0,
        vendor_meta={
            "protocol": "ble",
            "device_type": "coyote",
            "channel": getattr(actuator, "channel", "A"),
            "waveform_x": getattr(actuator, "x", None),
            "waveform_y": getattr(actuator, "y", None),
            "waveform_z": getattr(actuator, "z", None),
        },
    )


# ── YoKonex 设备状态采集 ─────────────────────────────────────────────────

async def _collect_yokonex(actuator: Any) -> ActuatorStatusFrame:
    """从 YoKonex 执行器实例采集反向遥测。

    通过 HTTP API-bridge ``/health`` 端点检测连接状态；YoKonex 协议
    本身不提供电量回传，因此 ``battery_pct`` 保持 ``None``。
    """
    device_id = getattr(actuator, "instance_id", "yokonex_unknown")
    connected = getattr(actuator, "_connected", False)
    bridge_url = getattr(actuator, "bridge_url", "")
    timeout = getattr(actuator, "timeout_seconds", 5.0)

    # 尝试主动探测 bridge 健康状态（仅在已连接时执行）
    health_ok = connected
    if connected and bridge_url:
        try:
            client = getattr(actuator, "_client", None)
            if client is not None:
                response = await asyncio.wait_for(
                    client.get(f"{bridge_url}/health"),
                    timeout=min(timeout, 2.0),
                )
                data = response.json()
                health_ok = (
                    response.status_code == 200
                    and data.get("status") == "ok"
                    and data.get("imReady") is True
                )
        except asyncio.TimeoutError:
            logger.debug("YoKonex health probe 超时 device=%s", device_id)
            health_ok = False
        except Exception:  # noqa: BLE001
            logger.debug(
                "YoKonex health probe 失败 device=%s", device_id, exc_info=True
            )
            health_ok = False

    return ActuatorStatusFrame(
        device_id=device_id,
        timestamp=time.time(),
        connected=health_ok,
        battery_pct=None,
        signal_quality=1.0 if health_ok else 0.0,
        vendor_meta={
            "protocol": "yokonex_im",
            "bridge_url": bridge_url,
        },
    )


# ── Mock 执行器状态采集 ──────────────────────────────────────────────────

def _collect_mock(actuator: Any) -> ActuatorStatusFrame:
    """Mock 执行器：仅报告连接状态，无真实硬件回传。"""
    device_id = getattr(actuator, "instance_id", "mock_unknown")
    return ActuatorStatusFrame(
        device_id=device_id,
        timestamp=time.time(),
        connected=True,
        vendor_meta={"protocol": "mock"},
    )


# ── 协议探测 ─────────────────────────────────────────────────────────────

def _detect_protocol(actuator: Any) -> str:
    """根据执行器实例属性推断其底层协议类型。"""
    cls_name = type(actuator).__name__
    if "Buttplug" in cls_name or "buttplug" in cls_name:
        return "buttplug"
    if "Coyote" in cls_name or "coyote" in cls_name:
        return "coyote"
    if "YokoNex" in cls_name or "yokonex" in cls_name:
        return "yokonex"
    if "Mock" in cls_name or "mock" in cls_name:
        return "mock"
    # 按属性探测
    if hasattr(actuator, "_client") and hasattr(actuator, "_devices"):
        return "buttplug"
    if hasattr(actuator, "_intensity_a") and hasattr(actuator, "_battery"):
        return "coyote"
    if hasattr(actuator, "bridge_url"):
        return "yokonex"
    return "unknown"


# ── 采集调度器 ────────────────────────────────────────────────────────────

class ActuatorFeedbackCollector:
    """硬件反向遥测采集调度器。

    定期遍历 ``channel_manager.actuator_groups`` 中所有激活执行器，
    按协议类型分派到对应的采集函数，将 ``ActuatorStatusFrame`` 通过
    ``sink`` 回调推送到事件总线，进而经 WebSocket 广播到前端仪表盘。

    与 ``btg.feedback.collector.FeedbackCollector`` 的区别：
    - 产出结构化的 ``ActuatorStatusFrame``（含电量、强度档位、物理位置）；
    - 对 Buttplug 设备电量查询施加独立超时保护；
    - 支持事件驱动的即时采集（``collect_once()``）。

    配置项：
    - ``interval_seconds``: 轮询间隔，默认 ``5.0`` 秒；
    - ``sink``: 异步回调，接收 ``ActuatorStatusFrame``；
    - ``buttplug_battery_timeout``: Buttplug 电量查询超时，默认 ``3.0`` 秒。
    """

    def __init__(
        self,
        channel_manager: Any,
        *,
        interval_seconds: float = 5.0,
        sink: Optional[StatusSink] = None,
        buttplug_battery_timeout: float = _BATTERY_TIMEOUT,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds 必须为正数（单位：秒）")
        self._channel_manager = channel_manager
        self._interval = interval_seconds
        self._sink = sink
        self._battery_timeout = buttplug_battery_timeout
        self._task: Optional[asyncio.Task] = None

    def set_sink(self, sink: StatusSink) -> None:
        """设置状态帧消费者回调。"""
        self._sink = sink

    async def start(self) -> None:
        """启动后台轮询任务（幂等）。"""
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """停止后台轮询任务（幂等）。"""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def collect_once(self) -> List[ActuatorStatusFrame]:
        """对当前所有激活执行器采集一轮，返回收集到的状态帧列表。

        单台设备异常不影响其余设备的采集。
        """
        collected: List[ActuatorStatusFrame] = []
        for group in self._channel_manager.actuator_groups.values():
            handle = group.active
            if handle is None:
                continue
            frame = await self._collect_device(handle)
            if frame is not None:
                collected.append(frame)
                if self._sink is not None:
                    try:
                        await self._sink(frame)
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "状态帧消费者处理异常 device=%s", frame.device_id
                        )
        return collected

    async def _collect_device(self, handle: Any) -> Optional[ActuatorStatusFrame]:
        """从单个设备句柄采集状态帧，捕获一切异常。"""
        actuator = handle.device
        instance_id = getattr(handle, "instance_id", "unknown")
        try:
            protocol = _detect_protocol(actuator)
            if protocol == "buttplug":
                return await self._collect_buttplug_group(actuator, instance_id)
            elif protocol == "coyote":
                return _collect_coyote(actuator)
            elif protocol == "yokonex":
                return await _collect_yokonex(actuator)
            elif protocol == "mock":
                return _collect_mock(actuator)
            else:
                logger.debug(
                    "未知协议类型 device=%s protocol=%s", instance_id, protocol
                )
                return None
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception(
                "执行器反向遥测采集异常 instance=%s", instance_id
            )
            return None

    async def _collect_buttplug_group(
        self, bridge: Any, instance_id: str
    ) -> Optional[ActuatorStatusFrame]:
        """从 Buttplug 桥接器遍历所有设备并聚合状态。

        如果桥接器已断连，返回一个 disconnected 状态帧；
        如果遍历过程中有设备异常，逐个跳过不阻断。
        """
        if not getattr(bridge, "_connected", False):
            return ActuatorStatusFrame(
                device_id=instance_id,
                timestamp=time.time(),
                connected=False,
                vendor_meta={"protocol": "buttplug"},
            )

        # 遍历 Intiface 设备列表
        client = getattr(bridge, "_client", None)
        if client is None:
            return None

        devices: Dict[str, Any] = getattr(client, "devices", {})
        if not devices:
            return ActuatorStatusFrame(
                device_id=instance_id,
                timestamp=time.time(),
                connected=True,
                battery_pct=None,
                vendor_meta={"protocol": "buttplug", "device_count": 0},
            )

        # 采集每个设备的状态
        frames: List[ActuatorStatusFrame] = []
        for bp_device in devices.values():
            try:
                frame = await asyncio.wait_for(
                    _collect_buttplug_device(bp_device, instance_id),
                    timeout=self._battery_timeout + 1.0,
                )
                frames.append(frame)
            except asyncio.TimeoutError:
                device_name = getattr(bp_device, "name", "<unknown>")
                logger.debug(
                    "Buttplug 设备采集超时 device=%s:%s",
                    instance_id, device_name,
                )
            except Exception:  # noqa: BLE001
                device_name = getattr(bp_device, "name", "<unknown>")
                logger.debug(
                    "Buttplug 设备采集异常 device=%s:%s",
                    instance_id, device_name,
                    exc_info=True,
                )

        if not frames:
            return ActuatorStatusFrame(
                device_id=instance_id,
                timestamp=time.time(),
                connected=True,
                vendor_meta={"protocol": "buttplug", "device_count": len(devices)},
            )

        # 聚合：取第一个设备的帧作为主帧，其余放入 vendor_meta
        primary = frames[0]
        if len(frames) > 1:
            merged_meta = dict(primary.vendor_meta)
            merged_meta["additional_devices"] = [
                f.to_dict() for f in frames[1:]
            ]
            return ActuatorStatusFrame(
                device_id=primary.device_id,
                timestamp=primary.timestamp,
                connected=primary.connected,
                battery_pct=primary.battery_pct,
                channel_a_level=primary.channel_a_level,
                channel_b_level=primary.channel_b_level,
                physical_position=primary.physical_position,
                signal_quality=primary.signal_quality,
                vendor_meta=merged_meta,
            )
        return primary

    async def _run(self) -> None:
        """后台轮询循环。"""
        while True:
            try:
                await self.collect_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("执行器反向遥测轮询异常")
            await asyncio.sleep(self._interval)
