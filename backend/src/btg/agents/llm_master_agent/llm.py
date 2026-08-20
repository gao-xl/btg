"""Provider-neutral async LLM request and strict response parsing."""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .context import TelemetryContext


SYSTEM_PROMPT = """You are a fictional cybernetic interrogator in a consensual game.
Return ONLY one JSON object: {"dialogue": string, "control": object}.
control must be exactly one of:
{"action":"stop"}, {"action":"pause"}, or
{"action":"set","channel":"A"|"B","intensity":integer,"duration_ms":integer}.
Never claim consent, never ask to resume output, and prefer pause/stop when telemetry is concerning.
Your suggested set values may only maintain or reduce the supplied active output; the local safety layer enforces this.
"""


class LLMTransport(Protocol):
    async def complete(self, context: TelemetryContext, *, include_image: bool) -> str: ...


class MockLLMTransport:
    """Offline transport used by tests and by the safe default configuration."""

    def __init__(self, response: str | None = None) -> None:
        self._response = response or '{"dialogue":"Telemetry acknowledged.","control":{"action":"pause"}}'

    async def complete(self, context: TelemetryContext, *, include_image: bool) -> str:
        return self._response


class OpenAICompatibleTransport:
    """OpenAI-compatible ``/v1/chat/completions`` transport using stdlib HTTP."""

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self._url = f"{base_url.rstrip('/')}/v1/chat/completions"
        self._api_key = api_key
        self._model = model

    async def complete(self, context: TelemetryContext, *, include_image: bool) -> str:
        content: list[dict[str, Any]] = [{"type": "text", "text": json.dumps(context.prompt_data())}]
        if include_image and context.image_path:
            content.append({"type": "image_url", "image_url": {"url": _as_data_url(context.image_path)}})
        request_data = {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}],
        }
        response = await asyncio.to_thread(_post_json, self._url, request_data, {"Authorization": f"Bearer {self._api_key}"})
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("OpenAI-compatible response has no message content") from exc


class AnthropicTransport:
    """Anthropic Messages API transport; selected with ``BTG_LLM_PROVIDER=anthropic``."""

    def __init__(self, *, api_key: str, model: str, base_url: str = "https://api.anthropic.com") -> None:
        self._url = f"{base_url.rstrip('/')}/v1/messages"
        self._api_key = api_key
        self._model = model

    async def complete(self, context: TelemetryContext, *, include_image: bool) -> str:
        content: list[dict[str, Any]] = [{"type": "text", "text": json.dumps(context.prompt_data())}]
        if include_image and context.image_path:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _jpeg_base64(context.image_path)}})
        request_data = {"model": self._model, "max_tokens": 300, "temperature": 0, "system": SYSTEM_PROMPT, "messages": [{"role": "user", "content": content}]}
        response = await asyncio.to_thread(_post_json, self._url, request_data, {"x-api-key": self._api_key, "anthropic-version": "2023-06-01"})
        try:
            return response["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Anthropic response has no text content") from exc


def parse_decision(text: str) -> tuple[str, dict[str, Any]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM response is not valid JSON") from exc
    if not isinstance(data, dict) or set(data) != {"dialogue", "control"} or not isinstance(data["dialogue"], str):
        raise ValueError("LLM response must contain only dialogue and control")
    return data["dialogue"], data["control"]


def _as_data_url(path: Path) -> str:
    return f"data:image/jpeg;base64,{_jpeg_base64(path)}"


def _jpeg_base64(path: Path) -> str:
    if path.suffix.lower() not in {".jpg", ".jpeg"}:
        raise ValueError("only JPEG latest-frame uploads are supported")
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("latest image exceeds 2 MiB upload limit")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return encoded


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("LLM request failed") from exc


def transport_from_env() -> LLMTransport:
    if os.getenv("BTG_LLM_PROVIDER", "mock") == "mock":
        return MockLLMTransport()
    if os.getenv("BTG_LLM_PROVIDER") == "openai":
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is required for BTG_LLM_PROVIDER=openai")
        return OpenAICompatibleTransport(base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com"), api_key=key, model=os.getenv("BTG_LLM_MODEL", "gpt-4.1-mini"))
    if os.getenv("BTG_LLM_PROVIDER") == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for BTG_LLM_PROVIDER=anthropic")
        return AnthropicTransport(api_key=key, model=os.getenv("BTG_LLM_MODEL", "claude-sonnet-4-20250514"), base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"))
    raise RuntimeError("BTG_LLM_PROVIDER must be mock, openai, or anthropic")


def transport_from_settings(ai: Any) -> LLMTransport:
    """按配置中心（``AISettings``）构造传输，供设置页热配置的主控代理使用。

    ``ai`` 为 :class:`btg.config.config_manager.AISettings` 实例（或等价字典）。
    空 ``base_url`` / ``model`` 回退到厂商默认值；空 ``api_key`` 对 openai/anthropic
    视为未配置并抛出，避免静默使用离线兜底而用户误以为已接入。
    """
    provider = getattr(ai, "provider", None) or (ai.get("provider") if isinstance(ai, dict) else None) or "mock"
    key = getattr(ai, "api_key", None) or (ai.get("api_key") if isinstance(ai, dict) else None) or ""
    base_url = getattr(ai, "base_url", None) or (ai.get("base_url") if isinstance(ai, dict) else None) or ""
    model = getattr(ai, "model", None) or (ai.get("model") if isinstance(ai, dict) else None) or ""
    if provider == "mock":
        return MockLLMTransport()
    if provider == "openai":
        if not key:
            raise RuntimeError("OpenAI API key is required (configure it in the settings page)")
        return OpenAICompatibleTransport(
            base_url=base_url or "https://api.openai.com",
            api_key=key,
            model=model or "gpt-4.1-mini",
        )
    if provider == "anthropic":
        if not key:
            raise RuntimeError("Anthropic API key is required (configure it in the settings page)")
        return AnthropicTransport(
            api_key=key,
            model=model or "claude-sonnet-4-20250514",
            base_url=base_url or "https://api.anthropic.com",
        )
    raise RuntimeError("provider must be mock, openai, or anthropic")


def resolve_transport() -> LLMTransport:
    """优先读环境变量（CI / 本地调试），否则回退到配置中心的热配置。

    环境变量 ``BTG_LLM_PROVIDER`` 存在时沿用 :func:`transport_from_env`，
    保证既有测试与手动调试方式不变；否则从 ``config/settings.yaml`` 的 ``ai`` 读取。
    """
    if os.getenv("BTG_LLM_PROVIDER"):
        return transport_from_env()
    try:
        from btg.config.config_manager import config_manager

        return transport_from_settings(config_manager.get_settings().ai)
    except Exception:  # noqa: BLE001 - 读取失败安全回退离线传输
        logger = logging.getLogger("btg.llm_master_agent")
        logger.warning("无法从设置中心读取 AI 配置，回退到 mock 传输")
        return MockLLMTransport()
