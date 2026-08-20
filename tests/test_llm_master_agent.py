"""Offline closed-loop test: mocked LLM output is locally constrained."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from btg.agents.llm_master_agent.context import TelemetryContext
from btg.agents.llm_master_agent.contracts import SafetyWrapper, UnifiedControlCommand
from btg.agents.llm_master_agent.llm import MockLLMTransport, parse_decision


def test_mocked_llm_closed_loop_cannot_escalate() -> None:
    async def exercise() -> None:
        context = TelemetryContext(
            heart_rate_bpm=110.0,
            imu_struggling=False,
            current_intensities={"A": 30},
            current_duration_ms=500,
            session_id="approved-session",
            session_authorized=True,
            captured_at=datetime.now(timezone.utc),
        )
        model = MockLLMTransport('{"dialogue":"Continue.","control":{"action":"set","channel":"A","intensity":99,"duration_ms":5000}}')
        _, raw_control = parse_decision(await model.complete(context, include_image=False))
        payload = SafetyWrapper(max_system_intensity=50).to_gateway_payload(UnifiedControlCommand.from_llm(raw_control), context)
        assert payload == {"channel": "A", "intensity": 30, "duration_ms": 500, "session_id": "approved-session"}

    asyncio.run(exercise())


def test_unauthorized_context_never_yields_gateway_payload() -> None:
    context = TelemetryContext(None, False, {"A": 30}, 500, None, False)
    command = UnifiedControlCommand.from_llm({"action": "stop"})
    assert SafetyWrapper(max_system_intensity=50).to_gateway_payload(command, context) is None


if __name__ == "__main__":
    test_mocked_llm_closed_loop_cannot_escalate()
    test_unauthorized_context_never_yields_gateway_payload()
    print("llm master agent smoke ok")
