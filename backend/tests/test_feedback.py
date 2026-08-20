"""反馈聚合模块与健康度判定的单元测试。

仅依赖 ``btg.feedback`` 与 ``btg_sdk``（纯逻辑，无硬件/网络），可在离线环境运行。
"""
from __future__ import annotations

import pytest

from btg.feedback import DeviceHealth, FeedbackAggregator, compute_health
from btg_sdk import DeviceFeedback, FeedbackKind

NOW = 1_000_000.0
STALE_AFTER = 30.0


def _fb(kind, *, value=None, timestamp=NOW, device_id="dev-1", **extra) -> DeviceFeedback:
    return DeviceFeedback(device_id=device_id, kind=kind, value=value, timestamp=timestamp, **extra)


# --------------------------------------------------------------------------- #
# compute_health：按反馈类别判定
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "kind,value,expected",
    [
        (FeedbackKind.ERROR, None, DeviceHealth.DEGRADED),
        (FeedbackKind.CONNECTION, 1.0, DeviceHealth.ONLINE),
        (FeedbackKind.CONNECTION, 0.0, DeviceHealth.OFFLINE),
        (FeedbackKind.CONNECTION, None, DeviceHealth.ONLINE),
        (FeedbackKind.ACK, None, DeviceHealth.ONLINE),
        (FeedbackKind.BATTERY, 0.3, DeviceHealth.ONLINE),
        (FeedbackKind.SIGNAL, 0.8, DeviceHealth.ONLINE),
        ("custom-kind", None, DeviceHealth.UNKNOWN),
    ],
)
def test_compute_health_by_kind(kind, value, expected):
    fb = _fb(kind, value=value)
    assert compute_health(fb, now=NOW, stale_after_seconds=STALE_AFTER) == expected


def test_compute_health_none_is_unknown():
    assert compute_health(None, now=NOW, stale_after_seconds=STALE_AFTER) == DeviceHealth.UNKNOWN


def test_compute_health_stale_overrides_kind():
    fb = _fb(FeedbackKind.ACK)
    # 超过时效即 STALE，即使类型本应判定为 ONLINE
    assert compute_health(fb, now=NOW + 31.0, stale_after_seconds=STALE_AFTER) == DeviceHealth.STALE
    # 恰好在时效边界内（未超过）仍按类型判定
    assert compute_health(fb, now=NOW + 30.0, stale_after_seconds=STALE_AFTER) == DeviceHealth.ONLINE


# --------------------------------------------------------------------------- #
# FeedbackAggregator：健康度与聚合行为
# --------------------------------------------------------------------------- #
def test_aggregator_health_from_latest():
    agg = FeedbackAggregator(stale_after_seconds=STALE_AFTER)
    agg.record(_fb(FeedbackKind.ACK))
    assert agg.health("dev-1", now=NOW) == DeviceHealth.ONLINE


def test_aggregator_health_unknown_without_feedback():
    agg = FeedbackAggregator()
    assert agg.health("missing", now=NOW) == DeviceHealth.UNKNOWN


def test_aggregator_health_stale():
    agg = FeedbackAggregator(stale_after_seconds=10.0)
    agg.record(_fb(FeedbackKind.ACK))
    assert agg.health("dev-1", now=NOW + 11.0) == DeviceHealth.STALE


def test_aggregator_health_tracks_latest_kind():
    agg = FeedbackAggregator(stale_after_seconds=STALE_AFTER)
    agg.record(_fb(FeedbackKind.CONNECTION, value=1.0))
    agg.record(_fb(FeedbackKind.ERROR))
    # 最近一条是 ERROR，覆盖此前 ONLINE 判定
    assert agg.health("dev-1", now=NOW) == DeviceHealth.DEGRADED


def test_aggregator_record_and_latest():
    agg = FeedbackAggregator(stale_after_seconds=STALE_AFTER)
    fb = _fb(FeedbackKind.ACK)
    agg.record(fb)
    assert agg.latest("dev-1") is fb
    assert agg.device_ids() == ["dev-1"]


def test_aggregator_history_truncates():
    agg = FeedbackAggregator(history_size=2)
    for i in range(3):
        agg.record(_fb(FeedbackKind.ACK, value=float(i), timestamp=NOW + i))
    assert [f.value for f in agg.history("dev-1")] == [1.0, 2.0]
    assert agg.latest("dev-1").value == 2.0


def test_aggregator_snapshot_contains_health():
    agg = FeedbackAggregator(stale_after_seconds=STALE_AFTER)
    agg.record(
        _fb(
            FeedbackKind.CONNECTION,
            value=1.0,
            unit="bool",
            message="connected",
            channel="haptic_feedback",
        )
    )
    snapshot = agg.snapshot(now=NOW)
    assert snapshot["dev-1"]["kind"] == FeedbackKind.CONNECTION
    assert snapshot["dev-1"]["value"] == 1.0
    assert snapshot["dev-1"]["unit"] == "bool"
    assert snapshot["dev-1"]["health"] == DeviceHealth.ONLINE


def test_aggregator_reset():
    agg = FeedbackAggregator()
    agg.record(_fb(FeedbackKind.ACK))
    agg.reset()
    assert agg.device_ids() == []
    assert agg.health("dev-1", now=NOW) == DeviceHealth.UNKNOWN


def test_aggregator_rejects_bad_params():
    with pytest.raises(ValueError):
        FeedbackAggregator(history_size=0)
    with pytest.raises(ValueError):
        FeedbackAggregator(stale_after_seconds=0.0)