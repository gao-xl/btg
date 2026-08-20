"""自学习与动态基线自适应引擎。

本模块为每个逻辑指标维护独立的校准/学习状态和有界滑动窗口：

* ``calibrating``：收集最初的样本并计算均值与总体标准差；
* ``learning``：先依据当前基线计算异常分数，再用受限 EWMA 缓慢更新基线。

安全约束：异常或接近异常的样本不会反向污染基线；EWMA 单次漂移受限；
模块只返回限制性建议，不直接生成执行器命令，也不提供增强或自动恢复建议。
同步计算路径由 ``threading.RLock`` 保护，可安全地被多个协程/线程调用。
JSON I/O 另提供 ``asyncio.to_thread`` 包装，避免阻塞事件循环。
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import statistics
import tempfile
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Deque, Dict, Mapping, Optional


class BaselinePhase(str, Enum):
    """单个指标的基线生命周期。"""

    CALIBRATING = "calibrating"
    LEARNING = "learning"


class InterventionLevel(str, Enum):
    """融合/安全层可消费的限制性建议。"""

    NONE = "none"
    TIGHTEN_LIMIT = "tighten_limit"
    PAUSE = "pause"


@dataclass(frozen=True, slots=True)
class MetricConfig:
    """一个指标的自适应参数。

    ``min_stddev`` 与指标使用相同物理单位，用于避免稳定基线的标准差为零。
    ``learning_guard_z`` 以内的样本才允许学习；``max_update_z`` 限制单次
    EWMA 残差，防止缓慢但持续的异常把基线无限拖走。
    """

    window_size: int = 300
    calibration_samples: int = 30
    ewma_alpha: float = 0.01
    anomaly_threshold_z: float = 2.5
    critical_threshold_z: float = 4.0
    min_stddev: float = 1.0
    learning_guard_z: float = 2.0
    max_update_z: float = 0.25

    def __post_init__(self) -> None:
        if self.window_size < 2:
            raise ValueError("window_size 必须至少为 2")
        if not 2 <= self.calibration_samples <= self.window_size:
            raise ValueError("calibration_samples 必须位于 [2, window_size]")
        if not 0.0 < self.ewma_alpha <= 1.0:
            raise ValueError("ewma_alpha 必须位于 (0, 1]")
        if self.anomaly_threshold_z <= 0.0:
            raise ValueError("anomaly_threshold_z 必须为正数")
        if self.critical_threshold_z < self.anomaly_threshold_z:
            raise ValueError("critical_threshold_z 不能小于 anomaly_threshold_z")
        if self.min_stddev <= 0.0:
            raise ValueError("min_stddev 必须为正数")
        if not 0.0 < self.learning_guard_z <= self.anomaly_threshold_z:
            raise ValueError("learning_guard_z 必须位于 (0, anomaly_threshold_z]")
        if self.max_update_z <= 0.0:
            raise ValueError("max_update_z 必须为正数")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "MetricConfig":
        allowed = {field for field in cls.__dataclass_fields__}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"未知指标配置字段: {sorted(unknown)}")
        return cls(**dict(raw))


def _finite_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} 必须为有限数值")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} 必须为有限数值")
    return number


class AdaptiveBaselineTracker:
    """维护单个指标的窗口、动态基线和异常评分。"""

    def __init__(self, metric_name: str, config: Optional[MetricConfig] = None) -> None:
        if not metric_name or not metric_name.strip():
            raise ValueError("metric_name 不能为空")
        self.metric_name = metric_name.strip()
        self.config = config or MetricConfig()
        self._window: Deque[float] = deque(maxlen=self.config.window_size)
        self._phase = BaselinePhase.CALIBRATING
        self._mean: Optional[float] = None
        self._variance: Optional[float] = None
        self._samples_seen = 0
        self._learned_samples = 0
        self._consecutive_anomalies = 0
        self._lock = threading.RLock()

    @property
    def phase(self) -> BaselinePhase:
        with self._lock:
            return self._phase

    def evaluate(self, current_value: float) -> Dict[str, Any]:
        """摄入一个样本，返回相对当前基线的异常评估结果。"""
        value = _finite_float(current_value, "current_value")
        with self._lock:
            self._window.append(value)
            self._samples_seen += 1

            if self._phase is BaselinePhase.CALIBRATING:
                if len(self._window) >= self.config.calibration_samples:
                    calibration = list(self._window)[-self.config.calibration_samples :]
                    self._mean = statistics.fmean(calibration)
                    raw_stddev = statistics.pstdev(calibration)
                    stddev = max(raw_stddev, self.config.min_stddev)
                    self._variance = stddev * stddev
                    self._phase = BaselinePhase.LEARNING
                else:
                    return self._calibrating_result(value)

            assert self._mean is not None and self._variance is not None
            mean_before = self._mean
            stddev_before = max(math.sqrt(self._variance), self.config.min_stddev)
            z_score = (value - mean_before) / stddev_before
            absolute_z = abs(z_score)
            is_anomaly = absolute_z >= self.config.anomaly_threshold_z
            is_critical = absolute_z >= self.config.critical_threshold_z

            if is_anomaly:
                self._consecutive_anomalies += 1
            else:
                self._consecutive_anomalies = 0

            baseline_updated = False
            if absolute_z <= self.config.learning_guard_z:
                self._update_ewma(value, mean_before, stddev_before)
                baseline_updated = True

            if is_critical:
                intervention = InterventionLevel.PAUSE
            elif is_anomaly:
                intervention = InterventionLevel.TIGHTEN_LIMIT
            else:
                intervention = InterventionLevel.NONE

            direction = "high" if z_score > 0 else "low" if z_score < 0 else "within"
            relative_deviation = (
                (value - mean_before) / abs(mean_before) if mean_before != 0.0 else None
            )
            event = None
            if is_anomaly:
                event = {
                    "type": "adaptive.anomaly_detected",
                    "metric": self.metric_name,
                    "z_score": z_score,
                    "direction": direction,
                    "suggested_intervention": intervention.value,
                }

            return {
                "metric": self.metric_name,
                "current_value": value,
                "phase": self._phase.value,
                "ready": True,
                "sample_count": self._samples_seen,
                "window_count": len(self._window),
                "baseline_mean": mean_before,
                "baseline_stddev": stddev_before,
                "z_score": z_score,
                "absolute_z_score": absolute_z,
                "relative_deviation": relative_deviation,
                "direction": direction,
                "threshold_z": self.config.anomaly_threshold_z,
                "critical_threshold_z": self.config.critical_threshold_z,
                "is_anomaly": is_anomaly,
                "is_critical": is_critical,
                "consecutive_anomalies": self._consecutive_anomalies,
                "baseline_updated": baseline_updated,
                "intervention_level": intervention.value,
                "event": event,
            }

    def _calibrating_result(self, value: float) -> Dict[str, Any]:
        remaining = self.config.calibration_samples - len(self._window)
        provisional_mean = statistics.fmean(self._window)
        provisional_stddev = (
            max(statistics.pstdev(self._window), self.config.min_stddev)
            if len(self._window) >= 2
            else None
        )
        return {
            "metric": self.metric_name,
            "current_value": value,
            "phase": BaselinePhase.CALIBRATING.value,
            "ready": False,
            "sample_count": self._samples_seen,
            "window_count": len(self._window),
            "calibration_remaining": remaining,
            "baseline_mean": provisional_mean,
            "baseline_stddev": provisional_stddev,
            "z_score": None,
            "absolute_z_score": None,
            "relative_deviation": None,
            "direction": "unknown",
            "threshold_z": self.config.anomaly_threshold_z,
            "critical_threshold_z": self.config.critical_threshold_z,
            "is_anomaly": False,
            "is_critical": False,
            "consecutive_anomalies": 0,
            "baseline_updated": False,
            "intervention_level": InterventionLevel.NONE.value,
            "event": None,
        }

    def _update_ewma(self, value: float, mean_before: float, stddev_before: float) -> None:
        assert self._variance is not None
        alpha = self.config.ewma_alpha
        residual = value - mean_before
        max_residual = self.config.max_update_z * stddev_before
        bounded_residual = min(max(residual, -max_residual), max_residual)
        new_mean = mean_before + alpha * bounded_residual

        # EWMA 方差使用更新后均值的残差，并保留最小方差地板。
        centered = value - new_mean
        new_variance = (1.0 - alpha) * self._variance + alpha * centered * centered
        self._mean = new_mean
        self._variance = max(new_variance, self.config.min_stddev**2)
        self._learned_samples += 1

    def snapshot(self) -> Dict[str, Any]:
        """返回可安全序列化的状态副本。"""
        with self._lock:
            stddev = (
                max(math.sqrt(self._variance), self.config.min_stddev)
                if self._variance is not None
                else None
            )
            return {
                "metric": self.metric_name,
                "phase": self._phase.value,
                "mean": self._mean,
                "stddev": stddev,
                "samples_seen": self._samples_seen,
                "learned_samples": self._learned_samples,
                "consecutive_anomalies": self._consecutive_anomalies,
                "window": list(self._window),
                "config": asdict(self.config),
            }

    @classmethod
    def from_snapshot(cls, raw: Mapping[str, Any]) -> "AdaptiveBaselineTracker":
        try:
            metric_name = str(raw["metric"])
            config = MetricConfig.from_dict(raw["config"])
            phase = BaselinePhase(str(raw["phase"]))
            window_raw = raw["window"]
            if not isinstance(window_raw, list):
                raise ValueError("window 必须为数组")
            window = [_finite_float(value, "window item") for value in window_raw]
            if len(window) > config.window_size:
                raise ValueError("持久化窗口超过 window_size")
            samples_seen = int(raw["samples_seen"])
            learned_samples = int(raw["learned_samples"])
            consecutive = int(raw.get("consecutive_anomalies", 0))
            if min(samples_seen, learned_samples, consecutive) < 0:
                raise ValueError("样本计数不能为负")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"无效的指标持久化状态: {exc}") from exc

        tracker = cls(metric_name, config)
        tracker._window.extend(window)
        tracker._phase = phase
        tracker._samples_seen = samples_seen
        tracker._learned_samples = learned_samples
        tracker._consecutive_anomalies = consecutive

        mean_raw = raw.get("mean")
        stddev_raw = raw.get("stddev")
        if phase is BaselinePhase.LEARNING:
            if mean_raw is None or stddev_raw is None:
                raise ValueError("learning 状态必须包含 mean/stddev")
            tracker._mean = _finite_float(mean_raw, "mean")
            stddev = _finite_float(stddev_raw, "stddev")
            if stddev <= 0.0:
                raise ValueError("stddev 必须为正数")
            tracker._variance = max(stddev, config.min_stddev) ** 2
        return tracker


class AdaptiveBiometricLearningEngine:
    """管理多个指标的动态基线、异常评分及本地持久化。"""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        metric_configs: Optional[Mapping[str, MetricConfig]] = None,
        *,
        default_config: Optional[MetricConfig] = None,
    ) -> None:
        self.default_config = default_config or MetricConfig()
        self._trackers: Dict[str, AdaptiveBaselineTracker] = {}
        self._lock = threading.RLock()
        for name, config in (metric_configs or {}).items():
            self.register_metric(name, config)

    def register_metric(self, metric_name: str, config: Optional[MetricConfig] = None) -> None:
        """显式注册指标；重复注册会被拒绝以避免静默覆盖基线。"""
        name = metric_name.strip()
        if not name:
            raise ValueError("metric_name 不能为空")
        with self._lock:
            if name in self._trackers:
                raise ValueError(f"指标已注册: {name}")
            self._trackers[name] = AdaptiveBaselineTracker(name, config or self.default_config)

    def evaluate_anomaly(self, metric_name: str, current_value: float) -> Dict[str, Any]:
        """评估样本，并在样本安全时缓慢学习动态基线。"""
        name = metric_name.strip()
        if not name:
            raise ValueError("metric_name 不能为空")
        with self._lock:
            tracker = self._trackers.get(name)
            if tracker is None:
                tracker = AdaptiveBaselineTracker(name, self.default_config)
                self._trackers[name] = tracker
            return tracker.evaluate(current_value)

    async def aevaluate_anomaly(
        self, metric_name: str, current_value: float
    ) -> Dict[str, Any]:
        """异步包装；适合高并发调用且不会阻塞事件循环。"""
        return await asyncio.to_thread(self.evaluate_anomaly, metric_name, current_value)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "schema_version": self.SCHEMA_VERSION,
                "saved_at": time.time(),
                "default_config": asdict(self.default_config),
                "metrics": {
                    name: tracker.snapshot()
                    for name, tracker in sorted(self._trackers.items())
                },
            }

    def save_state(self, path: str | os.PathLike[str]) -> None:
        """以临时文件 + ``os.replace`` 原子保存 JSON 状态。"""
        state = self.snapshot()
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    async def asave_state(self, path: str | os.PathLike[str]) -> None:
        await asyncio.to_thread(self.save_state, path)

    def load_state(self, path: str | os.PathLike[str], *, merge: bool = False) -> None:
        """校验并恢复状态；失败时保持当前内存状态不变。"""
        source = Path(path)
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"基线状态 JSON 损坏: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError("基线状态根节点必须为对象")
        if raw.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError(f"不支持的 schema_version: {raw.get('schema_version')}")

        metrics_raw = raw.get("metrics")
        if not isinstance(metrics_raw, dict):
            raise ValueError("metrics 必须为对象")
        restored: Dict[str, AdaptiveBaselineTracker] = {}
        for name, tracker_raw in metrics_raw.items():
            if not isinstance(name, str) or not isinstance(tracker_raw, dict):
                raise ValueError("metrics 包含无效条目")
            tracker = AdaptiveBaselineTracker.from_snapshot(tracker_raw)
            if tracker.metric_name != name:
                raise ValueError(f"指标键与状态名称不一致: {name}")
            restored[name] = tracker

        default_raw = raw.get("default_config")
        restored_default = (
            MetricConfig.from_dict(default_raw)
            if isinstance(default_raw, dict)
            else self.default_config
        )
        with self._lock:
            if merge:
                self._trackers.update(restored)
            else:
                self._trackers = restored
                self.default_config = restored_default

    async def aload_state(
        self, path: str | os.PathLike[str], *, merge: bool = False
    ) -> None:
        await asyncio.to_thread(self.load_state, path, merge=merge)


__all__ = [
    "AdaptiveBaselineTracker",
    "AdaptiveBiometricLearningEngine",
    "BaselinePhase",
    "InterventionLevel",
    "MetricConfig",
]
