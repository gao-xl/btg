"""AdaptiveBiometricLearningEngine 的心率突升与持久化测试。"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "sdk"))
sys.path.insert(0, str(_ROOT / "backend" / "src"))

from btg.fusion import AdaptiveBiometricLearningEngine, MetricConfig  # noqa: E402


def _heart_rate_engine() -> AdaptiveBiometricLearningEngine:
    config = MetricConfig(
        window_size=300,
        calibration_samples=20,
        ewma_alpha=0.02,
        anomaly_threshold_z=2.5,
        critical_threshold_z=4.0,
        min_stddev=1.0,
        learning_guard_z=2.0,
        max_update_z=0.25,
    )
    return AdaptiveBiometricLearningEngine({"heart_rate": config})


def test_heart_rate_stable_then_spike() -> None:
    engine = _heart_rate_engine()

    # 20 个平稳样本完成校准，再以小幅波动验证正常学习。
    stable_values = [79.0, 80.0, 81.0, 80.0] * 5
    for value in stable_values:
        result = engine.evaluate_anomaly("heart_rate", value)
    assert result["phase"] == "learning"
    assert result["ready"] is True

    normal = engine.evaluate_anomaly("heart_rate", 82.0)
    assert normal["is_anomaly"] is False
    assert normal["baseline_updated"] is True

    baseline_before_spike = engine.snapshot()["metrics"]["heart_rate"]["mean"]
    spike = engine.evaluate_anomaly("heart_rate", 145.0)
    baseline_after_spike = engine.snapshot()["metrics"]["heart_rate"]["mean"]

    assert spike["is_anomaly"] is True
    assert spike["is_critical"] is True
    assert spike["z_score"] > 4.0
    assert spike["intervention_level"] == "pause"
    assert spike["event"]["type"] == "adaptive.anomaly_detected"
    assert spike["baseline_updated"] is False
    assert baseline_after_spike == baseline_before_spike


def test_json_round_trip_avoids_recalibration() -> None:
    engine = _heart_rate_engine()
    for value in [79.0, 80.0, 81.0, 80.0] * 5:
        engine.evaluate_anomaly("heart_rate", value)

    with tempfile.TemporaryDirectory() as directory:
        state_path = Path(directory) / "adaptive-baseline.json"
        engine.save_state(state_path)

        restored = AdaptiveBiometricLearningEngine()
        restored.load_state(state_path)
        result = restored.evaluate_anomaly("heart_rate", 80.0)

    assert result["phase"] == "learning"
    assert result["ready"] is True
    assert result["is_anomaly"] is False


def test_async_wrapper_is_safe_for_multiple_metrics() -> None:
    engine = AdaptiveBiometricLearningEngine(
        default_config=MetricConfig(calibration_samples=4, window_size=16)
    )

    async def scenario() -> None:
        await asyncio.gather(
            *(engine.aevaluate_anomaly("heart_rate", value) for value in [80, 81, 80, 79]),
            *(engine.aevaluate_anomaly("imu_variance", value) for value in [1, 1.1, 0.9, 1]),
        )

    asyncio.run(scenario())
    snapshot = engine.snapshot()
    assert snapshot["metrics"]["heart_rate"]["phase"] == "learning"
    assert snapshot["metrics"]["imu_variance"]["phase"] == "learning"


if __name__ == "__main__":
    test_heart_rate_stable_then_spike()
    test_json_round_trip_avoids_recalibration()
    test_async_wrapper_is_safe_for_multiple_metrics()

    demo = _heart_rate_engine()
    for heart_rate in [79.0, 80.0, 81.0, 80.0] * 5:
        demo.evaluate_anomaly("heart_rate", heart_rate)
    print("平稳心率:", demo.evaluate_anomaly("heart_rate", 82.0))
    print("心率突升:", demo.evaluate_anomaly("heart_rate", 145.0))
    print("adaptive monitor smoke ok")
