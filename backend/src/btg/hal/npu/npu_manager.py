"""NPU 硬件加速管理器：自动检测、后端切换与 CPU 降级。

本模块为 BTG 的视觉/推理管线提供统一的 NPU 抽象层，支持运行时
自动识别并切换不同的边缘 NPU 后端：

- **HailoNPUBackend**: 树莓派 Hailo-8/8L AI 加速器（通过 ``hailo_platform``）。
- **RKNNNPUBackend**: 瑞芯微 RK3588 内置 NPU（通过 ``rknn-toolkit2``）。
- **CPUFallbackBackend**: 未检测到 NPU 时自动降级为 OpenCV CPU 推理。

设计原则（与 BTG HAL 一致）：

1. **故障安全**：NPU 初始化/模型加载失败绝不崩溃，自动降级到 CPU。
2. **策略隔离**：上层只依赖 ``BaseNPUBackend`` 抽象接口，不 import 任何芯片 SDK。
3. **幂等生命周期**：``load_model()`` / ``unload()`` 可被重复调用。
4. **可配置优先级**：可通过配置强制指定后端，跳过自动检测。

使用示例::

    manager = NPUManager()
    await manager.auto_detect()
    await manager.load_model("yolo_v8n.onnx")
    result = await manager.infer(frame)
    await manager.unload()
"""
from __future__ import annotations

import abc
import asyncio
import logging
import os
import platform
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:  # pragma: no cover
    BaseModel = object  # type: ignore[assignment]
    ConfigDict = lambda **kw: None  # type: ignore[misc]
    Field = lambda **kw: None  # type: ignore[misc]

LOGGER = logging.getLogger(__name__)


# ── 后端类型枚举 ──────────────────────────────────────────────────────────


class NPUBackendType(str, Enum):
    """可用的 NPU 后端类型。"""

    HAILO = "hailo"
    RKNN = "rknn"
    CPU = "cpu"
    AUTO = "auto"


# ── 配置 ──────────────────────────────────────────────────────────────────


class NPUManagerConfig(BaseModel if BaseModel is not object else object):  # type: ignore[misc]
    """NPU 管理器配置。"""

    if BaseModel is not object:
        model_config = ConfigDict(extra="forbid")

    backend: NPUBackendType = Field(default=NPUBackendType.AUTO)  # type: ignore[call-arg]
    model_path: str = Field(default="", min_length=0)  # type: ignore[call-arg]
    input_shape: Tuple[int, int, int] = Field(default=(640, 640, 3))  # type: ignore[call-arg]
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)  # type: ignore[call-arg]
    max_batch_size: int = Field(default=1, ge=1)  # type: ignore[call-arg]
    hailo_device: str = "/dev/hailo0"
    rknn_model_ext: str = ".rknn"


# ── 推理结果 ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class InferenceResult:
    """单帧推理结果。"""

    detections: List[Dict[str, Any]]
    inference_time_ms: float
    backend_used: str
    input_shape: Tuple[int, int, int]
    timestamp: float = field(default_factory=time.time)


# ── 抽象基类 ──────────────────────────────────────────────────────────────


class BaseNPUBackend(abc.ABC):
    """NPU 后端抽象接口。

    所有后端必须实现 ``load_model`` / ``infer`` / ``unload`` / ``is_available``
    四个方法。``load_model`` 和 ``unload`` 必须幂等。
    """

    name: str = "base"

    @abc.abstractmethod
    async def is_available(self) -> bool:
        """检测当前后端是否可用（硬件存在 + 驱动就绪）。

        Returns:
            True 表示该后端可以在当前系统上运行。
        """
        ...

    @abc.abstractmethod
    async def load_model(self, model_path: str, **kwargs: Any) -> bool:
        """加载推理模型到 NPU。

        Args:
            model_path: 模型文件路径（ONNX / RKNN / HEF）。
            **kwargs: 后端特有参数（如 input_shape）。

        Returns:
            True 表示加载成功。

        Raises:
            RuntimeError: 模型加载失败（上层应捕获并降级）。
        """
        ...

    @abc.abstractmethod
    async def infer(self, frame: Any) -> InferenceResult:
        """对单帧图像执行推理。

        Args:
            frame: 输入图像（numpy ndarray, BGR, HWC）。

        Returns:
            InferenceResult 推理结果。
        """
        ...

    @abc.abstractmethod
    async def unload(self) -> None:
        """释放模型与 NPU 资源（幂等）。"""
        ...

    async def health(self) -> Dict[str, Any]:
        """返回后端健康状态。"""
        available = await self.is_available()
        return {
            "backend": self.name,
            "available": available,
            "status": "ok" if available else "unavailable",
        }


