"""VideoProcessor 帧差、姿态评分、切换与降级测试。"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend" / "src"))

from btg.hal.algorithms.video_processor import (  # noqa: E402
    CLASSICAL_MOTION,
    MEDIAPIPE_POSE,
    VideoProcessor,
)


def _frame(value: int = 0) -> np.ndarray:
    return np.full((10, 10, 3), value, dtype=np.uint8)


def test_classical_motion_reports_changed_pixel_ratio() -> None:
    processor = VideoProcessor(
        {"algorithm_mode": CLASSICAL_MOTION}, changed_pixel_threshold=10
    )

    first = processor.process_frame(_frame())
    changed = _frame()
    changed[:5, :, :] = 255
    second = processor.process_frame(changed)

    assert first == {
        "algorithm_used": CLASSICAL_MOTION,
        "struggle_score": 0.0,
        "raw_metrics": {"changed_pixels_ratio": 0.0, "motion_intensity": 0.0},
    }
    assert second["algorithm_used"] == CLASSICAL_MOTION
    assert second["struggle_score"] == 0.5
    assert second["raw_metrics"]["changed_pixels_ratio"] == 0.5
    assert second["raw_metrics"]["motion_intensity"] == 0.5


def test_mode_switch_resets_temporal_baseline() -> None:
    processor = VideoProcessor(algorithm_mode=CLASSICAL_MOTION)
    processor.process_frame(_frame())
    assert processor.process_frame(_frame(255))["struggle_score"] == 1.0

    assert processor.set_algorithm_mode(CLASSICAL_MOTION) == CLASSICAL_MOTION
    assert processor.process_frame(_frame(255))["struggle_score"] == 0.0


def test_mediapipe_initialization_failure_falls_back() -> None:
    class BrokenPoseProcessor(VideoProcessor):
        def _initialize_pose(self) -> None:
            raise RuntimeError("model unavailable")

    processor = BrokenPoseProcessor(algorithm_mode=MEDIAPIPE_POSE)

    assert processor.requested_algorithm_mode == MEDIAPIPE_POSE
    assert processor.algorithm_mode == CLASSICAL_MOTION
    assert "model unavailable" in (processor.last_fallback_reason or "")
    assert processor.process_frame(_frame())["algorithm_used"] == CLASSICAL_MOTION


def test_pose_score_uses_arm_and_torso_landmark_speed() -> None:
    def pose_result(x_offset: float) -> SimpleNamespace:
        landmarks = [
            SimpleNamespace(x=0.0, y=0.0, z=0.0, visibility=1.0)
            for _ in range(25)
        ]
        for index in (11, 12, 13, 14, 15, 16, 23, 24):
            landmarks[index].x = x_offset
        return SimpleNamespace(
            pose_landmarks=SimpleNamespace(landmark=landmarks)
        )

    class FakePose:
        def __init__(self) -> None:
            self._results = iter((pose_result(0.0), pose_result(0.15)))

        def process(self, _frame: np.ndarray) -> SimpleNamespace:
            return next(self._results)

        def close(self) -> None:
            pass

    processor = VideoProcessor(
        algorithm_mode=CLASSICAL_MOTION, struggle_reference_speed=1.5
    )
    processor._pose = FakePose()
    processor._algorithm_mode = MEDIAPIPE_POSE

    first = processor.process_frame(_frame(), timestamp=10.0)
    second = processor.process_frame(_frame(), timestamp=10.1)

    assert first["algorithm_used"] == MEDIAPIPE_POSE
    assert first["struggle_score"] == 0.0
    assert second["algorithm_used"] == MEDIAPIPE_POSE
    assert second["struggle_score"] > 0.99
    assert second["raw_metrics"]["compared_landmarks"] == 8
    assert second["raw_metrics"]["pose_detected"] is True


def test_pose_runtime_failure_falls_back_without_dropping_frame() -> None:
    class BrokenPose:
        def process(self, _frame: np.ndarray) -> None:
            raise RuntimeError("inference failed")

        def close(self) -> None:
            pass

    processor = VideoProcessor(algorithm_mode=CLASSICAL_MOTION)
    processor._pose = BrokenPose()
    processor._algorithm_mode = MEDIAPIPE_POSE

    result = processor.process_frame(_frame())

    assert processor.algorithm_mode == CLASSICAL_MOTION
    assert result["algorithm_used"] == CLASSICAL_MOTION
    assert result["struggle_score"] == 0.0
    assert "inference failed" in (processor.last_fallback_reason or "")
