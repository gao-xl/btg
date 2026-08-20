"""独立剧情运行入口。

用法（剧本文件 -> 导入 -> 连接网关执行）：

    python -m btg.story script.txt --gateway-url http://127.0.0.1:8000 \\
        --events-ws ws://127.0.0.1:8000/ws/events \\
        --publish-ws ws://127.0.0.1:8000/ws/events/publish \\
        --session-id <id> --token <token>

剧本文件内容为一自然语言剧情（默认规则 DSL 解析）。运行依赖可选包
``websockets`` 与可达的网关；缺失时加载阶段即给出明确提示。
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from .engine import StoryEngine
from .importers import RuleBasedStoryImporter
from .runtime import GatewayActuatorWriter, gateway_event_sink, gateway_event_source


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a story script against a BTG gateway")
    parser.add_argument("script", help="path to a natural-language story script (.txt)")
    parser.add_argument("--gateway-url", default=os.getenv("BTG_GATEWAY_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--events-ws", default=os.getenv("BTG_EVENTS_WS", "ws://127.0.0.1:8000/ws/events"))
    parser.add_argument("--publish-ws", default=os.getenv("BTG_PUBLISH_WS", "ws://127.0.0.1:8000/ws/events/publish"))
    parser.add_argument("--session-id", default=os.getenv("BTG_CONTROL_SESSION_ID"), required=os.getenv("BTG_CONTROL_SESSION_ID") is None)
    parser.add_argument("--token", default=os.getenv("BTG_AGENT_TOKEN"), required=os.getenv("BTG_AGENT_TOKEN") is None)
    parser.add_argument("--story-id", help="explicit story id (default: file stem)")
    return parser


async def _run(args: argparse.Namespace) -> int:
    text = Path(args.script).read_text(encoding="utf-8")
    story_id = args.story_id or Path(args.script).stem
    story = await RuleBasedStoryImporter().import_story(text, story_id=story_id)
    writer = GatewayActuatorWriter(args.gateway_url, args.token, session_id=args.session_id)
    source = gateway_event_source(args.events_ws, args.token)
    sink = gateway_event_sink(args.publish_ws, args.token)
    engine = StoryEngine(story, writer, source, sink)
    state = await engine.run()
    print(f"story finished: {state.value}")
    return 0


def main() -> None:
    args = _build_parser().parse_args()
    try:
        asyncio.run(_run(args))
    except FileNotFoundError as exc:
        print(f"cannot read script: {exc}")
        raise SystemExit(2) from exc
    except ModuleNotFoundError as exc:
        print(f"missing optional dependency for gateway connection: {exc}")
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()