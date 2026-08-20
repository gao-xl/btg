"""MQTT 传输契约：主机 ↔ 板端薄代理间的消息编解码。

主机与开发板通过 MQTT 交换 JSON 载荷。本模块是双方唯一的"语法"来源，
避免两端各自维护一份易漂移的消息格式。时间戳统一 Unix epoch 秒（float，UTC）。

主题约定（前缀默认 ``btg``，按 board_id 隔离）：
- 板上行遥测:   ``btg/{board_id}/telemetry``（批量 Reading JSON）
- 板上行事件:   ``btg/{board_id}/event``（心跳/设备上下线）
- 主机下行指令: ``btg/{board_id}/command``（set / stop）
- 板执行回执:   ``btg/{board_id}/ack``（option nonce 校验）
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .types import Reading

DEFAULT_PREFIX = "btg"


def telemetry_topic(board_id: str, prefix: str = DEFAULT_PREFIX) -> str:
    return f"{prefix}/{board_id}/telemetry"


def event_topic(board_id: str, prefix: str = DEFAULT_PREFIX) -> str:
    return f"{prefix}/{board_id}/event"


def command_topic(board_id: str, prefix: str = DEFAULT_PREFIX) -> str:
    return f"{prefix}/{board_id}/command"


def ack_topic(board_id: str, prefix: str = DEFAULT_PREFIX) -> str:
    return f"{prefix}/{board_id}/ack"


def _reading_fields(reading: Reading) -> Dict[str, Any]:
    return {
        "channel": reading.channel,
        "sensor_id": reading.sensor_id,
        "value": reading.value,
        "unit": reading.unit,
        "timestamp": reading.timestamp,
        "extra": dict(reading.extra or {}),
    }


def _reading_from_fields(fields: Dict[str, Any]) -> Reading:
    return Reading(
        channel=str(fields["channel"]),
        sensor_id=str(fields["sensor_id"]),
        value=float(fields["value"]),
        unit=str(fields.get("unit", "")),
        timestamp=float(fields.get("timestamp", time.time())),
        extra=dict(fields.get("extra") or {}),
    )


def encode_telemetry(
    board_id: str,
    readings: List[Reading],
    ts: Optional[float] = None,
) -> str:
    """将一批 Reading 编码为上行遥测 JSON。"""
    msg = {
        "type": "telemetry",
        "board": board_id,
        "ts": ts if ts is not None else time.time(),
        "readings": [_reading_fields(r) for r in readings],
    }
    return json.dumps(msg)


def decode_telemetry(payload: bytes) -> Tuple[str, List[Reading]]:
    """解板上行遥测为 (board_id, Reading 列表)。"""
    msg = json.loads(payload)
    return str(msg["board"]), [_reading_from_fields(f) for f in msg["readings"]]


def encode_command(
    board_id: str,
    channel: str,
    value: Optional[float],
    *,
    action: str = "set",
    unit: str = "",
    nonce: Optional[str] = None,
) -> str:
    """将执行器目标编码为下行指令 JSON。"""
    cmd = {
        "type": "command",
        "board": board_id,
        "channel": channel,
        "action": action,
        "value": value,
        "unit": unit,
        "nonce": nonce or str(uuid.uuid4()),
        "ts": time.time(),
    }
    return json.dumps(cmd)


def decode_command(payload: bytes) -> Dict[str, Any]:
    """解主机下行指令为字典（字段缺失时给出安全默认）。"""
    msg = json.loads(payload)
    return {
        "board": str(msg["board"]),
        "channel": str(msg["channel"]),
        "action": str(msg.get("action", "set")),
        "value": msg.get("value"),
        "unit": str(msg.get("unit", "")),
        "nonce": str(msg.get("nonce", "")),
    }


def encode_ack(
    board_id: str,
    nonce: str,
    *,
    ok: bool,
    error: str = "",
) -> str:
    msg = {
        "type": "ack",
        "board": board_id,
        "nonce": nonce,
        "ok": ok,
        "error": error,
        "ts": time.time(),
    }
    return json.dumps(msg)


def encode_event(board_id: str, kind: str, **extra: Any) -> str:
    msg = {"type": "event", "board": board_id, "kind": kind, "ts": time.time(), **extra}
    return json.dumps(msg)


def decode_event(payload: bytes) -> Dict[str, Any]:
    """解板上行事件（如心跳）为字典。"""
    msg = json.loads(payload)
    return {
        "board": str(msg["board"]),
        "kind": str(msg.get("kind", "")),
        "ts": float(msg.get("ts", time.time())),
    }