"""Tests for the Manual Telemetry Override module."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

from btg.hal.actuators.manual_telemetry_override import (
    ManualOverride,
    ManualOverrideRequest,
    ManualOverrideStore,
)
from btg_sdk import Reading


# ── Request Validation ────────────────────────────────────────────────────


class TestManualOverrideRequest:
    """请求模型校验。"""

    def test_valid_request(self):
        req = ManualOverrideRequest(
            device_id="coyote_pro_01",
            manual_position=75.0,
            subjective_intensity=40,
            timestamp=1787180000.0,
        )
        assert req.device_id == "coyote_pro_01"
        assert req.manual_position == 75.0
        assert req.subjective_intensity == 40

    def test_defaults(self):
        req = ManualOverrideRequest(
            device_id="dev1",
            manual_position=50.0,
        )
        assert req.subjective_intensity == 0
        assert req.source == "operator"
        assert req.note == ""

    def test_position_at_boundary_zero(self):
        req = ManualOverrideRequest(device_id="d", manual_position=0.0)
        assert req.manual_position == 0.0

    def test_position_at_boundary_100(self):
        req = ManualOverrideRequest(device_id="d", manual_position=100.0)
        assert req.manual_position == 100.0

    def test_position_below_zero_rejected(self):
        with pytest.raises(Exception):
            ManualOverrideRequest(device_id="d", manual_position=-0.1)

    def test_position_above_100_rejected(self):
        with pytest.raises(Exception):
            ManualOverrideRequest(device_id="d", manual_position=100.1)

    def test_intensity_at_boundary_zero(self):
        req = ManualOverrideRequest(
            device_id="d", manual_position=50.0, subjective_intensity=0
        )
        assert req.subjective_intensity == 0

    def test_intensity_at_boundary_100(self):
        req = ManualOverrideRequest(
            device_id="d", manual_position=50.0, subjective_intensity=100
        )
        assert req.subjective_intensity == 100

    def test_intensity_below_zero_rejected(self):
        with pytest.raises(Exception):
            ManualOverrideRequest(
                device_id="d", manual_position=50.0, subjective_intensity=-1
            )

    def test_intensity_above_100_rejected(self):
        with pytest.raises(Exception):
            ManualOverrideRequest(
                device_id="d", manual_position=50.0, subjective_intensity=101
            )

    def test_empty_device_id_rejected(self):
        with pytest.raises(Exception):
            ManualOverrideRequest(device_id="", manual_position=50.0)

    def test_zero_timestamp_rejected(self):
        with pytest.raises(Exception):
            ManualOverrideRequest(
                device_id="d", manual_position=50.0, timestamp=0.0
            )

    def test_negative_timestamp_rejected(self):
        with pytest.raises(Exception):
            ManualOverrideRequest(
                device_id="d", manual_position=50.0, timestamp=-1.0
            )


# ── ManualOverride Dataclass ──────────────────────────────────────────────


class TestManualOverride:
    """覆盖记录数据类。"""

    def test_creation(self):
        o = ManualOverride(
            device_id="dev1",
            manual_position=75.0,
            subjective_intensity=40,
            authoritative_position=75.0,
            timestamp=1787180000.0,
            source="operator",
            note="test",
        )
        assert o.device_id == "dev1"
        assert o.authoritative_position == 75.0


# ── ManualOverrideStore ───────────────────────────────────────────────────


class TestManualOverrideStore:
    """状态存储测试。"""

    def _make_store(self, **kwargs: Any) -> ManualOverrideStore:
        hub = MagicMock()
        hub.publish = MagicMock()
        return ManualOverrideStore(hub=hub, **kwargs)

    def test_update_creates_override(self):
        store = self._make_store()
        req = ManualOverrideRequest(
            device_id="dev1", manual_position=75.0,
            subjective_intensity=40, timestamp=1787180000.0,
        )
        result = asyncio.run(store.update(req))
        assert result.device_id == "dev1"
        assert result.manual_position == 75.0
        assert result.authoritative_position == 75.0

    def test_update_broadcasts_via_hub(self):
        hub = MagicMock()
        store = ManualOverrideStore(hub=hub)
        req = ManualOverrideRequest(
            device_id="dev1", manual_position=75.0, timestamp=1787180000.0,
        )
        asyncio.run(store.update(req))
        hub.publish.assert_called_once()
        payload = hub.publish.call_args[0][0]
        assert payload["type"] == "manual_override"
        assert payload["device_id"] == "dev1"
        assert payload["manual_position"] == 75.0

    def test_update_publishes_to_event_bus(self):
        bus = AsyncMock()
        store = ManualOverrideStore(event_bus=bus)
        req = ManualOverrideRequest(
            device_id="dev1", manual_position=75.0, timestamp=1787180000.0,
        )
        asyncio.run(store.update(req))
        bus.publish.assert_awaited_once()
        args = bus.publish.call_args
        assert args[0][0] == "manual_override"

    def test_update_merges_with_existing(self):
        store = self._make_store()
        req1 = ManualOverrideRequest(
            device_id="dev1", manual_position=75.0,
            subjective_intensity=40, timestamp=1787180000.0,
        )
        asyncio.run(store.update(req1))

        req2 = ManualOverrideRequest(
            device_id="dev1", manual_position=80.0,
            subjective_intensity=0,  # default = keep old
            timestamp=1787180010.0,
        )
        result = asyncio.run(store.update(req2))
        assert result.manual_position == 80.0
        assert result.subjective_intensity == 40  # kept from first request

    def test_update_overrides_intensity_when_provided(self):
        store = self._make_store()
        req1 = ManualOverrideRequest(
            device_id="dev1", manual_position=75.0,
            subjective_intensity=40, timestamp=1787180000.0,
        )
        asyncio.run(store.update(req1))

        req2 = ManualOverrideRequest(
            device_id="dev1", manual_position=80.0,
            subjective_intensity=60,  # explicit new value
            timestamp=1787180010.0,
        )
        result = asyncio.run(store.update(req2))
        assert result.subjective_intensity == 60

    def test_get_returns_latest(self):
        store = self._make_store()
        req = ManualOverrideRequest(
            device_id="dev1", manual_position=75.0, timestamp=1787180000.0,
        )
        asyncio.run(store.update(req))
        override = store.get("dev1")
        assert override is not None
        assert override.manual_position == 75.0

    def test_get_returns_none_for_unknown(self):
        store = self._make_store()
        assert store.get("nonexistent") is None

    def test_get_all(self):
        store = self._make_store()
        for i in range(3):
            req = ManualOverrideRequest(
                device_id=f"dev{i}", manual_position=float(i * 10),
                timestamp=1787180000.0,
            )
            asyncio.run(store.update(req))
        all_overrides = store.get_all()
        assert len(all_overrides) == 3

    def test_get_authoritative_position(self):
        store = self._make_store()
        req = ManualOverrideRequest(
            device_id="dev1", manual_position=75.0, timestamp=1787180000.0,
        )
        asyncio.run(store.update(req))
        assert store.get_authoritative_position("dev1") == 75.0
        assert store.get_authoritative_position("unknown") is None

    def test_history_records_all_updates(self):
        store = self._make_store()
        for i in range(5):
            req = ManualOverrideRequest(
                device_id="dev1", manual_position=float(i * 10),
                timestamp=1787180000.0 + i,
            )
            asyncio.run(store.update(req))
        hist = store.history("dev1")
        assert len(hist) == 5
        assert hist[0].manual_position == 0.0
        assert hist[-1].manual_position == 40.0

    def test_history_limit(self):
        store = self._make_store()
        for i in range(5):
            req = ManualOverrideRequest(
                device_id="dev1", manual_position=float(i),
                timestamp=1787180000.0 + i,
            )
            asyncio.run(store.update(req))
        hist = store.history("dev1", limit=2)
        assert len(hist) == 2

    def test_clear_single_device(self):
        store = self._make_store()
        for i in range(3):
            req = ManualOverrideRequest(
                device_id=f"dev{i}", manual_position=float(i),
                timestamp=1787180000.0,
            )
            asyncio.run(store.update(req))
        store.clear("dev1")
        assert store.get("dev1") is None
        assert store.get("dev0") is not None
        assert store.get("dev2") is not None

    def test_clear_all(self):
        store = self._make_store()
        for i in range(3):
            req = ManualOverrideRequest(
                device_id=f"dev{i}", manual_position=float(i),
                timestamp=1787180000.0,
            )
            asyncio.run(store.update(req))
        store.clear()
        assert store.get_all() == {}

    def test_clear_unknown_device_no_error(self):
        store = self._make_store()
        store.clear("nonexistent")  # should not raise

    def test_snapshot_returns_all(self):
        store = self._make_store()
        req = ManualOverrideRequest(
            device_id="dev1", manual_position=75.0, timestamp=1787180000.0,
        )
        asyncio.run(store.update(req))
        snap = store.snapshot()
        assert "dev1" in snap
        assert snap["dev1"]["manual_position"] == 75.0

    def test_default_timestamp_uses_server_time(self):
        store = self._make_store()
        before = time.time()
        req = ManualOverrideRequest(
            device_id="dev1", manual_position=50.0,
        )
        result = asyncio.run(store.update(req))
        assert result.timestamp >= before


# ── Merged Telemetry ──────────────────────────────────────────────────────


class TestMergedTelemetry:
    """状态合并逻辑测试。"""

    def test_merge_with_no_hardware(self):
        store = ManualOverrideStore()
        req = ManualOverrideRequest(
            device_id="dev1", manual_position=75.0,
            subjective_intensity=40, timestamp=1787180000.0,
        )
        asyncio.run(store.update(req))
        merged = store.get_merged_telemetry("dev1", None)
        assert merged["position"] == 75.0
        assert merged["position_source"] == "manual_override"
        assert merged["manual_position"] == 75.0

    def test_merge_with_hardware_without_position(self):
        store = ManualOverrideStore()
        req = ManualOverrideRequest(
            device_id="dev1", manual_position=75.0, timestamp=1787180000.0,
        )
        asyncio.run(store.update(req))
        hw = {"battery": 0.8, "signal": -45}
        merged = store.get_merged_telemetry("dev1", hw)
        assert merged["position"] == 75.0
        assert merged["position_source"] == "manual_override"
        assert merged["battery"] == 0.8

    def test_merge_with_hardware_with_position(self):
        store = ManualOverrideStore()
        req = ManualOverrideRequest(
            device_id="dev1", manual_position=75.0, timestamp=1787180000.0,
        )
        asyncio.run(store.update(req))
        hw = {"position": 60.0, "battery": 0.8}
        merged = store.get_merged_telemetry("dev1", hw)
        assert merged["position"] == 60.0  # hardware wins
        assert merged["position_source"] == "hardware"
        assert merged["manual_position"] == 75.0  # still available

    def test_merge_without_override(self):
        store = ManualOverrideStore()
        hw = {"position": 60.0, "battery": 0.8}
        merged = store.get_merged_telemetry("dev1", hw)
        assert merged["position"] == 60.0
        assert merged["position_source"] == "hardware"

    def test_merge_without_override_no_position(self):
        store = ManualOverrideStore()
        merged = store.get_merged_telemetry("dev1", {"battery": 0.8})
        assert "position" not in merged
        assert "position_source" not in merged


# ── Broadcast Callback ────────────────────────────────────────────────────


class TestBroadcastCallback:
    """自定义广播回调测试。"""

    def test_on_broadcast_called(self):
        callback = MagicMock()
        store = ManualOverrideStore(on_broadcast=callback)
        req = ManualOverrideRequest(
            device_id="dev1", manual_position=75.0, timestamp=1787180000.0,
        )
        asyncio.run(store.update(req))
        callback.assert_called_once()
        payload = callback.call_args[0][0]
        assert payload["type"] == "manual_override"

    def test_async_on_broadcast(self):
        callback = AsyncMock()
        store = ManualOverrideStore(on_broadcast=callback)
        req = ManualOverrideRequest(
            device_id="dev1", manual_position=75.0, timestamp=1787180000.0,
        )
        asyncio.run(store.update(req))
        callback.assert_awaited_once()

    def test_broadcast_exception_does_not_propagate(self):
        def bad_callback(payload: dict) -> None:
            raise RuntimeError("broadcast failed")

        store = ManualOverrideStore(on_broadcast=bad_callback)
        req = ManualOverrideRequest(
            device_id="dev1", manual_position=75.0, timestamp=1787180000.0,
        )
        # should not raise
        asyncio.run(store.update(req))
