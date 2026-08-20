"""Contract tests for the YOKONEX local API-bridge actuator."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "sdk"))
sys.path.insert(0, str(_ROOT / "backend" / "src"))

from btg.hal.actuators.yokonex_im import YokoNexImActuator  # noqa: E402


def _config(**overrides):
    config = {
        "instance_id": "yokonex_output:yokonex_im:0",
        "bridge_url": "http://127.0.0.1:3001",
        "levels": [
            {"max_value": 25, "command_id": "gentle"},
            {"max_value": 50, "command_id": "medium"},
            {"max_value": 100, "command_id": "strong"},
        ],
    }
    config.update(overrides)
    return config


def _device(handler) -> YokoNexImActuator:
    device = YokoNexImActuator(_config())
    device._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return device


def test_connect_mapping_zero_and_stop_are_fail_closed() -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "imReady": True})
        assert request.url.path == "/api/send-command"
        sent.append(request.read().decode())
        return httpx.Response(200, json={"success": True})

    device = _device(handler)

    async def scenario() -> None:
        assert await device.connect() is True
        assert await device.set_target("yokonex_output", 20.0) is True
        assert await device.set_target("yokonex_output", 30.0) is True
        assert await device.set_target("yokonex_output", 0.0) is True
        await device.stop()
        assert device._connected is False
        assert device._client is None

    asyncio.run(scenario())
    assert sent == [
        '{"commandId":"gentle"}',
        '{"commandId":"medium"}',
        '{"commandId":"_stop_all"}',
        '{"commandId":"_stop_all"}',
    ]


def test_connect_rejects_bridge_when_im_is_not_ready() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok", "imReady": False})

    device = _device(handler)
    with pytest.raises(ConnectionError, match="IM is not ready"):
        asyncio.run(device.connect())
    assert device._client is None


def test_command_failure_marks_connection_unhealthy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "imReady": True})
        return httpx.Response(503, json={"success": False, "message": "IM 未就绪"})

    device = _device(handler)

    async def scenario() -> None:
        await device.connect()
        with pytest.raises(ConnectionError, match="command 'strong' failed"):
            await device.set_target("yokonex_output", 80.0)
        assert device._connected is False
        await device.disconnect()

    asyncio.run(scenario())


def test_remote_bridge_requires_explicit_opt_in() -> None:
    with pytest.raises(ValidationError, match="remote API-bridge is disabled"):
        YokoNexImActuator(_config(bridge_url="http://192.0.2.10:3001"))

    device = YokoNexImActuator(
        _config(bridge_url="https://bridge.example.test", allow_remote_bridge=True)
    )
    assert device.bridge_url == "https://bridge.example.test"

    with pytest.raises(ValidationError, match="requires HTTPS"):
        YokoNexImActuator(
            _config(bridge_url="http://bridge.example.test", allow_remote_bridge=True)
        )


def test_levels_must_cover_full_normalized_range() -> None:
    with pytest.raises(ValidationError, match="max_value=100"):
        YokoNexImActuator(
            _config(levels=[{"max_value": 50, "command_id": "only_half"}])
        )


def test_rejects_wrong_channel_and_out_of_range_value() -> None:
    device = YokoNexImActuator(_config())
    device._connected = True
    device._client = object()

    with pytest.raises(ValueError, match="belongs to channel"):
        asyncio.run(device.set_target("another_channel", 10.0))
    with pytest.raises(ValueError, match=r"values in \[0, 100\]"):
        asyncio.run(device.set_target("yokonex_output", 101.0))
