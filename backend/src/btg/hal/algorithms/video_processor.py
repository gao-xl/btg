"""BTG 视频算法处理引擎。

原始帧只在调用进程内处理，返回值仅包含结构化的运动特征。MediaPipe
不可用或运行失败时，处理器会自动切换到 OpenCV 帧差模式。
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Mapping
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)

CLASSICAL_MOTION = "classical_motion"
MEDIAPIPE_POSE = "mediapipe_pose"
SUPPORTED_ALGORITHMS = frozenset((CLASSICAL_MOTION, MEDIAPIPE_POSE))

# MediaPipe Pose 索引：左/右肩、肘、腕、髋。只用手臂和躯干，
# 避免手指、面部等局部噪声对“挣扎”指标的过度放大。
_TRACKED_LANDMARKS = (11, 12, 13, 14, 15, 16, 23, 24)


class VideoProcessor:
    """在帧差运动检测和 MediaPipe Pose 之间可运行时切换的处理器。

    Args:
        config: 包含 ``algorithm_mode`` 的映射或配置对象。
        algorithm_mode: 显式模式，优先级高于 ``config``。
        changed_pixel_threshold: OpenCV 灰度差分阈值（取值 0..255）。
        landmark_visibility_threshold: 参与速度计算的关键点最低可见度。
        struggle_reference_speed: 对应满分的平均归一化坐标速度（每秒）。
        clock: 单调时钟，可在测试或采集时间戳注入时替换。
    """

    def __init__(
        self,
        config: Mapping[str, Any] | Any | None = None,
        *,
        algorithm_mode: str | None = None,
        changed_pixel_threshold: int = 25,
        landmark_visibility_threshold: float = 0.5,
        struggle_reference_speed: float = 1.5,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 <= changed_pixel_threshold <= 255:
            raise ValueError("changed_pixel_threshold must be in [0, 255]")
        if not 0.0 <= landmark_visibility_threshold <= 1.0:
            raise ValueError("landmark_visibility_threshold must be in [0, 1]")
        if struggle_reference_speed <= 0.0:
            raise ValueError("struggle_reference_speed must be positive")

        configured_mode = algorithm_mode or self._read_mode(config)
        self._changed_pixel_threshold = int(changed_pixel_threshold)
        self._visibility_threshold = float(landmark_visibility_threshold)
        self._struggle_reference_speed = float(struggle_reference_speed)
        self._clock = clock

        self._cv2: Any = None
        self._pose: Any = None
        self._previous_gray: Any = None
        self._previous_landmarks: dict[int, tuple[float, float, float]] | None = None
        self._previous_pose_timestamp: float | None = None
        self._algorithm_mode = CLASSICAL_MOTION
        self._requested_algorithm_mode = configured_mode
        self._last_fallback_reason: str | None = None

        self.set_algorithm_mode(configured_mode)

    @staticmethod
    def _read_mode(config: Mapping[str, Any] | Any | None) -> str:
        if config is None:
            return CLASSICAL_MOTION
        if isinstance(config, Mapping):
            return str(config.get("algorithm_mode", CLASSICAL_MOTION))
        return str(getattr(config, "algorithm_mode", CLASSICAL_MOTION))

    @property
    def algorithm_mode(self) -> str:
        """当前实际使用的算法（可能是降级后的帧差模式）。"""
        return self._algorithm_mode

    @property
    def requested_algorithm_mode(self) -> str:
        """最近一次请求切换的算法。"""
        return self._requested_algorithm_mode

    @property
    def last_fallback_reason(self) -> str | None:
        """最近一次降级原因；未发生降级时为 ``None``。"""
        return self._last_fallback_reason

    def set_algorithm_mode(self, algorithm_mode: str) -> str:
        """切换算法并返回实际激活的模式。

        无效配置或 MediaPipe 初始化失败都会安全降级为
        ``classical_motion``。切换时会清空时序基线，因此新模式首帧
        稳定输出 0，不会把两种算法的历史状态混用。
        """
        requested = str(algorithm_mode).strip().lower()
        self._requested_algorithm_mode = requested
        self._last_fallback_reason = None
        self._reset_temporal_state()

        if requested not in SUPPORTED_ALGORITHMS:
            self._fallback_to_classical(f"unsupported algorithm_mode: {requested!r}")
            return self._algorithm_mode

        if requested == MEDIAPIPE_POSE:
            try:
                self._require_cv2()
                self._initialize_pose()
            except Exception as exc:  # MediaPipe 可因导入、模型或平台失败
                self._fallback_to_classical(
                    f"MediaPipe Pose initialization failed: {type(exc).__name__}: {exc}"
                )
                return self._algorithm_mode
            self._algorithm_mode = MEDIAPIPE_POSE
            return self._algorithm_mode

        self._close_pose()
        self._require_cv2()
        self._algorithm_mode = CLASSICAL_MOTION
        return self._algorithm_mode

    def process_frame(
        self, frame: Any, *, timestamp: float | None = None
    ) -> dict[str, Any]:
        """处理一帧 BGR/BGRA/灰度 OpenCV 图像并返回统一特征字典。"""
        self._validate_frame(frame)
        frame_timestamp = self._clock() if timestamp is None else float(timestamp)
        if not math.isfinite(frame_timestamp):
            raise ValueError("timestamp must be finite")

        if self._algorithm_mode == MEDIAPIPE_POSE:
            try:
                return self._process_mediapipe(frame, frame_timestamp)
            except Exception as exc:  # 运行中模型异常也不应中断视频链路
                self._fallback_to_classical(
                    f"MediaPipe Pose processing failed: {type(exc).__name__}: {exc}"
                )

        return self._process_classical(frame)

    def close(self) -> None:
        """释放 MediaPipe 资源；可重复调用。"""
        self._close_pose()
        self._reset_temporal_state()

    def __enter__(self) -> "VideoProcessor":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _require_cv2(self) -> Any:
        if self._cv2 is None:
            try:
                import cv2
            except ImportError as exc:
                raise ImportError(
                    "OpenCV is required; install btg-backend[vision] or "
                    "opencv-python-headless"
                ) from exc
            self._cv2 = cv2
        return self._cv2

    def _initialize_pose(self) -> None:
        self._close_pose()
        import mediapipe as mp

        pose_module = mp.solutions.pose
        self._pose = pose_module.Pose(
            static_image_mode=False,
            model_complexity=0,
            smooth_landmarks=True,
            enable_segmentation=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def _process_classical(self, frame: Any) -> dict[str, Any]:
        gray = self._to_gray(frame)
        if self._previous_gray is None or self._previous_gray.shape != gray.shape:
            self._previous_gray = gray.copy()
            ratio = 0.0
        else:
            cv2 = self._require_cv2()
            difference = cv2.absdiff(self._previous_gray, gray)
            _, changed = cv2.threshold(
                difference,
                self._changed_pixel_threshold,
                255,
                cv2.THRESH_BINARY,
            )
            ratio = float(cv2.countNonZero(changed)) / float(changed.size)
            self._previous_gray = gray.copy()

        intensity = self._clamp01(ratio)
        return {
            "algorithm_used": CLASSICAL_MOTION,
            "struggle_score": intensity,
            "raw_metrics": {
                "changed_pixels_ratio": intensity,
                "motion_intensity": intensity,
            },
        }

    def _process_mediapipe(
        self, frame: Any, timestamp: float
    ) -> dict[str, Any]:
        cv2 = self._require_cv2()
        if len(frame.shape) == 2:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
        elif frame.shape[2] == 4:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
        else:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        results = self._pose.process(rgb_frame)
        pose_landmarks = getattr(results, "pose_landmarks", None)
        if pose_landmarks is None:
            self._previous_landmarks = None
            self._previous_pose_timestamp = None
            return self._pose_result(0.0, 0.0, 0, False)

        current: dict[int, tuple[float, float, float]] = {}
        landmarks = pose_landmarks.landmark
        for index in _TRACKED_LANDMARKS:
            landmark = landmarks[index]
            visibility = float(getattr(landmark, "visibility", 1.0))
            if visibility >= self._visibility_threshold:
                current[index] = (
                    float(landmark.x),
                    float(landmark.y),
                    float(landmark.z),
                )

        speed = 0.0
        compared_count = 0
        if self._previous_landmarks is not None and self._previous_pose_timestamp is not None:
            elapsed = timestamp - self._previous_pose_timestamp
            if elapsed > 0.0:
                distances = [
                    math.dist(position, self._previous_landmarks[index])
                    for index, position in current.items()
                    if index in self._previous_landmarks
                ]
                compared_count = len(distances)
                if distances:
                    speed = (sum(distances) / compared_count) / elapsed

        self._previous_landmarks = current
        self._previous_pose_timestamp = timestamp
        score = self._clamp01(speed / self._struggle_reference_speed)
        return self._pose_result(score, speed, compared_count, True)

    def _pose_result(
        self,
        score: float,
        speed: float,
        compared_count: int,
        pose_detected: bool,
    ) -> dict[str, Any]:
        return {
            "algorithm_used": MEDIAPIPE_POSE,
            "struggle_score": self._clamp01(score),
            "raw_metrics": {
                "mean_landmark_speed": max(0.0, float(speed)),
                "compared_landmarks": int(compared_count),
                "pose_detected": bool(pose_detected),
            },
        }

    def _to_gray(self, frame: Any) -> Any:
        cv2 = self._require_cv2()
        if len(frame.shape) == 2:
            return frame
        if frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def _validate_frame(frame: Any) -> None:
        if frame is None or not hasattr(frame, "shape") or not hasattr(frame, "size"):
            raise ValueError("frame must be a non-empty OpenCV/numpy image")
        if frame.size == 0 or len(frame.shape) not in (2, 3):
            raise ValueError("frame must be a non-empty 2D or 3D image")
        if len(frame.shape) == 3 and frame.shape[2] not in (3, 4):
            raise ValueError("color frame must have 3 (BGR) or 4 (BGRA) channels")

    def _fallback_to_classical(self, reason: str) -> None:
        self._last_fallback_reason = reason
        LOGGER.warning("%s; falling back to %s", reason, CLASSICAL_MOTION)
        self._close_pose()
        self._reset_temporal_state()
        self._require_cv2()
        self._algorithm_mode = CLASSICAL_MOTION

    def _reset_temporal_state(self) -> None:
        self._previous_gray = None
        self._previous_landmarks = None
        self._previous_pose_timestamp = None

    def _close_pose(self) -> None:
        pose, self._pose = self._pose, None
        if pose is not None:
            try:
                pose.close()
            except Exception:  # pragma: no cover - 第三方释放失败不可影响关闭
                LOGGER.exception("Failed to close MediaPipe Pose")

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))


__all__ = [
    "CLASSICAL_MOTION",
    "MEDIAPIPE_POSE",
    "SUPPORTED_ALGORITHMS",
    "VideoProcessor",
]
