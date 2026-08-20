"""板端薄代理配置模型（纯 stdlib 解析，避免强依赖 pydantic）。

配置来自 ``config.yaml``，见同目录 ``config.example.yaml``。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class BrokerConfig:
    host: str = "127.0.0.1"
    port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    prefix: str = "btg"
    client_id: str = "btg-board"

    @classmethod
    def from_dict(cls, d: Dict) -> "BrokerConfig":
        return cls(
            host=str(d.get("host", cls.host)),
            port=int(d.get("port", cls.port)),
            username=d.get("username"),
            password=d.get("password"),
            prefix=str(d.get("prefix", cls.prefix)),
            client_id=str(d.get("client_id", cls.client_id)),
        )


@dataclass
class SensorChannel:
    channel: str
    driver: str
    interval: float = 1.0

    @classmethod
    def from_dict(cls, d: Dict) -> "SensorChannel":
        return cls(
            channel=str(d["channel"]),
            driver=str(d["driver"]),
            interval=float(d.get("interval", 1.0)),
        )


@dataclass
class ActuatorChannel:
    channel: str
    driver: str

    @classmethod
    def from_dict(cls, d: Dict) -> "ActuatorChannel":
        return cls(channel=str(d["channel"]), driver=str(d["driver"]))


@dataclass
class AgentConfig:
    board_id: str
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    sensors: List[SensorChannel] = field(default_factory=list)
    actuators: List[ActuatorChannel] = field(default_factory=list)
    heartbeat_interval: float = 5.0

    @classmethod
    def from_dict(cls, d: Dict) -> "AgentConfig":
        return cls(
            board_id=str(d["board_id"]),
            broker=BrokerConfig.from_dict(d.get("broker", {})),
            sensors=[SensorChannel.from_dict(s) for s in d.get("sensors", [])],
            actuators=[ActuatorChannel.from_dict(a) for a in d.get("actuators", [])],
            heartbeat_interval=float(d.get("heartbeat_interval", 5.0)),
        )