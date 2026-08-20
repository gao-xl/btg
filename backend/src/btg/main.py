"""BTG 网关进程入口：装配 Gateway 并启动 ASGI 服务（uvicorn）。

运行：``python -m btg.main``（缺省监听 0.0.0.0:8000）。
"""
from __future__ import annotations

import uvicorn

from btg.bus.app import create_app
from btg.core import setup_logging
from btg.gateway import Gateway
from btg.settings import AppSettings


def main() -> None:
    settings = AppSettings.from_env()
    setup_logging(
        level=getattr(__import__("logging"), settings.log_level.upper(), 20),
        json_format=settings.json_logs,
    )
    gateway = Gateway(settings=settings)
    app = create_app(gateway)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()