# ── Hailo NPU 后端 ────────────────────────────────────────────────────────


class HailoNPUBackend(BaseNPUBackend):
    """Hailo-8/8L AI 加速器后端（树莓派 5 + Hailo M.2 HAT）。

    依赖 ``hailo_platform``（Hailo 官方 Python API）。

    设备节点: ``/dev/hailo0``
    模型格式: ``.hef``（Hailo Efficient Format）
    """

    name = "hailo"

    def __init__(self, config: NPUManagerConfig) -> None:
        self._config = config
        self._hef: Any = None
        self._network_group: Any = None
        self._input_vstreams: Any = None
        self._output_vstreams: Any = None
        self._loaded = False
        self._ctx: Any = None

    async def is_available(self) -> bool:
        """检测 Hailo 设备节点与 Python SDK 是否就绪。"""
        if not os.path.exists(self._config.hailo_device):
            return False
        try:
            import importlib
            importlib.import_module("hailo_platform")
            return True
        except ImportError:
            return False

    async def load_model(self, model_path: str, **kwargs: Any) -> bool:
        """加载 .hef 模型到 Hailo NPU。

        Raises:
            RuntimeError: SDK 不可用或模型加载失败。
        """
        if self._loaded:
            return True

        try:
            from hailo_platform import (
                HEF,
                HailoStreamInterface,
                InferVStreams,
                InputVStreamParams,
                OutputVStreamParams,
                configure,
            )

            hef = HEF(model_path)
            interface = HailoStreamInterface.pcie()
            self._ctx = configure(interface, hef)

            input_vstream_params = InputVStreamParams.from_hef(
                hef, stream_sections=hef.get_input_sections()
            )
            output_vstream_params = OutputVStreamParams.from_hef(
                hef, stream_sections=hef.get_output_sections()
            )

            self._hef = hef
            self._input_vstreams = input_vstream_params
            self._output_vstreams = output_vstream_params
            self._loaded = True

            LOGGER.info("Hailo NPU 模型已加载: %s", model_path)
            return True

        except ImportError as exc:
            raise RuntimeError(
                "hailo_platform 未安装，请安装 Hailo SDK 后重试"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"Hailo NPU 模型加载失败: {exc}") from exc

    async def infer(self, frame: Any) -> InferenceResult:
        """通过 Hailo VStream 执行推理。"""
        if not self._loaded or self._ctx is None:
            raise RuntimeError("Hailo NPU 模型未加载")

        import numpy as np

        t0 = time.perf_counter()

        try:
            from hailo_platform import InferVStreams

            input_dict = {self._hef.get_input_sections()[0].name: frame}
            with InferVStreams(self._ctx, self._input_vstreams, self._output_vstreams) as infer_pipeline:
                raw_output = infer_pipeline.infer(input_dict)

            detections = self._postprocess(raw_output)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            return InferenceResult(
                detections=detections,
                inference_time_ms=round(elapsed_ms, 2),
                backend_used=self.name,
                input_shape=frame.shape,
            )

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            LOGGER.warning("Hailo NPU 推理异常: %s", exc)
            return InferenceResult(
                detections=[],
                inference_time_ms=round(elapsed_ms, 2),
                backend_used=self.name,
                input_shape=frame.shape,
            )

    async def unload(self) -> None:
        """释放 Hailo 资源（幂等）。"""
        self._hef = None
        self._network_group = None
        self._input_vstreams = None
        self._output_vstreams = None
        self._ctx = None
        self._loaded = False
        LOGGER.info("Hailo NPU 资源已释放")

    def _postprocess(self, raw_output: Any) -> List[Dict[str, Any]]:
        """将 Hailo 原始输出转换为标准检测结果。"""
        detections: List[Dict[str, Any]] = []
        try:
            for layer_name, output_tensor in raw_output.items():
                if output_tensor.ndim == 3:
                    for det in output_tensor[0]:
                        if len(det) >= 5:
                            conf = float(det[4])
                            if conf >= self._config.confidence_threshold:
                                detections.append({
                                    "class_id": int(det[5]) if len(det) > 5 else 0,
                                    "confidence": conf,
                                    "bbox": [float(det[0]), float(det[1]),
                                             float(det[2]), float(det[3])],
                                })
        except Exception:  # noqa: BLE001
            LOGGER.debug("Hailo 后处理跳过异常输出格式")
        return detections


