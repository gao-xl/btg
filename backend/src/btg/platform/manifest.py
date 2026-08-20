"""模块清单（Manifest）：平台插件的自描述元数据与契约。

每个插件模块在定义时必须提供一份 :class:`ModuleManifest`，供平台内核
用于发现、依赖解析、能力登记与健康监控。
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ModuleKind(str, Enum):
    """插件模块类别。"""

    SENSOR = "sensor"
    ACTUATOR = "actuator"
    PROVIDER = "provider"
    AGENT = "agent"
    EXTENSION = "extension"


class ModuleManifest(BaseModel):
    """插件模块的自描述契约。

    Attributes:
        name: 模块唯一名（同类 kind 内唯一），如 ``"mock_sensor"``。
        version: 语义化版本字符串。
        kind: 模块类别。
        description: 一句话说明。
        capabilities: 模块对外提供的能力标识（开放字符串列表）。
        dependencies: 依赖的其他模块 ``name`` 列表。
        config_schema: JSON Schema 字典，描述本模块可接收的配置。
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str = "0.1.0"
    kind: ModuleKind
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    config_schema: dict = Field(default_factory=dict)