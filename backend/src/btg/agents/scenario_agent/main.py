"""CLI entry point for a standalone Scenario Agent process."""
from __future__ import annotations

import argparse
import asyncio
import os

from .client import BTGClient, GatewayWebSocketSource, WebSocketEventPublisher
from .models import ScenarioParser
from .runner import ScenarioRunner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", help="path to a YAML scenario")
    parser.add_argument("--gateway-url", default=os.getenv("BTG_GATEWAY_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--events-ws", default=os.getenv("BTG_EVENTS_WS", "ws://127.0.0.1:8000/ws/events"))
    parser.add_argument("--publish-ws", default=os.getenv("BTG_PUBLISH_WS", "ws://127.0.0.1:8000/ws/events/publish"))
    parser.add_argument("--session-id", default=os.getenv("BTG_CONTROL_SESSION_ID"), required=os.getenv("BTG_CONTROL_SESSION_ID") is None)
    parser.add_argument("--token", default=os.getenv("BTG_AGENT_TOKEN"), required=os.getenv("BTG_AGENT_TOKEN") is None)
    args = parser.parse_args()
    scenario = ScenarioParser.load_file(args.scenario)
    runner = ScenarioRunner(
        scenario,
        BTGClient(args.gateway_url, args.token, session_id=args.session_id),
        GatewayWebSocketSource(args.events_ws, args.token),
        WebSocketEventPublisher(args.publish_ws, args.token),
    )
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