# ── RKNN NPU 后端 ─────────────────────────────────────────────────────────


class RKNNNPUBackend(BaseNPUBackend):
    """瑞芯微 RK3588 内置 NPU 后端。

    依赖 ``rknn-toolkit2``（瑞芯微官方 Python API）。

    模型格式: ``.rknn``
    支持芯片: RK3588 / RK3588S / RK3576 等
    """

    name = "rknn"

    def __init__(self, config: NPUManagerConfig) -> None:
        self._config = config
        self._rknn: Any = None
        self._loaded = False

    async def is_available(self) -> bool:
        """检测 RKNN 驱动节点与 Python SDK 是否就绪。"""
        rknn_nodes = ["/dev/rknpu", "/dev/rknpu0", "/dev/rknpu_uts"]
        if not any(os.path.exists(n) for n in rknn_nodes):
            if platform.machine() not in ("aarch64", "armv7l"):
                return False
        try:
            import importlib
            importlib.import_module("rknn.api")
            return True
        except ImportError:
            return False

    async def load_model(self, model_path: str, **kwargs: Any) -> bool:
        """加载 .rknn 模型到 RKNN NPU。

        Raises:
            RuntimeError: SDK 不可用或模型加载失败。
        """
        if self._loaded:
            return True

        try:
            from rknn.api import RKNN

            rknn = RKNN(verbose=False)

            rknn.config(
                mean_values=[[0, 0, 0]],
                std_values=[[255, 255, 255]],
                target_platform="rk3588",
            )

            ret = rknn.load_rknn(model_path)
            if ret != 0:
                raise RuntimeError(f"rknn.load_rknn 失败 (ret={ret})")

            ret = rknn.init_runtime(target=None)
            if ret != 0:
                raise RuntimeError(f"rknn.init_runtime 失败 (ret={ret})")

            self._rknn = rknn
            self._loaded = True

            LOGGER.info("RKNN NPU 模型已加载: %s", model_path)
            return True

        except ImportError as exc:
            raise RuntimeError(
                "rknn-toolkit2 未安装，请安装瑞芯微 SDK 后重试"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"RKNN NPU 模型加载失败: {exc}") from exc

    async def infer(self, frame: Any) -> InferenceResult:
        """通过 RKNN Runtime 执行推理。"""
        if not self._loaded or self._rknn is None:
            raise RuntimeError("RKNN NPU 模型未加载")

        t0 = time.perf_counter()

        try:
            import numpy as np

            img = frame
            if img.shape[:2] != (self._config.input_shape[0], self._config.input_shape[1]):
                import cv2
                img = cv2.resize(
                    img,
                    (self._config.input_shape[1], self._config.input_shape[0]),
                )

            outputs = self._rknn.inference(inputs=[img])
            detections = self._postprocess(outputs)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            return InferenceResult(
                detections=detections,
                inference_time_ms=round(elapsed_ms, 2),
                backend_used=self.name,
                input_shape=frame.shape,
            )

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            LOGGER.warning("RKNN NPU 推理异常: %s", exc)
            return InferenceResult(
                detections=[],
                inference_time_ms=round(elapsed_ms, 2),
                backend_used=self.name,
                input_shape=frame.shape,
            )

    async def unload(self) -> None:
        """释放 RKNN 资源（幂等）。"""
        if self._rknn is not None:
            try:
                self._rknn.release()
            except Exception:  # noqa: BLE001
                pass
        self._rknn = None
        self._loaded = False
        LOGGER.info("RKNN NPU 资源已释放")

    def _postprocess(self, outputs: Any) -> List[Dict[str, Any]]:
        """将 RKNN 原始输出转换为标准检测结果。"""
        detections: List[Dict[str, Any]] = []
        try:
            for output in outputs:
                if output.ndim == 2:
                    for det in output:
                        if len(det) >= 5:
                            conf = float(det[4])
                            if conf >= self._config.confidence_threshold:
                                detections.append({
                                    "class_id": int(det[5]) if len(det) > 5 else 0,
                                    "confidence": conf,
                                    "bbox": [float(det[0]), float(det[1]),
                                             float(det[2]), float(det[3])],
                                })
        except Exception:  # noqa: BLE001
            LOGGER.debug("RKNN 后处理跳过异常输出格式")
        return detections


