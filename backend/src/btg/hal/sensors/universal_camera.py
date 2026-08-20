"""多协议万能视频源适配器 (Universal Video Stream Adapter)。

通过 ``@register_sensor("universal_camera")`` 登记，支持通过统一的配置
文件切换并接入 USB 摄像头、RTSP 网络流或 ONVIF 局域网智能摄像头。

配置项（通过 ``devices.yaml`` 注入）：

- ``instance_id``: 传感器实例 ID，默认 ``"universal_camera_0"``。
- ``source_type``: 视频源类型，可选 ``"usb"``、``"rtsp"``、``"onvif"``。
- ``usb_index``: USB 摄像头设备索引，仅 ``source_type="usb"`` 时有效，默认 ``0``。
- ``rtsp_url``: RTSP 流地址，仅 ``source_type="rtsp"`` 时有效。
- ``onvif_ip``: ONVIF 设备 IP 地址，仅 ``source_type="onvif"`` 时有效。
- ``onvif_port``: ONVIF 设备端口，默认 ``80``。
- ``onvif_user``: ONVIF 用户名，默认空字符串（无鉴权）。
- ``onvif_pass``: ONVIF 密码，默认空字符串。
- ``onvif_profile``: ONVIF 流配置，可选 ``"main"`` 或 ``"sub"``，默认 ``"main"``。
- ``frame_interval``: 帧采样间隔（秒），默认 ``0.33``（约 3 FPS）。
- ``output_path``: 帧输出文件路径，默认 ``"latest.jpg"``。
- ``reconnect_delay_seconds``: 断线重连等待秒数，仅网络源有效，默认 ``5.0``。
- ``channel``: 逻辑通道名，默认 ``"camera_frame"``。
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Optional

from btg_sdk import BaseSensor, Reading, register_sensor

try:
    import cv2
    import numpy as np
except ImportError as exc:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    _CV2_IMPORT_ERROR: ImportError | None = exc
else:
    _CV2_IMPORT_ERROR = None

try:
    from onvif import ONVIFCamera
except ImportError as exc:  # pragma: no cover
    ONVIFCamera = None  # type: ignore[assignment]
    _ONVIF_IMPORT_ERROR: ImportError | None = exc
else:
    _ONVIF_IMPORT_ERROR = None

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:  # pragma: no cover
    BaseModel = object  # type: ignore[assignment]
    ConfigDict = lambda **kw: None  # type: ignore[misc]
    Field = lambda **kw: None  # type: ignore[misc]

LOGGER = logging.getLogger(__name__)

_SOURCE_TYPE_USB = "usb"
_SOURCE_TYPE_RTSP = "rtsp"
_SOURCE_TYPE_ONVIF = "onvif"
_VALID_SOURCE_TYPES = (_SOURCE_TYPE_USB, _SOURCE_TYPE_RTSP, _SOURCE_TYPE_ONVIF)


class UniversalCameraConfig(BaseModel if BaseModel is not object else object):  # type: ignore[misc]
    """万能视频源适配器的严格配置边界。"""

    if BaseModel is not object:
        model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(default="universal_camera_0", min_length=1)  # type: ignore[call-arg]
    source_type: str = Field(default=_SOURCE_TYPE_USB, pattern=r"^(usb|rtsp|onvif)$")  # type: ignore[call-arg]
    usb_index: int = Field(default=0, ge=0)  # type: ignore[call-arg]
    rtsp_url: str = ""
    onvif_ip: str = ""
    onvif_port: int = Field(default=80, ge=1, le=65535)  # type: ignore[call-arg]
    onvif_user: str = ""
    onvif_pass: str = ""
    onvif_profile: str = Field(default="main", pattern=r"^(main|sub)$")  # type: ignore[call-arg]
    frame_interval: float = Field(default=0.33, gt=0.0, le=5.0)  # type: ignore[call-arg]
    output_path: str = "latest.jpg"
    reconnect_delay_seconds: float = Field(default=5.0, ge=1.0, le=60.0)  # type: ignore[call-arg]
    channel: str = "camera_frame"


def _atomic_write_jpeg(data: bytes, path: Path) -> None:
    """以原子方式将 JPEG 数据写入目标路径。

    先写入同目录下的临时文件，再通过 rename 保证上层读取者
    要么看到完整的旧帧，要么看到完整的新帧。
    """
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, suffix=".tmp", prefix=".cam_"
    )
    try:
        with open(tmp_fd, "wb") as f:
            f.write(data)
            f.flush()
            import os
            os.fsync(f.fileno())
        Path(tmp_path).replace(path)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise


@register_sensor("universal_camera")
class UniversalCameraSensor(BaseSensor):
    """多协议万能视频源适配器。

    根据 ``source_type`` 配置项，动态选择 USB / RTSP / ONVIF 协议接入
    摄像头，并以统一的异步循环将画面拉取下来，实时将最新帧以原子化
    方式覆写保存为本地 ``latest.jpg``，供上层 Mode 0/1/2 视觉代理使用。

    实现 ``BaseSensor`` 契约：
    - ``connect()``: 初始化视频源连接。
    - ``read_stream()``: 持续采集帧并写入 ``out_queue`` 与本地文件。
    - ``disconnect()``: 释放视频源资源。
    """

    def __init__(self, config: Mapping[str, Any]) -> None:
        if _CV2_IMPORT_ERROR is not None:
            raise ImportError(
                "OpenCV 库未安装，请执行 pip install opencv-python-headless "
                "或 pip install btg-backend[vision] 后重试"
            ) from _CV2_IMPORT_ERROR

        raw = dict(config)
        if isinstance(UniversalCameraConfig, type) and issubclass(
            UniversalCameraConfig, BaseModel
        ):
            validated = UniversalCameraConfig.model_validate(raw)
            self.instance_id: str = validated.instance_id
            self._source_type: str = validated.source_type
            self._usb_index: int = validated.usb_index
            self._rtsp_url: str = validated.rtsp_url
            self._onvif_ip: str = validated.onvif_ip
            self._onvif_port: int = validated.onvif_port
            self._onvif_user: str = validated.onvif_user
            self._onvif_pass: str = validated.onvif_pass
            self._onvif_profile: str = validated.onvif_profile
            self._frame_interval: float = validated.frame_interval
            self._output_path: Path = Path(validated.output_path).resolve()
            self._reconnect_delay: float = validated.reconnect_delay_seconds
            self._channel: str = validated.channel
        else:
            self.instance_id = str(raw.get("instance_id", "universal_camera_0"))
            self._source_type = str(raw.get("source_type", _SOURCE_TYPE_USB))
            self._usb_index = int(raw.get("usb_index", 0))
            self._rtsp_url = str(raw.get("rtsp_url", ""))
            self._onvif_ip = str(raw.get("onvif_ip", ""))
            self._onvif_port = int(raw.get("onvif_port", 80))
            self._onvif_user = str(raw.get("onvif_user", ""))
            self._onvif_pass = str(raw.get("onvif_pass", ""))
            self._onvif_profile = str(raw.get("onvif_profile", "main"))
            self._frame_interval = float(raw.get("frame_interval", 0.33))
            self._output_path = Path(raw.get("output_path", "latest.jpg")).resolve()
            self._reconnect_delay = float(raw.get("reconnect_delay_seconds", 5.0))
            self._channel = str(raw.get("channel", "camera_frame"))

        if self._source_type not in _VALID_SOURCE_TYPES:
            raise ValueError(
                f"不支持的 source_type: {self._source_type!r}，"
                f"可选值: {_VALID_SOURCE_TYPES}"
            )

        self._cap: Any = None
        self._onvif_cam: Any = None
        self._connected = False
        self._stop_event = asyncio.Event()
        self._rtsp_url_resolved: Optional[str] = None

    # ── BaseSensor 契约 ───────────────────────────────────────────────────

    async def connect(self) -> bool:
        """建立视频源连接。

        Returns:
            True 表示连接成功。

        Raises:
            ConnectionError: 无法建立连接时抛出。
        """
        if self._source_type == _SOURCE_TYPE_USB:
            return await self._connect_usb()
        elif self._source_type == _SOURCE_TYPE_RTSP:
            return await self._connect_rtsp(self._rtsp_url)
        elif self._source_type == _SOURCE_TYPE_ONVIF:
            return await self._connect_onvif()
        raise RuntimeError("unreachable")

    async def disconnect(self) -> None:
        """幂等释放视频源资源。"""
        self._stop_event.set()
        self._connected = False
        self._release_capture()
        LOGGER.info("视频源已断开: %s", self.instance_id)

    async def read_stream(self, out_queue: asyncio.Queue) -> None:
        """持续采集帧并推送到总线与本地文件。

        断线时自动进入指数退避重连循环，不会导致网关崩溃。
        """
        while not self._stop_event.is_set():
            try:
                if not self._connected:
                    await self._reconnect_loop()
                    continue

                frame = await self._grab_frame()
                if frame is None:
                    LOGGER.warning("视频帧为空，尝试重连: %s", self.instance_id)
                    self._connected = False
                    self._release_capture()
                    continue

                jpeg_bytes = await self._encode_jpeg(frame)
                if jpeg_bytes is not None:
                    _atomic_write_jpeg(jpeg_bytes, self._output_path)

                reading = Reading(
                    channel=self._channel,
                    sensor_id=self.instance_id,
                    value=float(frame.shape[0] * frame.shape[1]),
                    unit="pixels",
                    timestamp=time.time(),
                    extra={
                        "width": frame.shape[1],
                        "height": frame.shape[0],
                        "output_path": str(self._output_path),
                    },
                )
                out_queue.put_nowait(reading)

                await asyncio.sleep(self._frame_interval)

            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                LOGGER.exception("视频帧采集异常: %s", self.instance_id)
                self._connected = False
                self._release_capture()
                await self._backoff_sleep()

    # ── USB 连接 ──────────────────────────────────────────────────────────

    async def _connect_usb(self) -> bool:
        """打开本地 USB 摄像头。"""
        try:
            cap = cv2.VideoCapture(self._usb_index)
            if not cap.isOpened():
                raise ConnectionError(
                    f"无法打开 USB 摄像头 (index={self._usb_index})"
                )
            self._cap = cap
            self._connected = True
            LOGGER.info(
                "USB 摄像头已连接: %s (index=%d)", self.instance_id, self._usb_index
            )
            return True
        except Exception as exc:
            self._connected = False
            raise ConnectionError(f"USB 摄像头连接失败: {exc}") from exc

    # ── RTSP 连接 ─────────────────────────────────────────────────────────

    async def _connect_rtsp(self, url: str) -> bool:
        """拉取标准 RTSP 网络流。"""
        try:
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                raise ConnectionError(f"无法连接 RTSP 流: {url}")
            self._cap = cap
            self._rtsp_url_resolved = url
            self._connected = True
            LOGGER.info("RTSP 流已连接: %s", self.instance_id)
            return True
        except Exception as exc:
            self._connected = False
            raise ConnectionError(f"RTSP 流连接失败: {exc}") from exc

    # ── ONVIF 连接 ────────────────────────────────────────────────────────

    async def _connect_onvif(self) -> bool:
        """通过 ONVIF 协议发现设备并获取 RTSP 播放地址。"""
        if ONVIFCamera is None:
            raise ImportError(
                "onvif-python 库未安装，请执行 pip install onvif-python "
                "或 pip install btg-backend[onvif] 后重试"
            ) from _ONVIF_IMPORT_ERROR

        try:
            self._onvif_cam = ONVIFCamera(
                self._onvif_ip, self._onvif_port,
                self._onvif_user, self._onvif_pass,
            )

            media_service = self._onvif_cam.create_media_service()
            profiles = media_service.GetProfiles()

            target_profile = None
            for profile in profiles:
                token = getattr(profile, "token", "")
                name = getattr(profile, "name", "")
                if self._onvif_profile == "main" and "main" in name.lower():
                    target_profile = profile
                    break
                elif self._onvif_profile == "sub" and "sub" in name.lower():
                    target_profile = profile
                    break
                elif "main" in name.lower():
                    target_profile = profile

            if target_profile is None and profiles:
                target_profile = profiles[0]

            if target_profile is None:
                raise ConnectionError("ONVIF 设备无可用流配置")

            stream_setup = {
                "Stream": "RTP-Unicast",
                "Transport": {"Protocol": "RTSP"},
            }
            uri_response = media_service.GetStreamUri(
                StreamSetup=stream_setup,
                ProfileToken=target_profile.token,
            )
            rtsp_url = uri_response.Uri

            if rtsp_url.startswith("rtsp://") is False:
                if self._onvif_user and self._onvif_pass:
                    rtsp_url = rtsp_url.replace(
                        "rtsp://",
                        f"rtsp://{self._onvif_user}:{self._onvif_pass}@",
                        1,
                    )

            LOGGER.info(
                "ONVIF 设备 RTSP 地址已获取: %s -> %s",
                self.instance_id, rtsp_url,
            )
            return await self._connect_rtsp(rtsp_url)

        except ConnectionError:
            raise
        except Exception as exc:
            self._connected = False
            raise ConnectionError(f"ONVIF 设备连接失败: {exc}") from exc

    # ── 帧采集与编码 ──────────────────────────────────────────────────────

    async def _grab_frame(self) -> Any:
        """从视频源异步抓取一帧。

        Returns:
            BGR 格式的 numpy 数组，若抓取失败返回 None。
        """
        if self._cap is None or not self._cap.isOpened():
            return None

        loop = asyncio.get_running_loop()

        def _read_sync() -> Any:
            ret, frame = self._cap.read()  # type: ignore[union-attr]
            return frame if ret else None

        return await loop.run_in_executor(None, _read_sync)

    def _release_capture(self) -> None:
        """安全释放 OpenCV VideoCapture 资源。"""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None

    async def _encode_jpeg(self, frame: Any) -> Optional[bytes]:
        """将 BGR 帧编码为 JPEG 字节流。"""
        if frame is None or frame.size == 0:
            return None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes(),
        )

    # ── 重连逻辑 ──────────────────────────────────────────────────────────

    async def _reconnect_loop(self) -> None:
        """断线重连循环：指数退避，直到连接成功或被外部停止。"""
        delay = self._reconnect_delay
        while not self._stop_event.is_set():
            LOGGER.info("视频源重连中... (delay=%.1fs)", delay)
            await self._backoff_sleep(delay)
            if self._stop_event.is_set():
                break
            try:
                await self.connect()
                LOGGER.info("视频源重连成功: %s", self.instance_id)
                return
            except ConnectionError as exc:
                LOGGER.warning("视频源重连失败: %s", exc)
                delay = min(delay * 2, 60.0)

    async def _backoff_sleep(self, delay: Optional[float] = None) -> None:
        """可被 ``_stop_event`` 中断的等待。"""
        seconds = delay if delay is not None else self._reconnect_delay
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
