"""YoKonex-inspired gameplay tests; all results remain non-actuating."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _path in (_ROOT / "sdk", _ROOT / "backend" / "src"):
    sys.path.insert(0, str(_path))

import pytest
from fastapi.testclient import TestClient

from btg.bus.app import create_app
from btg.play.models import PlayDecisionRequest, StartPlaySessionRequest
from btg.play.service import PlaySessionError, PlaySessionManager
from helpers import build_gateway


def _session(manager: PlaySessionManager):
    return manager.start(StartPlaySessionRequest(
        control_session_id="authorized-control-reference",
        consent_confirmed=True,
        channels="AB",
        part_a="left",
        part_b="right",
        cap_a=20,
        cap_b=35,
    ))


def test_catalog_contains_yokonex_style_presets_with_bounded_frames() -> None:
    manager = PlaySessionManager()
    assert set(manager.catalog.keys()) == {
        "breathe", "tide", "combo", "fast_pinch", "pinch_crescendo",
        "heartbeat", "compress", "rhythm_step",
    }
    assert max(manager.catalog.get("breathe").preview(20)) <= 20


def test_wave_recommendation_is_preview_only_and_scaled_per_channel() -> None:
    manager = PlaySessionManager()
    session = _session(manager)
    decision = PlayDecisionRequest.model_validate({
        "dialogue": "Try a heartbeat pattern.",
        "directive": {"action": "recommend_wave", "channel": "AB", "wave": "heartbeat"},
    })
    result = manager.evaluate(session.id, decision)
    assert result["actuated"] is False
    assert result["operator_confirmation_required"] is True
    assert max(result["previews"]["A"]) <= 20
    assert max(result["previews"]["B"]) <= 35


def test_ai_reduce_rejects_any_strength_increase() -> None:
    manager = PlaySessionManager()
    session = _session(manager)
    decision = PlayDecisionRequest.model_validate({
        "dialogue": "Changing level.",
        "directive": {"action": "reduce", "channel": "A", "target_strength": 21},
        "current_strengths": {"A": 20},
    })
    with pytest.raises(PlaySessionError, match="cannot increase"):
        manager.evaluate(session.id, decision)


def test_consent_and_channel_scope_are_enforced() -> None:
    manager = PlaySessionManager()
    with pytest.raises(PlaySessionError, match="consent"):
        manager.start(StartPlaySessionRequest(control_session_id="s", consent_confirmed=False))

    session = manager.start(StartPlaySessionRequest(
        control_session_id="s", consent_confirmed=True, channels="A", cap_a=10,
    ))
    decision = PlayDecisionRequest.model_validate({
        "dialogue": "B is outside scope.",
        "directive": {"action": "recommend_random", "channel": "B"},
    })
    with pytest.raises(PlaySessionError, match="outside"):
        manager.evaluate(session.id, decision)


def test_play_rest_flow_never_actuates(tmp_path: Path) -> None:
    client = TestClient(create_app(build_gateway(tmp_path)))
    waves = client.get("/api/v1/play/waves")
    assert waves.status_code == 200
    assert len(waves.json()["data"]) == 8

    started = client.post("/api/v1/play/sessions", json={
        "control_session_id": "control-1",
        "consent_confirmed": True,
        "channels": "A",
        "cap_a": 15,
        "cap_b": 0,
    })
    assert started.status_code == 201
    session = started.json()["data"]
    assert session["actuation_enabled"] is False

    evaluated = client.post(f"/api/v1/play/sessions/{session['id']}/decisions", json={
        "dialogue": "A gentle suggestion.",
        "directive": {"action": "recommend_wave", "channel": "A", "wave": "breathe"},
    })
    assert evaluated.status_code == 200
    assert evaluated.json()["data"]["actuated"] is False

    stopped = client.delete(f"/api/v1/play/sessions/{session['id']}")
    assert stopped.json()["data"] == {"id": session["id"], "stopped": True, "actuated": False}


def test_play_sessions_expire_and_are_bounded() -> None:
    now = [100.0]
    manager = PlaySessionManager(max_sessions=1, session_ttl_seconds=10, clock=lambda: now[0])
    session = _session(manager)
    with pytest.raises(PlaySessionError, match="too many"):
        _session(manager)
    now[0] = 111.0
    with pytest.raises(PlaySessionError, match="expired"):
        manager.get(session.id)
    assert _session(manager).id != session.id