# ── CPU 降级后端 ──────────────────────────────────────────────────────────


class CPUFallbackBackend(BaseNPUBackend):
    """OpenCV CPU 推理降级后端（无 NPU 时自动启用）。

    使用 OpenCV 的 DNN 模块在 CPU 上执行推理，作为所有 NPU 不可用时
    的保底方案。支持 ONNX / Caffe / TensorFlow 等格式。
    """

    name = "cpu"

    def __init__(self, config: NPUManagerConfig) -> None:
        self._config = config
        self._net: Any = None
        self._loaded = False
        self._model_path: str = ""

    async def is_available(self) -> bool:
        """CPU 后端始终可用。"""
        return True

    async def load_model(self, model_path: str, **kwargs: Any) -> bool:
        """通过 OpenCV DNN 加载模型。"""
        if self._loaded:
            return True

        try:
            import cv2

            ext = Path(model_path).suffix.lower()

            if ext == ".onnx":
                self._net = cv2.dnn.readNetFromONNX(model_path)
            elif ext in (".prototxt", ".caffemodel"):
                self._net = cv2.dnn.readNetFromCaffe(
                    model_path if ext == ".prototxt" else "",
                    model_path if ext == ".caffemodel" else "",
                )
            elif ext == ".tflite":
                self._net = cv2.dnn.readNetFromTFLite(model_path)
            elif ext == ".pb":
                self._net = cv2.dnn.readNetFromTensorflow(model_path)
            else:
                self._net = cv2.dnn.readNetFromONNX(model_path)

            self._net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self._net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

            self._model_path = model_path
            self._loaded = True
            LOGGER.info("CPU 后端模型已加载: %s", model_path)
            return True

        except ImportError:
            raise RuntimeError("OpenCV 未安装，请执行 pip install opencv-python")
        except Exception as exc:
            raise RuntimeError(f"CPU 后端模型加载失败: {exc}") from exc

    async def infer(self, frame: Any) -> InferenceResult:
        """通过 OpenCV DNN 执行 CPU 推理。"""
        if not self._loaded or self._net is None:
            raise RuntimeError("CPU 后端模型未加载")

        t0 = time.perf_counter()

        try:
            import cv2
            import numpy as np

            blob = cv2.dnn.blobFromImage(
                frame,
                scalefactor=1.0 / 255.0,
                size=(self._config.input_shape[1], self._config.input_shape[0]),
                swapRB=True,
                crop=False,
            )
            self._net.setInput(blob)
            outputs = self._net.forward()

            detections = self._postprocess(outputs)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            return InferenceResult(
                detections=detections,
                inference_time_ms=round(elapsed_ms, 2),
                backend_used=self.name,
                input_shape=frame.shape,
            )

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            LOGGER.warning("CPU 后端推理异常: %s", exc)
            return InferenceResult(
                detections=[],
                inference_time_ms=round(elapsed_ms, 2),
                backend_used=self.name,
                input_shape=frame.shape,
            )

    async def unload(self) -> None:
        """释放 OpenCV DNN 模型（幂等）。"""
        self._net = None
        self._loaded = False
        LOGGER.info("CPU 后端模型已释放")

    def _postprocess(self, outputs: Any) -> List[Dict[str, Any]]:
        """将 OpenCV DNN 输出转换为标准检测结果。"""
        detections: List[Dict[str, Any]] = []
        try:
            if outputs.ndim == 3:
                for det in outputs[0]:
                    if len(det) >= 5:
                        conf = float(det[4])
                        if conf >= self._config.confidence_threshold:
                            detections.append({
                                "class_id": int(det[5]) if len(det) > 5 else 0,
                                "confidence": conf,
                                "bbox": [float(det[0]), float(det[1]),
                                         float(det[2]), float(det[3])],
                            })
        except Exception:  # noqa: BLE001
            LOGGER.debug("CPU 后处理跳过异常输出格式")
        return detections


# ── NPU 管理器 ────────────────────────────────────────────────────────────


