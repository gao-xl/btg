"""Entrypoint for the consent-gated BTG LLM Master Agent."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
import sys

try:  # Supports ``python -m`` and direct execution from the repository root.
    from btg.agents.game_agent.client import BTGClient, GatewayUnavailable
    from .context import WebSocketTelemetrySource
    from .contracts import ControlContractError, SafetyWrapper, UnifiedControlCommand
    from .llm import parse_decision, resolve_transport
except ImportError:  # pragma: no cover - direct-script fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
    from btg.agents.game_agent.client import BTGClient, GatewayUnavailable
    from btg.agents.llm_master_agent.context import WebSocketTelemetrySource
    from btg.agents.llm_master_agent.contracts import ControlContractError, SafetyWrapper, UnifiedControlCommand
    from btg.agents.llm_master_agent.llm import parse_decision, resolve_transport


LOG = logging.getLogger("btg.llm_master_agent")


async def run_once(args: argparse.Namespace) -> None:
    context = await WebSocketTelemetrySource(args.telemetry_ws, image_path=args.latest_image).fetch()
    if not context.session_authorized or not context.session_id:
        LOG.warning("No authorized control session; refusing LLM and gateway calls")
        return
    include_image = args.allow_image_upload and context.image_path is not None
    text = await resolve_transport().complete(context, include_image=include_image)
    dialogue, raw_command = parse_decision(text)
    LOG.info("LLM dialogue: %s", dialogue)
    try:
        command = UnifiedControlCommand.from_llm(raw_command)
    except ControlContractError as exc:
        LOG.warning("Rejected invalid LLM control: %s", exc)
        return
    payload = SafetyWrapper(max_system_intensity=args.max_system_intensity).to_gateway_payload(command, context)
    if payload is None:
        LOG.warning("Safety wrapper rejected an unauthorized or escalating control request")
        return
    try:
        await BTGClient(args.gateway_url, api_token=args.api_token).send_control(payload)
    except GatewayUnavailable as exc:
        LOG.warning("Gateway unavailable; no command was retried: %s", exc)


async def run_forever(args: argparse.Namespace) -> None:
    while True:
        try:
            await run_once(args)
        except Exception:  # noqa: BLE001 - long-running agent must fail closed and continue observing
            LOG.exception("LLM cycle failed safely")
        await asyncio.sleep(args.interval_s)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BTG consent-gated LLM master agent")
    parser.add_argument("--telemetry-ws", default=os.getenv("BTG_TELEMETRY_WS", "ws://127.0.0.1:8000/ws"))
    parser.add_argument("--gateway-url", default=os.getenv("BTG_GATEWAY_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--api-token", default=os.getenv("BTG_API_TOKEN"))
    parser.add_argument("--latest-image", type=Path, default=Path(os.getenv("BTG_LATEST_IMAGE", "latest.jpg")))
    parser.add_argument("--allow-image-upload", action="store_true", default=os.getenv("BTG_ALLOW_IMAGE_UPLOAD", "").lower() == "true")
    parser.add_argument("--max-system-intensity", type=int, default=int(os.getenv("BTG_MAX_SYSTEM_INTENSITY", "50")))
    parser.add_argument("--interval-s", type=float, default=float(os.getenv("BTG_LLM_INTERVAL_S", "5")))
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> None:
    logging.basicConfig(level=os.getenv("BTG_LLM_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args()
    if args.interval_s <= 0:
        raise SystemExit("interval must be positive")
    if not 0 <= args.max_system_intensity <= 100:
        raise SystemExit("max system intensity must be in [0, 100]")
    asyncio.run(run_once(args) if args.once else run_forever(args))


if __name__ == "__main__":
    main()
