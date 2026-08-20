"""相机运行态管理器：命名视频源（USB / RTSP）的启停、取流、算法与状态。

``CameraRuntime`` 是独立于遥测采集管线的可控视频层：

- 维护相机定义（持久化到 YAML，含算法模式）；
- ``start``/``stop`` 每个相机的后台采集任务；
- 缓存最新帧（JPEG 字节）供前端轮询预览，并缓存结构化的运动/挣扎指标；
- 支持运行时在帧差运动检测与 MediaPipe Pose 之间切换算法。

OpenCV 未安装时，相机清单仍可增删改查，仅启动采集会返回明确的依赖错误。
PyYAML 未安装时读取/保存相机定义会降级为仅内存（进程内有效）。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

try:
    import yaml
except ImportError:  # pragma: no cover - 可选依赖
    yaml = None  # type: ignore[assignment]

try:
    import cv2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - 可选依赖
    cv2 = None  # type: ignore[assignment]
    _CV2_IMPORT_ERROR: Optional[ImportError] = ImportError(
        "OpenCV 未安装，请 pip install opencv-python-headless 或 btg-backend[vision]"
    )
else:
    _CV2_IMPORT_ERROR = None

from btg.hal.algorithms.video_processor import VideoProcessor

LOGGER = logging.getLogger(__name__)
_JPEG_QUALITY = 85


class CameraDef(BaseModel):
    """相机的持久化定义与启动约束。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    source_type: str = Field(default="usb", pattern=r"^(usb|rtsp)$")
    usb_index: int = Field(default=0, ge=0)
    rtsp_url: str = ""
    algorithm_mode: str = Field(default="classical_motion")
    auto_start: bool = Field(default=False)


def _read_jpeg(frame: Any) -> bytes:
    return cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])[1].tobytes()


def _read_capture(cap: Any) -> Any:
    ok, frame = cap.read()
    return frame if ok else None


