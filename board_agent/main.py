"""板端薄代理入口：``python -m board_agent.main --config config.yaml``。"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


def _load_config(path: Path):
    if yaml is None:
        raise RuntimeError("缺少 pyyaml，请在板端 `pip install pyyaml`")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def main() -> None:
    parser = argparse.ArgumentParser(description="BTG 板端薄代理")
    parser.add_argument("-c", "--config", default="config.yaml", type=Path)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    from .agent import BoardAgent
    from .config import AgentConfig

    config = AgentConfig.from_dict(_load_config(args.config))
    asyncio.run(BoardAgent(config).run())


if __name__ == "__main__":
    main()