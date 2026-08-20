"""Run the BTG Game Agent.

Example (PowerShell):
  $env:BTG_GAME_AGENT_ENABLED='true'
  $env:BTG_GAME_LOG='C:\\games\\game_events.log'
  $env:BTG_GATEWAY_URL='http://127.0.0.1:8000'
  python -m btg.agents.game_agent.main
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
import logging
import os
from pathlib import Path
import random
import signal
from typing import AsyncIterator, Any

try:  # Supports both ``python -m agents.game_agent.main`` and direct execution.
    from .client import BTGClient, GatewayUnavailable
    from .events import EventMapper, parse_event_line
except ImportError:  # pragma: no cover - direct-script fallback
    from client import BTGClient, GatewayUnavailable
    from events import EventMapper, parse_event_line


LOG = logging.getLogger("btg.game_agent")


class LogTailer:
    """Polling, rotation-tolerant asynchronous ``tail -f`` implementation."""

    def __init__(self, path: Path, *, poll_interval_s: float = 0.25, from_end: bool = True) -> None:
        self._path = path
        self._poll_interval_s = poll_interval_s
        self._from_end = from_end

    async def lines(self) -> AsyncIterator[str]:
        position: int | None = None
        file_id: tuple[int, int] | None = None
        while True:
            try:
                stat = self._path.stat()
                current_id = (stat.st_dev, stat.st_ino)
                if position is None or file_id != current_id or stat.st_size < position:
                    position = stat.st_size if self._from_end else 0
                    file_id = current_id
                with self._path.open("r", encoding="utf-8", errors="replace") as stream:
                    stream.seek(position)
                    new_lines = stream.readlines()
                    position = stream.tell()
                for line in new_lines:
                    yield line
            except FileNotFoundError:
                LOG.warning("Waiting for game log: %s", self._path)
            except OSError as exc:
                LOG.warning("Unable to read game log %s: %s", self._path, exc)
            await asyncio.sleep(self._poll_interval_s)


async def _send_with_retry(client: BTGClient, queue: asyncio.Queue[dict[str, Any]]) -> None:
    while True:
        payload = await queue.get()
        delay_s = 1.0
        try:
            while True:
                try:
                    await client.send_control(payload)
                    LOG.info("Control sent: %s", payload)
                    break
                except GatewayUnavailable as exc:
                    # Full jitter prevents many agents reconnecting in lockstep.
                    wait_s = random.uniform(0, delay_s)
                    LOG.warning("Gateway unavailable (%s); retrying in %.2fs", exc, wait_s)
                    await asyncio.sleep(wait_s)
                    delay_s = min(delay_s * 2, 30.0)
        finally:
            queue.task_done()


async def run(args: argparse.Namespace) -> None:
    if not args.enabled:
        LOG.warning("Agent is disabled. Set BTG_GAME_AGENT_ENABLED=true or pass --enable to send controls.")
    mapper = EventMapper()
    if args.rules_file is not None:
        mapper.reload_from_file(args.rules_file)
        LOG.info("Loaded game mapping rules from %s", args.rules_file)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=args.queue_size)
    worker = asyncio.create_task(
        _send_with_retry(BTGClient(args.gateway_url, api_token=args.api_token, timeout_s=args.timeout_s), queue)
    )
    try:
        async for line in LogTailer(args.log_file, poll_interval_s=args.poll_interval_s, from_end=not args.read_existing).lines():
            event = parse_event_line(line)
            if event is None:
                continue
            payload = mapper.map(event)
            if payload is None:
                continue
            if args.enabled:
                await queue.put(payload)  # intentional backpressure preserves event order
                LOG.info("Queued %s -> %s", event.name, payload)
            else:
                LOG.info("Dry run %s -> %s", event.name, payload)
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BTG game telemetry and control agent")
    parser.add_argument("--log-file", type=Path, default=Path(os.getenv("BTG_GAME_LOG", "game_events.log")))
    parser.add_argument("--gateway-url", default=os.getenv("BTG_GATEWAY_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--api-token", default=os.getenv("BTG_API_TOKEN"))
    parser.add_argument("--enable", action="store_true", default=os.getenv("BTG_GAME_AGENT_ENABLED", "").lower() == "true")
    parser.add_argument("--read-existing", action="store_true", help="Process existing lines instead of starting at EOF")
    parser.add_argument("--queue-size", type=int, default=int(os.getenv("BTG_GAME_QUEUE_SIZE", "1000")))
    parser.add_argument(
        "--rules-file",
        type=Path,
        default=Path(os.getenv("BTG_GAME_RULES", Path(__file__).with_name("game_rules.yaml"))),
        help="YAML mapping rules; replace or reload it through EventMapper for hot tuning",
    )
    parser.add_argument("--poll-interval-s", type=float, default=0.25)
    parser.add_argument("--timeout-s", type=float, default=5.0)
    return parser


def main() -> None:
    logging.basicConfig(level=os.getenv("BTG_GAME_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args()
    if args.queue_size <= 0 or args.poll_interval_s <= 0 or args.timeout_s <= 0:
        raise SystemExit("queue size, poll interval and timeout must be positive")
    with suppress(NotImplementedError):
        signal.signal(signal.SIGTERM, lambda *_: raise_keyboard_interrupt())
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        LOG.info("Game agent stopped")


def raise_keyboard_interrupt() -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    main()
