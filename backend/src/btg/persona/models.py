"""剧本人格市场：剧本元数据契约（scenario_manifest.json）。

一个完整剧本包不仅是一段 System Prompt，而是「人格 + 硬件映射策略」的一整套：

- :class:`HardwareStrategy`：心率放大系数、AI 全权标志、最高安全强度上限；
- :class:`ScenarioManifest`：剧本自描述元数据 + 系统提示词 + 硬件策略。

模型严格校验（``extra="forbid"``），供 REST 导入与社区工坊拉取的统一校验。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HardwareStrategy(BaseModel):
    """剧本的硬件映射策略（安全边界的一部分）。"""

    model_config = ConfigDict(extra="forbid")

    heart_rate_multiplier: float = Field(default=1.0, gt=0.0, le=10.0, description="心率对强度的放大系数")
    allow_ai_full_control: bool = Field(default=False, description="是否允许 AI 自主控权")
    max_allowed_intensity: float = Field(default=100.0, ge=0.0, le=100.0, description="该剧本允许的最大安全强度上限")


class ScenarioManifest(BaseModel):
    """一个剧本包的只读契约。"""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    author: str = Field(default="BTG-Community", max_length=120)
    version: str = Field(default="1.0.0", max_length=32)
    description: str = Field(default="", max_length=2000)
    system_prompt: str = Field(min_length=1, max_length=20000)
    hardware_strategy: HardwareStrategy = Field(default_factory=HardwareStrategy)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_prompt(self) -> "ScenarioManifest":
        # 安全红线：即便剧本声明 AI 全权，仍受 safety 层 + 最高强度双重约束。
        return self

    def metadata_digest(self) -> dict[str, Any]:
        """供列表/健康检查使用的轻量元数据（不含完整提示词）。"""
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "author": self.author,
            "version": self.version,
            "description": self.description,
            "tags": list(self.tags),
            "hardware_strategy": self.hardware_strategy.model_dump(),
        }


__all__ = ["HardwareStrategy", "ScenarioManifest"]