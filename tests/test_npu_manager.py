"""Tests for the NPU Manager and backends."""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from btg.hal.npu.npu_manager import (
    BaseNPUBackend,
    CPUFallbackBackend,
    HailoNPUBackend,
    InferenceResult,
    NPUBackendType,
    NPUManager,
    NPUManagerConfig,
    RKNNNPUBackend,
)


# ── Config ────────────────────────────────────────────────────────────────


class TestNPUManagerConfig:
    """配置模型校验。"""

    def test_default_config(self):
        cfg = NPUManagerConfig()
        assert cfg.backend == NPUBackendType.AUTO
        assert cfg.input_shape == (640, 640, 3)
        assert cfg.confidence_threshold == 0.5
        assert cfg.max_batch_size == 1

    def test_custom_config(self):
        cfg = NPUManagerConfig(
            backend=NPUBackendType.RKNN,
            input_shape=(320, 320, 3),
            confidence_threshold=0.7,
        )
        assert cfg.backend == NPUBackendType.RKNN
        assert cfg.input_shape == (320, 320, 3)
        assert cfg.confidence_threshold == 0.7


# ── InferenceResult ───────────────────────────────────────────────────────


class TestInferenceResult:
    """推理结果数据类。"""

    def test_creation(self):
        r = InferenceResult(
            detections=[{"class_id": 0, "confidence": 0.9, "bbox": [0, 0, 1, 1]}],
            inference_time_ms=12.5,
            backend_used="cpu",
            input_shape=(640, 640, 3),
        )
        assert len(r.detections) == 1
        assert r.inference_time_ms == 12.5
        assert r.backend_used == "cpu"

    def test_empty_detections(self):
        r = InferenceResult(
            detections=[],
            inference_time_ms=5.0,
            backend_used="hailo",
            input_shape=(640, 640, 3),
        )
        assert r.detections == []


# ── BackendType ───────────────────────────────────────────────────────────


class TestNPUBackendType:
    """后端类型枚举。"""

    def test_values(self):
        assert NPUBackendType.HAILO == "hailo"
        assert NPUBackendType.RKNN == "rknn"
        assert NPUBackendType.CPU == "cpu"
        assert NPUBackendType.AUTO == "auto"


# ── CPUFallbackBackend ────────────────────────────────────────────────────


class TestCPUFallbackBackend:
    """CPU 降级后端测试。"""

    def test_always_available(self):
        cfg = NPUManagerConfig()
        backend = CPUFallbackBackend(cfg)
        assert asyncio.run(backend.is_available()) is True

    def test_name(self):
        cfg = NPUManagerConfig()
        backend = CPUFallbackBackend(cfg)
        assert backend.name == "cpu"

    def test_health(self):
        cfg = NPUManagerConfig()
        backend = CPUFallbackBackend(cfg)
        health = asyncio.run(backend.health())
        assert health["backend"] == "cpu"
        assert health["available"] is True

    def test_load_model_no_cv2(self):
        cfg = NPUManagerConfig()
        backend = CPUFallbackBackend(cfg)
        with patch.dict("sys.modules", {"cv2": None}):
            with pytest.raises(RuntimeError, match="OpenCV"):
                asyncio.run(backend.load_model("test.onnx"))

    def test_unload_idempotent(self):
        cfg = NPUManagerConfig()
        backend = CPUFallbackBackend(cfg)
        asyncio.run(backend.unload())
        asyncio.run(backend.unload())  # should not raise

    def test_infer_without_model_raises(self):
        cfg = NPUManagerConfig()
        backend = CPUFallbackBackend(cfg)
        with pytest.raises(RuntimeError, match="未加载"):
            asyncio.run(backend.infer(MagicMock()))


# ── HailoNPUBackend ───────────────────────────────────────────────────────


