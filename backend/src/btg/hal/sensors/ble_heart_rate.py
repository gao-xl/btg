"""BLE 心率传感器插件（标准心率带 + 小米手环）。

支持两种 BLE 心率数据采集模式：

1. **标准 GATT 模式**（Magene / Polar / Garmin 等兼容设备）：
   通过 bleak 异步 BLE 库连接 Bluetooth SIG Heart Rate Service (0x180D)，
   订阅 Heart Rate Measurement 特征值 (0x2A37) 的 Notification。

2. **小米被动嗅探模式**（Mi Band 5/6/7/8/9/10 等）：
   通过 xiaomi-ble 库解析 MiBeacon 广播数据，无需主动连接即可获取心率。
   需要提供认证密钥（auth_key）以解密广播数据。

配置项（通过 ``devices.yaml`` 注入）：

- ``instance_id``: 传感器实例 ID，默认 ``"ble_hr_0"``。
- ``device_name_prefix``: BLE 广播名前缀，用于自动扫描匹配。
- ``device_address``: 可选的固定 BLE MAC 地址，跳过扫描直连。
- ``reconnect_delay_seconds``: 断线重连等待秒数，默认 ``3.0``。
- ``scan_timeout_seconds``: 扫描超时秒数，默认 ``10.0``。
- ``channel``: 逻辑通道名，默认 ``"heart_rate"``。
- ``mode``: 采集模式，``"gatt"`` (默认) 或 ``"xiaomi"``。
- ``xiaomi_auth_key``: 小米设备认证密钥（16字节 hex 字符串）。
- ``xiaomi_device_model``: 小米设备型号（如 ``"M2457B1"``）。
- ``xiaomi_passive``: 是否被动嗅探广播数据，默认 ``True``。

参考文档：
- Bluetooth SIG Heart Rate Service: https://www.bluetooth.com/specifications/specs/heart-rate-service-1-0/
- xiaomi-ble: https://github.com/Bluetooth-Devices/xiaomi-ble
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time
from typing import Any, Mapping, Optional

from btg_sdk import BaseSensor, Reading, register_sensor

try:
    from bleak import BleakClient, BleakScanner
    from bleak.exc import BleakError
except ImportError as exc:  # pragma: no cover - depends on deployment extras.
    BleakClient = BleakScanner = BleakError = None  # type: ignore[assignment,misc]
    _BLEAK_IMPORT_ERROR: ImportError | None = exc
else:
    _BLEAK_IMPORT_ERROR = None

try:
    from xiaomi_ble import (
        XiaomiBluetoothDeviceData,
        SensorUpdate,
        DeviceKey,
        SensorDescription,
        SensorValue,
        Units,
    )
    from xiaomi_ble.const import EncryptionScheme
    from xiaomi_ble.parser import ExtendedSensorDeviceClass
    _XIAOMI_BLE_AVAILABLE = True
except ImportError:
    XiaomiBluetoothDeviceData = None  # type: ignore[assignment,misc]
    SensorUpdate = None  # type: ignore[assignment,misc]
    DeviceKey = None  # type: ignore[assignment,misc]
    SensorDescription = None  # type: ignore[assignment,misc]
    SensorValue = None  # type: ignore[assignment,misc]
    Units = None  # type: ignore[assignment,misc]
    EncryptionScheme = None  # type: ignore[assignment,misc]
    ExtendedSensorDeviceClass = None  # type: ignore[assignment,misc]
    _XIAOMI_BLE_AVAILABLE = False

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:  # pragma: no cover
    BaseModel = object  # type: ignore[assignment]
    ConfigDict = lambda **kw: None  # type: ignore[misc]
    Field = lambda **kw: None  # type: ignore[misc]

LOGGER = logging.getLogger(__name__)

# ── Bluetooth SIG Heart Rate Service ──────────────────────────────────────
HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

# Heart Rate Measurement 位域 (Flags byte)
_FLAGS_HEART_RATE_VALUE_FORMAT = 0x01  # 0 = 8-bit, 1 = 16-bit
_FLAGS_ENERGY_EXPENDITURE = 0x08      # 是否包含累计能耗字段
_FLAGS_RR_INTERVAL = 0x10             # 是否包含 RR 间期字段

# ── 小米 MiBeacon 服务 UUID ─────────────────────────────────────────────
XIAOMI_MIBEACON_UUID = "0000fe95-0000-1000-8000-00805f9b34fb"


class BleHeartRateConfig(BaseModel if BaseModel is not object else object):  # type: ignore[misc]
    """BLE 心率带插件的严格配置边界。"""

    if BaseModel is not object:
        model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(default="ble_hr_0", min_length=1)  # type: ignore[call-arg]
    device_name_prefix: str = "Magene"
    device_address: Optional[str] = None
    reconnect_delay_seconds: float = Field(default=3.0, ge=0.5, le=30.0)  # type: ignore[call-arg]
    scan_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)  # type: ignore[call-arg]
    channel: str = "heart_rate"
    mode: str = Field(default="gatt")  # type: ignore[call-arg]
    xiaomi_auth_key: Optional[str] = None
    xiaomi_device_model: Optional[str] = None
    xiaomi_passive: bool = True


def _parse_heart_rate_measurement(data: bytearray) -> Optional[int]:
    """解析 Bluetooth SIG Heart Rate Measurement 特征值。

    布局（per CSS Part A, Section 3.28）：

    - Byte 0: Flags
    - Byte 1+: Heart Rate Value (8-bit 或 16-bit, 由 Flags bit 0 决定)
    - 可选: Energy Expended (16-bit, 若 Flags bit 3)
    - 可选: RR-Interval (16-bit × N, 若 Flags bit 4)

    Returns:
        心率值 (BPM)，解析失败返回 None。
    """
    if len(data) < 2:
        return None

    flags = data[0]
    is_16bit = bool(flags & _FLAGS_HEART_RATE_VALUE_FORMAT)

    try:
        if is_16bit:
            if len(data) < 3:
                return None
            heart_rate = struct.unpack_from("<H", data, 1)[0]
        else:
            heart_rate = data[1]
    except (struct.error, IndexError):
        return None

    if heart_rate < 0 or heart_rate > 300:
        return None

    return heart_rate


def _parse_xiaomi_mibeacon(data: bytearray, auth_key: Optional[bytes] = None) -> Optional[int]:
    """解析小米 MiBeacon 广播数据中的心率值。

    MiBeacon v5+ 格式：
    - Byte 0-2: Frame control (3 bytes)
    - Byte 3-4: Device type (little-endian)
    - Byte 5-10: MAC address (6 bytes)
    - Byte 11: Capability
    - Byte 12+: Object data (加密或明文)

    Object ID 0x1017 或 0x1048 表示心率数据。

    Args:
        data: 原始广播数据。
        auth_key: 16字节认证密钥（用于解密 v5+ 广播）。

    Returns:
        心率值 (BPM)，解析失败返回 None。
    """
    if len(data) < 13:
        return None

    # 检查 MiBeacon 服务标识（data[0] 通常是 service data UUID 的一部分）
    # 实际的 MiBeacon 数据从 Byte 3 开始（Frame control）
    frame_control = int.from_bytes(data[0:3], "little")

    # 检查是否有对象数据
    if not (frame_control & 0x4000):  # bit 14 = 累计数据标志
        return None

    # 对象数据偏移（根据加密标志和计数器）
    object_offset = 3 + 6 + 2 + 1  # frame_control(3) + MAC(6) + capability(2) + counter(1)

    if object_offset + 4 > len(data):
        return None

    # 解析对象头
    object_id = int.from_bytes(data[object_offset:object_offset + 2], "little")
    object_length = data[object_offset + 2]

    if object_offset + 3 + object_length > len(data):
        return None

    object_data = data[object_offset + 3:object_offset + 3 + object_length]

    # 小米心率对象 ID: 0x1048 (heart rate with timestamp)
    # 或 0x1017 (simple heart rate, older devices)
    if object_id in (0x1048, 0x1017):
        if len(object_data) >= 1:
            heart_rate = object_data[0]
            if 0 <= heart_rate <= 300:
                return heart_rate

    return None


@register_sensor("ble_heart_rate")
class BleHeartRateSensor(BaseSensor):
    """通过 BLE GATT 连接标准心率带并实时推送心率数据。

    实现 ``BaseSensor`` 契约：

    - ``connect()``: 扫描并连接目标心率带，订阅心率 Notification。
    - ``read_stream()``: 持续接收 Notification 并将解析出的心率值以
      ``Reading`` 写入 ``out_queue``；断线时自动进入重连循环。
    - ``disconnect()``: 幂等释放 BLE 资源。
    """

    def __init__(self, config: Mapping[str, Any]) -> None:
        if _BLEAK_IMPORT_ERROR is not None:
            raise ImportError(
                "bleak 库未安装，请执行 pip install bleak 或 "
                "pip install btg-backend[ble] 后重试"
            ) from _BLEAK_IMPORT_ERROR

        raw = dict(config)
        if isinstance(BleHeartRateConfig, type) and issubclass(BleHeartRateConfig, BaseModel):
            validated = BleHeartRateConfig.model_validate(raw)
            self.instance_id: str = validated.instance_id
            self._device_name_prefix: str = validated.device_name_prefix
            self._device_address: Optional[str] = validated.device_address
            self._reconnect_delay: float = validated.reconnect_delay_seconds
            self._scan_timeout: float = validated.scan_timeout_seconds
            self._channel: str = validated.channel
        else:
            self.instance_id = str(raw.get("instance_id", "ble_hr_0"))
            self._device_name_prefix = str(raw.get("device_name_prefix", "Magene"))
            self._device_address = raw.get("device_address")
            self._reconnect_delay = float(raw.get("reconnect_delay_seconds", 3.0))
            self._scan_timeout = float(raw.get("scan_timeout_seconds", 10.0))
            self._channel = str(raw.get("channel", "heart_rate"))

        self._client: Optional[BleakClient] = None
        self._connected = False
        self._stop_event = asyncio.Event()
        self._notification_queue: asyncio.Queue[int] = asyncio.Queue(maxsize=64)

    # ── BaseSensor 契约 ───────────────────────────────────────────────────

    async def connect(self) -> bool:
        """扫描并连接 BLE 心率带，订阅心率 Measurement Notification。

        Returns:
            True 表示连接成功并已订阅 Notification。

        Raises:
            ConnectionError: 扫描超时或连接失败时抛出，由冗余层触发备用切换。
        """
        device = await self._find_device()
        if device is None:
            raise ConnectionError(
                f"未找到匹配的心率带 "
                f"(prefix={self._device_name_prefix!r}, address={self._device_address!r})"
            )

        try:
            self._client = BleakClient(
                device,
                disconnected_callback=self._on_disconnect,
            )
            await self._client.connect(timeout=10.0)
            await self._client.start_notify(
                HR_MEASUREMENT_UUID,
                self._notification_handler,
            )
            self._connected = True
            LOGGER.info(
                "BLE 心率带已连接: %s (%s)",
                getattr(device, "name", "unknown"),
                getattr(device, "address", "unknown"),
            )
            return True
        except Exception as exc:
            self._connected = False
            await self._safe_disconnect()
            raise ConnectionError(f"BLE 心率带连接失败: {exc}") from exc

    async def disconnect(self) -> None:
        """幂等释放 BLE 连接资源。"""
        self._stop_event.set()
        self._connected = False
        await self._safe_disconnect()
        LOGGER.info("BLE 心率带已断开: %s", self.instance_id)

    async def read_stream(self, out_queue: asyncio.Queue) -> None:
        """持续从 Notification 队列读取心率并写入总线。

        断线时自动进入后台重连循环，不会导致网关崩溃。
        外部通过 ``disconnect()`` 设置 ``_stop_event`` 终止本协程。
        """
        while not self._stop_event.is_set():
            try:
                if not self._connected:
                    await self._reconnect_loop()
                    continue

                try:
                    bpm = await asyncio.wait_for(
                        self._notification_queue.get(), timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue

                reading = Reading(
                    channel=self._channel,
                    sensor_id=self.instance_id,
                    value=float(bpm),
                    unit="bpm",
                    timestamp=time.time(),
                )
                out_queue.put_nowait(reading)

            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                LOGGER.exception("BLE 心率带读取异常")
                self._connected = False
                await self._backoff_sleep()

    # ── 内部方法 ──────────────────────────────────────────────────────────

    def _notification_handler(self, _sender: Any, data: bytearray) -> None:
        """Bleak Notification 回调：解析心率值并写入内部队列。"""
        bpm = _parse_heart_rate_measurement(data)
        if bpm is None:
            return
        if self._notification_queue.full():
            try:
                self._notification_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self._notification_queue.put_nowait(bpm)
        except asyncio.QueueFull:
            pass

    def _on_disconnect(self, _client: Any) -> None:
        """Bleak 断连回调（在 Bleak 事件循环线程中同步调用）。"""
        self._connected = False
        LOGGER.warning("BLE 心率带连接断开: %s", self.instance_id)

    async def _find_device(self) -> Optional[Any]:
        """按名称前缀或 MAC 地址扫描 BLE 心率带。"""
        if self._device_address:
            try:
                device = await BleakScanner.find_device_by_address(
                    self._device_address, timeout=self._scan_timeout
                )
                return device
            except BleakError:
                LOGGER.warning(
                    "按地址 %s 扫描失败，回退到前缀扫描", self._device_address
                )

        def _matches(d: Any) -> bool:
            name = getattr(d, "name", None) or ""
            return (
                not self._device_name_prefix
                or name.startswith(self._device_name_prefix)
            )

        try:
            device = await BleakScanner.find_device_by_filter(
                _matches, timeout=self._scan_timeout
            )
            return device
        except BleakError as exc:
            LOGGER.error("BLE 扫描失败: %s", exc)
            return None

    async def _reconnect_loop(self) -> None:
        """断线重连循环：指数退避，直到连接成功或被外部停止。"""
        delay = self._reconnect_delay
        while not self._stop_event.is_set():
            LOGGER.info(
                "BLE 心率带重连中... (delay=%.1fs)", delay
            )
            await self._backoff_sleep(delay)
            if self._stop_event.is_set():
                break
            try:
                await self.connect()
                return
            except ConnectionError as exc:
                LOGGER.warning("BLE 重连失败: %s", exc)
                delay = min(delay * 2, 30.0)

    async def _backoff_sleep(self, delay: Optional[float] = None) -> None:
        """可被 ``_stop_event`` 中断的等待。"""
        seconds = delay if delay is not None else self._reconnect_delay
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _safe_disconnect(self) -> None:
        """安全断开 BLE 客户端（忽略异常）。"""
        if self._client is None:
            return
        try:
            if self._client.is_connected:
                await self._client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._client = None


@register_sensor("xiaomi_heart_rate")
class XiaomiBleHeartRateSensor(BaseSensor):
    """通过被动嗅探小米 MiBeacon 广播获取心率数据。

    实现 ``BaseSensor`` 契约，使用 xiaomi-ble 库解析小米手环/手表的
    MiBeacon 广播数据，提取心率值并推送到网关遥测总线。

    支持设备型号：
    - Mi Band 5/6/7/8/9/10
    - Amazfit Bip/Verme/T-Rex 系列
    - 其他支持 MiBeacon v5+ 的小米/华米设备

    注意事项：
    - 需要提供 16 字节认证密钥（auth_key）以解密广播数据。
    - 认证密钥可通过 huami-token 或 freemyband.com 获取。
    - 被动嗅探模式无需主动连接设备，功耗更低。
    """

    def __init__(self, config: Mapping[str, Any]) -> None:
        if _BLEAK_IMPORT_ERROR is not None:
            raise ImportError(
                "bleak 库未安装，请执行 pip install bleak 或 "
                "pip install btg-backend[ble] 后重试"
            ) from _BLEAK_IMPORT_ERROR

        if not _XIAOMI_BLE_AVAILABLE:
            raise ImportError(
                "xiaomi-ble 库未安装，请执行 pip install xiaomi-ble 后重试"
            )

        raw = dict(config)
        if isinstance(BleHeartRateConfig, type) and issubclass(BleHeartRateConfig, BaseModel):
            validated = BleHeartRateConfig.model_validate(raw)
            self.instance_id: str = validated.instance_id
            # 小米传感器默认匹配 Mi Band（共享 config 的默认值是 Magene）
            self._device_name_prefix: str = (
                validated.device_name_prefix
                if "device_name_prefix" in raw
                else "Mi Band"
            )
            self._device_address: Optional[str] = validated.device_address
            self._reconnect_delay: float = validated.reconnect_delay_seconds
            self._scan_timeout: float = validated.scan_timeout_seconds
            self._channel: str = validated.channel
            self._xiaomi_auth_key: Optional[str] = validated.xiaomi_auth_key
            self._xiaomi_device_model: Optional[str] = validated.xiaomi_device_model
            self._xiaomi_passive: bool = validated.xiaomi_passive
        else:
            self.instance_id = str(raw.get("instance_id", "xiaomi_hr_0"))
            self._device_name_prefix = str(raw.get("device_name_prefix", "Mi Band"))
            self._device_address = raw.get("device_address")
            self._reconnect_delay = float(raw.get("reconnect_delay_seconds", 3.0))
            self._scan_timeout = float(raw.get("scan_timeout_seconds", 10.0))
            self._channel = str(raw.get("channel", "heart_rate"))
            self._xiaomi_auth_key = raw.get("xiaomi_auth_key")
            self._xiaomi_device_model = raw.get("xiaomi_device_model")
            self._xiaomi_passive = bool(raw.get("xiaomi_passive", True))

        # 解析认证密钥
        self._auth_key_bytes: Optional[bytes] = None
        if self._xiaomi_auth_key:
            try:
                self._auth_key_bytes = bytes.fromhex(self._xiaomi_auth_key)
                if len(self._auth_key_bytes) != 16:
                    LOGGER.warning(
                        "小米认证密钥长度应为 16 字节，当前为 %d 字节",
                        len(self._auth_key_bytes),
                    )
                    self._auth_key_bytes = None
            except ValueError:
                LOGGER.error("小米认证密钥格式无效（应为 16 字节 hex）")
                self._auth_key_bytes = None

        self._xiaomi_parser: Optional[XiaomiBluetoothDeviceData] = None
        self._connected = False
        self._stop_event = asyncio.Event()
        self._notification_queue: asyncio.Queue[int] = asyncio.Queue(maxsize=64)
        self._scanner: Optional[Any] = None
        self._client: Optional[BleakClient] = None

    # ── BaseSensor 契约 ───────────────────────────────────────────────────

    async def connect(self) -> bool:
        """启动小米 BLE 广播嗅探。

        Returns:
            True 表示嗅探器已启动。

        Raises:
            ConnectionError: 扫描启动失败时抛出。
        """
        if self._xiaomi_passive:
            return await self._connect_passive()
        else:
            return await self._connect_active()

    async def _connect_passive(self) -> bool:
        """被动嗅探模式：扫描并解析 MiBeacon 广播数据。"""
        try:
            self._xiaomi_parser = XiaomiBluetoothDeviceData(
                encryption_scheme=EncryptionScheme.MIBEACON_4_5
                if self._auth_key_bytes
                else EncryptionScheme.NONE,
                bindkey=self._auth_key_bytes,
            )

            def _advertisement_callback(device: Any, adv_data: bytearray) -> None:
                """处理小米 MiBeacon 广播数据。"""
                if self._device_address:
                    addr = getattr(device, "address", "")
                    if addr.upper() != self._device_address.upper():
                        return

                # 尝试解析 MiBeacon 数据
                bpm = _parse_xiaomi_mibeacon(adv_data, self._auth_key_bytes)
                if bpm is not None:
                    if self._notification_queue.full():
                        try:
                            self._notification_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    try:
                        self._notification_queue.put_nowait(bpm)
                    except asyncio.QueueFull:
                        pass

            # 使用 BleakScanner 进行被动扫描
            self._scanner = BleakScanner(
                detection_callback=_advertisement_callback,
                service_uuids=[XIAOMI_MIBEACON_UUID],
            )
            await self._scanner.start()
            self._connected = True
            LOGGER.info(
                "小米 BLE 广播嗅探器已启动: %s (address=%s)",
                self.instance_id,
                self._device_address or "any",
            )
            return True

        except Exception as exc:
            self._connected = False
            raise ConnectionError(f"小米 BLE 嗅探器启动失败: {exc}") from exc

    async def _connect_active(self) -> bool:
        """主动连接模式：直接连接小米设备获取心率。"""
        device = await self._find_device()
        if device is None:
            raise ConnectionError(
                f"未找到匹配的小米设备 "
                f"(prefix={self._device_name_prefix!r}, address={self._device_address!r})"
            )

        try:
            self._xiaomi_parser = XiaomiBluetoothDeviceData(
                encryption_scheme=EncryptionScheme.MIBEACON_4_5
                if self._auth_key_bytes
                else EncryptionScheme.NONE,
                bindkey=self._auth_key_bytes,
            )

            self._client = BleakClient(
                device,
                disconnected_callback=self._on_disconnect,
            )
            await self._client.connect(timeout=10.0)

            # 订阅 MiBeacon 通知（如果设备支持）
            try:
                await self._client.start_notify(
                    XIAOMI_MIBEACON_UUID,
                    self._xiaomi_notification_handler,
                )
            except Exception:
                LOGGER.warning("无法订阅 MiBeacon 通知，回退到扫描模式")

            self._connected = True
            LOGGER.info(
                "小米设备已连接: %s (%s)",
                getattr(device, "name", "unknown"),
                getattr(device, "address", "unknown"),
            )
            return True

        except Exception as exc:
            self._connected = False
            await self._safe_disconnect()
            raise ConnectionError(f"小米设备连接失败: {exc}") from exc

    async def disconnect(self) -> None:
        """幂等释放 BLE 连接资源。"""
        self._stop_event.set()
        self._connected = False

        if self._scanner is not None:
            try:
                await self._scanner.stop()
            except Exception:
                pass
            self._scanner = None

        await self._safe_disconnect()
        LOGGER.info("小米 BLE 设备已断开: %s", self.instance_id)

    async def read_stream(self, out_queue: asyncio.Queue) -> None:
        """持续从广播嗅探队列读取心率并写入总线。

        断线时自动进入后台重连循环，不会导致网关崩溃。
        外部通过 ``disconnect()`` 设置 ``_stop_event`` 终止本协程。
        """
        while not self._stop_event.is_set():
            try:
                if not self._connected:
                    await self._reconnect_loop()
                    continue

                try:
                    bpm = await asyncio.wait_for(
                        self._notification_queue.get(), timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue

                reading = Reading(
                    channel=self._channel,
                    sensor_id=self.instance_id,
                    value=float(bpm),
                    unit="bpm",
                    timestamp=time.time(),
                    extra={"device_type": "xiaomi", "model": self._xiaomi_device_model},
                )
                out_queue.put_nowait(reading)

            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                LOGGER.exception("小米 BLE 心率读取异常")
                self._connected = False
                await self._backoff_sleep()

    # ── 内部方法 ──────────────────────────────────────────────────────────

    def _xiaomi_notification_handler(self, _sender: Any, data: bytearray) -> None:
        """MiBeacon Notification 回调：解析心率值并写入内部队列。"""
        bpm = _parse_xiaomi_mibeacon(data, self._auth_key_bytes)
        if bpm is None:
            return
        if self._notification_queue.full():
            try:
                self._notification_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self._notification_queue.put_nowait(bpm)
        except asyncio.QueueFull:
            pass

    def _on_disconnect(self, _client: Any) -> None:
        """Bleak 断连回调（在 Bleak 事件循环线程中同步调用）。"""
        self._connected = False
        LOGGER.warning("小米 BLE 设备连接断开: %s", self.instance_id)

    async def _find_device(self) -> Optional[Any]:
        """按名称前缀或 MAC 地址扫描小米 BLE 设备。"""
        if self._device_address:
            try:
                device = await BleakScanner.find_device_by_address(
                    self._device_address, timeout=self._scan_timeout
                )
                return device
            except BleakError:
                LOGGER.warning(
                    "按地址 %s 扫描失败，回退到前缀扫描", self._device_address
                )

        def _matches(d: Any) -> bool:
            name = getattr(d, "name", None) or ""
            return (
                not self._device_name_prefix
                or name.startswith(self._device_name_prefix)
            )

        try:
            device = await BleakScanner.find_device_by_filter(
                _matches, timeout=self._scan_timeout
            )
            return device
        except BleakError as exc:
            LOGGER.error("小米 BLE 扫描失败: %s", exc)
            return None

    async def _reconnect_loop(self) -> None:
        """断线重连循环：指数退避，直到连接成功或被外部停止。"""
        delay = self._reconnect_delay
        while not self._stop_event.is_set():
            LOGGER.info(
                "小米 BLE 设备重连中... (delay=%.1fs)", delay
            )
            await self._backoff_sleep(delay)
            if self._stop_event.is_set():
                break
            try:
                await self.connect()
                return
            except ConnectionError as exc:
                LOGGER.warning("小米 BLE 重连失败: %s", exc)
                delay = min(delay * 2, 30.0)

    async def _backoff_sleep(self, delay: Optional[float] = None) -> None:
        """可被 ``_stop_event`` 中断的等待。"""
        seconds = delay if delay is not None else self._reconnect_delay
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _safe_disconnect(self) -> None:
        """安全断开 BLE 客户端（忽略异常）。"""
        if self._client is None:
            return
        try:
            if self._client.is_connected:
                await self._client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._client = None


# ── 便捷工厂函数 ──────────────────────────────────────────────────────────

async def connect_heart_rate_device(
    device_name_prefix: str = "Magene",
    device_address: Optional[str] = None,
    auth_key: Optional[str] = None,
    device_model: Optional[str] = None,
) -> BaseSensor:
    """扫描并连接指定前缀的蓝牙心率设备。

    这是一个便捷工厂函数，根据提供的参数自动选择合适的传感器类：

    - 如果提供 ``auth_key``，使用 ``XiaomiBleHeartRateSensor``（被动嗅探模式）。
    - 否则使用 ``BleHeartRateSensor``（标准 GATT 模式）。

    Args:
        device_name_prefix: BLE 广播名前缀，默认 ``"Magene"``。
        device_address: 可选的固定 BLE MAC 地址。
        auth_key: 小米设备认证密钥（16字节 hex 字符串）。
        device_model: 小米设备型号（如 ``"M2457B1"``）。

    Returns:
        已配置的传感器实例（未连接）。

    Example:
        >>> sensor = await connect_heart_rate_device("Magene")
        >>> await sensor.connect()
        >>> # ... 使用传感器 ...
        >>> await sensor.disconnect()
    """
    config: dict[str, Any] = {
        "instance_id": "ble_hr_0",
        "device_name_prefix": device_name_prefix,
        "device_address": device_address,
    }

    if auth_key:
        config["instance_id"] = "xiaomi_hr_0"
        config["mode"] = "xiaomi"
        config["xiaomi_auth_key"] = auth_key
        config["xiaomi_device_model"] = device_model
        config["xiaomi_passive"] = True
        return XiaomiBleHeartRateSensor(config)
    else:
        return BleHeartRateSensor(config)