class NPUManager:
    """NPU 管理器：自动检测硬件、选择最优后端、管理生命周期。

    使用::

        manager = NPUManager()
        await manager.auto_detect()
        await manager.load_model("model.onnx")
        result = await manager.infer(frame)
        await manager.unload()

    或通过配置强制指定后端::

        manager = NPUManager(config=NPUManagerConfig(backend=NPUBackendType.RKNN))
    """

    def __init__(
        self,
        config: Optional[NPUManagerConfig] = None,
        *,
        backends: Optional[List[BaseNPUBackend]] = None,
    ) -> None:
        self._config = config or NPUManagerConfig()
        self._backends: List[BaseNPUBackend] = backends or [
            HailoNPUBackend(self._config),
            RKNNNPUBackend(self._config),
            CPUFallbackBackend(self._config),
        ]
        self._active: Optional[BaseNPUBackend] = None
        self._detection_done = False

    @property
    def active_backend(self) -> Optional[BaseNPUBackend]:
        """当前激活的 NPU 后端。"""
        return self._active

    @property
    def active_backend_name(self) -> str:
        """当前激活后端名称。"""
        return self._active.name if self._active else "none"

    async def auto_detect(self) -> str:
        """自动检测硬件并选择最优 NPU 后端。

        检测顺序: Hailo → RKNN → CPU（按性能降序）。
        如果配置中指定了具体后端（非 AUTO），直接尝试该后端。

        Returns:
            最终激活的后端名称。
        """
        if self._config.backend != NPUBackendType.AUTO:
            target_name = self._config.backend.value
            LOGGER.info("配置指定后端: %s", target_name)
            for backend in self._backends:
                if backend.name == target_name:
                    try:
                        if await backend.is_available():
                            self._active = backend
                            self._detection_done = True
                            LOGGER.info("已激活指定后端: %s", target_name)
                            return target_name
                    except Exception:  # noqa: BLE001
                        LOGGER.warning("指定后端 %s 不可用，尝试降级", target_name)
                    break

        for backend in self._backends:
            try:
                if await backend.is_available():
                    self._active = backend
                    self._detection_done = True
                    LOGGER.info("自动检测到可用后端: %s", backend.name)
                    return backend.name
            except Exception:  # noqa: BLE001
                LOGGER.warning("后端 %s 检测失败，跳过", backend.name)
                continue

        for backend in self._backends:
            if isinstance(backend, CPUFallbackBackend):
                self._active = backend
                self._detection_done = True
                LOGGER.warning("所有 NPU 不可用，已降级到 CPU 后端")
                return backend.name

        LOGGER.critical("无任何可用后端（包括 CPU 降级）")
        return "none"

    async def load_model(self, model_path: str, **kwargs: Any) -> bool:
        """加载模型到当前激活的后端。

        如果加载失败，自动降级到 CPU 后端重试。

        Returns:
            True 表示至少有一个后端加载成功。
        """
        if self._active is None:
            await self.auto_detect()

        if self._active is None:
            LOGGER.error("无可用后端，无法加载模型")
            return False

        try:
            return await self._active.load_model(model_path, **kwargs)
        except RuntimeError as exc:
            LOGGER.warning(
                "后端 %s 模型加载失败: %s，尝试 CPU 降级",
                self._active.name,
                exc,
            )
            return await self._fallback_to_cpu_and_load(model_path, **kwargs)

    async def infer(self, frame: Any) -> InferenceResult:
        """对单帧图像执行推理。"""
        if self._active is None:
            raise RuntimeError("NPU 管理器未初始化，请先调用 auto_detect()")
        return await self._active.infer(frame)

    async def unload(self) -> None:
        """释放当前后端的模型资源（幂等）。"""
        if self._active is not None:
            await self._active.unload()

    async def health(self) -> Dict[str, Any]:
        """返回管理器与当前后端的健康状态。"""
        backend_health = {}
        if self._active is not None:
            backend_health = await self._active.health()

        return {
            "manager_initialized": self._detection_done,
            "active_backend": self.active_backend_name,
            "available_backends": [
                b.name for b in self._backends
            ],
            **backend_health,
        }

    async def _fallback_to_cpu_and_load(
        self, model_path: str, **kwargs: Any
    ) -> bool:
        """降级到 CPU 后端并加载模型。"""
        for backend in self._backends:
            if isinstance(backend, CPUFallbackBackend) or backend.name == "cpu":
                try:
                    self._active = backend
                    return await backend.load_model(model_path, **kwargs)
                except RuntimeError as exc:
                    LOGGER.error("CPU 降级也失败: %s", exc)
                    return False
        return False