class TestHailoNPUBackend:
    """Hailo 后端测试（mock 硬件）。"""

    def test_not_available_without_device(self):
        cfg = NPUManagerConfig(hailo_device="/dev/nonexistent_hailo")
        backend = HailoNPUBackend(cfg)
        assert asyncio.run(backend.is_available()) is False

    def test_name(self):
        cfg = NPUManagerConfig()
        backend = HailoNPUBackend(cfg)
        assert backend.name == "hailo"

    def test_not_available_without_sdk(self):
        cfg = NPUManagerConfig(hailo_device="/dev/fake_hailo")
        backend = HailoNPUBackend(cfg)
        with patch("os.path.exists", return_value=True):
            with patch.dict("sys.modules", {"hailo_platform": None}):
                assert asyncio.run(backend.is_available()) is False

    def test_unload_idempotent(self):
        cfg = NPUManagerConfig()
        backend = HailoNPUBackend(cfg)
        asyncio.run(backend.unload())
        asyncio.run(backend.unload())

    def test_infer_without_model_raises(self):
        cfg = NPUManagerConfig()
        backend = HailoNPUBackend(cfg)
        with pytest.raises(RuntimeError, match="未加载"):
            asyncio.run(backend.infer(MagicMock()))


# ── RKNNNPUBackend ────────────────────────────────────────────────────────


class TestRKNNNPUBackend:
    """RKNN 后端测试（mock 硬件）。"""

    def test_name(self):
        cfg = NPUManagerConfig()
        backend = RKNNNPUBackend(cfg)
        assert backend.name == "rknn"

    def test_not_available_without_sdk(self):
        cfg = NPUManagerConfig()
        backend = RKNNNPUBackend(cfg)
        with patch.dict("sys.modules", {"rknn": None, "rknn.api": None}):
            assert asyncio.run(backend.is_available()) is False

    def test_unload_idempotent(self):
        cfg = NPUManagerConfig()
        backend = RKNNNPUBackend(cfg)
        asyncio.run(backend.unload())
        asyncio.run(backend.unload())

    def test_infer_without_model_raises(self):
        cfg = NPUManagerConfig()
        backend = RKNNNPUBackend(cfg)
        with pytest.raises(RuntimeError, match="未加载"):
            asyncio.run(backend.infer(MagicMock()))


# ── NPUManager ────────────────────────────────────────────────────────────