class CameraRuntime:
    """摄像头运行态的进程内管理器（单事件循环线程安全设计）。"""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self._config_path = Path(config_path) if config_path else Path("cameras.yaml")
        # name -> CameraDef（持久化定义）
        self._defs: Dict[str, CameraDef] = {}
        # name -> 运行时状态（仅事件循环线程读写）
        self._state: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._load()

    # ------------------------------------------------------------------ #
    # 相机定义（持久化）
    # ------------------------------------------------------------------ #
    def cameras(self) -> List[dict]:
        """返回「定义 + 运行态」合并清单，供前端渲染。"""
        with self._lock:
            names = list(self._defs)
            defs = {n: d.model_dump() for n, d in self._defs.items()}
        result = []
        for name in names:
            st = self._state.get(name)
            result.append({
                **defs[name],
                "state": st["state"] if st else "stopped",
                "error": st.get("error") if st else None,
                "last_frame_at": st.get("last_frame_time") if st else None,
                "algorithm_used": st.get("algorithm_used") if st else None,
                "metrics": st.get("metrics") if st else None,
            })
        return result

    def add_camera(self, camera: CameraDef) -> CameraDef:
        with self._lock:
            if camera.name in self._defs:
                # 视为更新，保留定义但不动运行态
                self._defs[camera.name] = camera
            else:
                self._defs[camera.name] = camera
            self._save()
        return camera

    def remove_camera(self, name: str) -> bool:
        removed = False
        with self._lock:
            if name in self._defs:
                del self._defs[name]
                removed = True
                self._save()
        if removed:
            self._state.pop(name, None)
        return removed

    def get(self, name: str) -> Optional[CameraDef]:
        with self._lock:
            camera = self._defs.get(name)
            return camera.model_copy() if camera else None

    # ------------------------------------------------------------------ #
    # 运行态
    # ------------------------------------------------------------------ #
    async def start(self, name: str) -> None:
        """启动一个相机的后台采集任务（已在运行则忽略）。"""
        camera = self.get(name)
        if camera is None:
            raise KeyError(f"相机未定义: {name}")
        existing = self._state.get(name)
        if existing and existing.get("task") and not existing["task"].done():
            return
        if _CV2_IMPORT_ERROR is not None:
            raise RuntimeError(
                f"视觉后端不可用: {_CV2_IMPORT_ERROR}"  # type: ignore[str-format]
            )
        self._state[name] = {
            "state": "starting",
            "error": None,
            "task": None,
            "last_frame": None,
            "last_frame_time": None,
            "metrics": None,
            "metrics_time": None,
            "algorithm_used": None,
            "algo_target": camera.algorithm_mode,
        }
        task = asyncio.create_task(self._capture_loop(name, camera))
        self._state[name]["task"] = task

    async def stop(self, name: str) -> None:
        """停止相机采集任务（幂等）。"""
        st = self._state.get(name)
        if not st:
            return
        task = st.get("task")
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._state.get(name, {}).update({"state": "stopped", "task": None})

    async def stop_all(self) -> None:
        """停止全部运行中的相机（网关停机时调用）。"""
        for name in list(self._state):
            await self.stop(name)

    def latest_frame(self, name: str) -> Optional[bytes]:
        st = self._state.get(name)
        return st.get("last_frame") if st else None

    def metrics(self, name: str) -> Optional[dict]:
        st = self._state.get(name)
        return st.get("metrics") if st else None

    def state_of(self, name: str) -> dict:
        st = self._state.get(name)
        return {
            "state": st["state"] if st else "stopped",
            "error": st.get("error") if st else None,
            "last_frame_at": st.get("last_frame_time") if st else None,
            "algorithm_used": st.get("algorithm_used") if st else None,
            "metrics": st.get("metrics") if st else None,
        }

    async def set_algorithm(self, name: str, mode: str) -> str:
        """请求切换算法模式；仅记录目标，由采集循环下次收敛。"""
        st = self._state.get(name)
        if not st:
            raise KeyError(f"相机未运行: {name}")
        st["algo_target"] = mode
        # 短暂等待采集循环收敛（最快一次循环内生效）
        for _ in range(20):
            if st.get("algorithm_used") == mode or st.get("error"):
                break
            await asyncio.sleep(0.05)
        return st.get("algorithm_used") or st.get("algo_target")

    # ------------------------------------------------------------------ #
    # 采集循环
    # ------------------------------------------------------------------ #
    async def _capture_loop(self, name: str, camera: CameraDef) -> None:
        st = self._state.get(name)
        proc = VideoProcessor(config={"algorithm_mode": camera.algorithm_mode})
        cap: Any = None
        try:
            source = (
                camera.usb_index if camera.source_type == "usb" else camera.rtsp_url
            )
            cap = cv2.VideoCapture(source)
            if not cap.isOpened():
                raise ConnectionError(
                    f"无法打开视频源: {camera.source_type} {source}"
                )
            st["state"] = "running"
            st["error"] = None
            loop = asyncio.get_running_loop()
            while True:
                # 算法模式收敛（幂等）
                if proc.algorithm_mode != st["algo_target"]:
                    proc.set_algorithm_mode(st["algo_target"])
                    st["algorithm_used"] = proc.algorithm_mode

                frame = await loop.run_in_executor(None, _read_capture, cap)
                if frame is None:
                    st["error"] = "帧读取为空（视频源中断）"
                    await asyncio.sleep(0.5)
                    continue

                now = time.time()
                jpeg = await loop.run_in_executor(None, _read_jpeg, frame)
                st["last_frame"] = jpeg
                st["last_frame_time"] = now

                metrics = await loop.run_in_executor(
                    None, lambda f=frame, t=now: proc.process_frame(f, timestamp=t),
                )
                st["metrics"] = metrics
                st["metrics_time"] = now
                st["error"] = None
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 单相机失败不崩溃
            LOGGER.exception("相机采集循环异常 name=%s", name)
            st["state"] = "error"
            st["error"] = str(exc)
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:  # pragma: no cover
                    pass
            proc.close()
            current = self._state.get(name)
            if current is not None:
                current["task"] = None

    # ------------------------------------------------------------------ #
    # 持久化
    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        if yaml is None:
            LOGGER.warning("PyYAML 未安装，相机定义仅存内存")
            return
        if not self._config_path.exists():
            return
        try:
            raw = yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}
            for item in raw.get("cameras", []):
                self._defs[item["name"]] = CameraDef(**item)
        except Exception as exc:  # pragma: no cover - 配置损坏兜底
            LOGGER.error("相机配置读取失败 %s: %s", self._config_path, exc)

    def _save(self) -> None:
        if yaml is None:
            return
        payload = {"cameras": [c.model_dump() for c in self._defs.values()]}
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._config_path.with_suffix(".tmp")
            tmp.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
            tmp.replace(self._config_path)
        except Exception as exc:  # pragma: no cover
            LOGGER.error("相机配置保存失败 %s: %s", self._config_path, exc)