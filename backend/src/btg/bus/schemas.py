"""Shared REST request/response schema for the bus and integration layers."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CommandRequest(BaseModel):
    """A single downstream actuator command submitted over REST/integration.

    ``channel`` 是逻辑执行通道名；``value`` 会经安全层截断后再下发；
    ``unit`` 与 ``actuator_id`` 为可选描述项，仅用于溯源与审计。
    """

    model_config = ConfigDict(extra="forbid")

    channel: str = Field(min_length=1, description="逻辑执行通道名")
    value: float = Field(description="目标输出值，语义由 unit 决定")
    unit: str = Field(default="", description="物理单位（mA/Hz/% 等）")
    actuator_id: str = Field(default="", description="可选执行器实例 ID")