class TestNPUManager:
    """NPU 管理器测试。"""

    def _make_mock_backend(self, name: str, available: bool = True) -> BaseNPUBackend:
        backend = MagicMock(spec=BaseNPUBackend)
        backend.name = name
        backend.is_available = AsyncMock(return_value=available)
        backend.load_model = AsyncMock(return_value=True)
        backend.unload = AsyncMock()
        backend.health = AsyncMock(return_value={"backend": name, "available": available})
        return backend

    def test_auto_detect_selects_first_available(self):
        hailo = self._make_mock_backend("hailo", available=True)
        rknn = self._make_mock_backend("rknn", available=False)
        cpu = self._make_mock_backend("cpu", available=True)
        manager = NPUManager(backends=[hailo, rknn, cpu])

        result = asyncio.run(manager.auto_detect())
        assert result == "hailo"
        assert manager.active_backend_name == "hailo"

    def test_auto_detect_fallback_to_cpu(self):
        hailo = self._make_mock_backend("hailo", available=False)
        rknn = self._make_mock_backend("rknn", available=False)
        cpu = self._make_mock_backend("cpu", available=True)
        manager = NPUManager(backends=[hailo, rknn, cpu])

        result = asyncio.run(manager.auto_detect())
        assert result == "cpu"
        assert manager.active_backend_name == "cpu"

    def test_auto_detect_forced_backend(self):
        cfg = NPUManagerConfig(backend=NPUBackendType.RKNN)
        hailo = self._make_mock_backend("hailo", available=True)
        rknn = self._make_mock_backend("rknn", available=True)
        cpu = self._make_mock_backend("cpu", available=True)
        manager = NPUManager(config=cfg, backends=[hailo, rknn, cpu])

        result = asyncio.run(manager.auto_detect())
        assert result == "rknn"

    def test_auto_detect_forced_backend_unavailable_fallback(self):
        cfg = NPUManagerConfig(backend=NPUBackendType.HAILO)
        hailo = self._make_mock_backend("hailo", available=False)
        rknn = self._make_mock_backend("rknn", available=False)
        cpu = self._make_mock_backend("cpu", available=True)
        manager = NPUManager(config=cfg, backends=[hailo, rknn, cpu])

        result = asyncio.run(manager.auto_detect())
        assert result == "cpu"

    def test_auto_detect_none_available(self):
        hailo = self._make_mock_backend("hailo", available=False)
        rknn = self._make_mock_backend("rknn", available=False)
        cpu = self._make_mock_backend("cpu", available=False)
        manager = NPUManager(backends=[hailo, rknn, cpu])

        result = asyncio.run(manager.auto_detect())
        assert result == "none"

    def test_load_model_delegates_to_active(self):
        hailo = self._make_mock_backend("hailo", available=True)
        manager = NPUManager(backends=[hailo])
        asyncio.run(manager.auto_detect())

        result = asyncio.run(manager.load_model("model.hef"))
        assert result is True
        hailo.load_model.assert_awaited_once_with("model.hef")

    def test_load_model_fallback_on_failure(self):
        hailo = self._make_mock_backend("hailo", available=True)
        hailo.load_model = AsyncMock(side_effect=RuntimeError("NPU fail"))

        cpu = MagicMock(spec=CPUFallbackBackend)
        cpu.name = "cpu"
        cpu.is_available = AsyncMock(return_value=True)
        cpu.load_model = AsyncMock(return_value=True)
        cpu.unload = AsyncMock()

        manager = NPUManager(backends=[hailo, cpu])
        asyncio.run(manager.auto_detect())

        result = asyncio.run(manager.load_model("model.onnx"))
        assert result is True
        cpu.load_model.assert_awaited_once()

    def test_infer_delegates_to_active(self):
        hailo = self._make_mock_backend("hailo", available=True)
        mock_result = InferenceResult(
            detections=[], inference_time_ms=1.0,
            backend_used="hailo", input_shape=(640, 640, 3),
        )
        hailo.infer = AsyncMock(return_value=mock_result)
        manager = NPUManager(backends=[hailo])
        asyncio.run(manager.auto_detect())

        result = asyncio.run(manager.infer(MagicMock()))
        assert result is mock_result

    def test_infer_without_init_raises(self):
        manager = NPUManager()
        with pytest.raises(RuntimeError, match="未初始化"):
            asyncio.run(manager.infer(MagicMock()))

    def test_unload_delegates_to_active(self):
        hailo = self._make_mock_backend("hailo", available=True)
        manager = NPUManager(backends=[hailo])
        asyncio.run(manager.auto_detect())
        asyncio.run(manager.unload())
        hailo.unload.assert_awaited_once()

    def test_health_returns_manager_info(self):
        hailo = self._make_mock_backend("hailo", available=True)
        manager = NPUManager(backends=[hailo])
        asyncio.run(manager.auto_detect())

        health = asyncio.run(manager.health())
        assert health["manager_initialized"] is True
        assert health["active_backend"] == "hailo"

    def test_health_before_detection(self):
        manager = NPUManager()
        health = asyncio.run(manager.health())
        assert health["manager_initialized"] is False
        assert health["active_backend"] == "none"


# ── BaseNPUBackend Contract ───────────────────────────────────────────────


class TestBaseNPUBackendContract:
    """确保抽象基类接口完整。"""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseNPUBackend()  # type: ignore[abstract]

    def test_all_backends_implement_interface(self):
        cfg = NPUManagerConfig()
        for cls in (HailoNPUBackend, RKNNNPUBackend, CPUFallbackBackend):
            backend = cls(cfg)
            assert hasattr(backend, "is_available")
            assert hasattr(backend, "load_model")
            assert hasattr(backend, "infer")
            assert hasattr(backend, "unload")
            assert hasattr(backend, "health")
