"""剧本人格市场冒烟测试：元数据契约、注册中心、切换与内置剧本。

独立运行：``python tests/test_persona.py``
pytest 运行：``pytest tests/``
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "sdk"))
sys.path.insert(0, str(_ROOT / "backend" / "src"))

import pytest  # noqa: E402

from btg.persona import (  # noqa: E402
    HardwareStrategy,
    PersonaService,
    PersonaServiceError,
    ScenarioManifest,
    builtin_catalog,
)


def _manifest(scenario_id: str = "test_v1", **overrides) -> ScenarioManifest:
    data = {
        "scenario_id": scenario_id,
        "name": "Test Persona",
        "system_prompt": "you are a test",
        "hardware_strategy": {"heart_rate_multiplier": 1.2, "max_allowed_intensity": 50},
    }
    data.update(overrides)
    return ScenarioManifest.model_validate(data)


# ------------------------------------------------------------------ #
# 元数据契约
# ------------------------------------------------------------------ #
def test_manifest_defaults() -> None:
    m = ScenarioManifest.model_validate(
        {"scenario_id": "x", "name": "X", "system_prompt": "hi"}
    )
    assert m.hardware_strategy.max_allowed_intensity == 100.0
    assert m.hardware_strategy.allow_ai_full_control is False
    assert m.author == "BTG-Community"


def test_manifest_rejects_bad_intensity() -> None:
    with pytest.raises(ValueError):
        _manifest(hardware_strategy={"max_allowed_intensity": 150})


def test_manifest_rejects_bad_id() -> None:
    with pytest.raises(ValueError):
        _manifest(scenario_id="has space")


def test_metadata_digest_omits_prompt() -> None:
    digest = _manifest().metadata_digest()
    assert "system_prompt" not in digest
    assert digest["hardware_strategy"]["max_allowed_intensity"] == 50


def test_builtin_catalog_has_two() -> None:
    catalog = builtin_catalog()
    ids = {p["scenario_id"] for p in catalog}
    assert {"gentle_healing", "cyber_interrogator_v2"} <= ids


# ------------------------------------------------------------------ #
# 注册中心
# ------------------------------------------------------------------ #
def test_service_install_activate_deactivate() -> None:
    hook_calls = []
    service = PersonaService(on_activate=lambda m: hook_calls.append(m))
    service.install(_manifest())

    activated = service.activate("test_v1")
    assert activated.scenario_id == "test_v1"
    assert service.active().scenario_id == "test_v1"
    assert len(hook_calls) == 1

    service.deactivate()
    assert service.active() is None
    assert hook_calls[-1] is None


def test_service_activate_hook_sets_intensity_limit() -> None:
    seen = {}
    service = PersonaService(on_activate=lambda m: seen.update(max=m.hardware_strategy.max_allowed_intensity if m else None))
    service.install(_manifest())
    service.activate("test_v1")
    assert seen["max"] == 50
    service.deactivate()
    assert seen["max"] is None


def test_service_delete_active_deactivates() -> None:
    service = PersonaService()
    service.install(_manifest())
    service.activate("test_v1")
    service.delete("test_v1")
    assert service.active() is None
    assert service.count() == 0


def test_service_install_builtin_idempotent() -> None:
    service = PersonaService()
    first = service.install_builtin()
    second = service.install_builtin()
    assert len(first) == 2
    assert second == []
    assert service.count() == 2


def test_service_errors() -> None:
    service = PersonaService()
    with pytest.raises(PersonaServiceError):
        service.get("missing")
    with pytest.raises(PersonaServiceError):
        service.activate("missing")
    service.install(_manifest())
    with pytest.raises(PersonaServiceError):
        service.install(_manifest())