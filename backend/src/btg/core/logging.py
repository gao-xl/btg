"""结构化日志配置。

面向多模块复用，提供统一初始化入口与命名 logger 获取函数。
安全事件（急停/截断/心跳超时）使用独立 audit logger，便于审计检索。
"""
from __future__ import annotations

import json
import logging
import sys

AUDIT_LOGGER_NAME = "btg.security"


class JsonFormatter(logging.Formatter):
    """将日志记录格式化为单行 JSON，便于采集与审计。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int = logging.INFO, json_format: bool = False) -> None:
    """初始化根日志。幂等：重复调用重置 handler、级别与格式。

    Args:
        level: 日志级别（如 ``logging.INFO``）。
        json_format: True 输出单行 JSON；False 输出人类可读格式。
    """
    root = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root.handlers = [handler]
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """返回命名 logger。"""
    return logging.getLogger(name)


def get_audit_logger() -> logging.Logger:
    """返回安全审计专用 logger（标记急停/截断/心跳超时等事件）。"""
    return logging.getLogger(AUDIT_LOGGER_NAME)