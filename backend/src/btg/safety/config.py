"""安全层配置模型：解析 safety.yaml（clamps 边界 + watchdog 超时）。"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping

from .clamps import Clamp, ClampSet

DEFAULT_WATCHDOG_TIMEOUT = 2.0


@dataclass
class GuardrailConfig:
    """动态风控分级安全闸配置（safety.yaml 的 ``guardrails`` 段）。

    Attributes:
        attenuation_factor: 软降级时对下行强度的衰减系数（默认 ×0.5）。
        heart_rate_channel: 心率逻辑通道名。
        heart_rate_warn_bpm: 心率预警线，达到即触发软降级。
        heart_rate_critical_bpm: 心率危险线，连续超限达到
            ``heart_rate_critical_consecutive`` 次触发硬急停。
        heart_rate_critical_consecutive: 触发硬急停所需的连续超限次数。
        heart_rate_reset_bpm: 软降级自动复原的心率回退线。
        imu_channel: IMU 幅度/方差逻辑通道名。
        imu_fall_threshold: IMU 摔倒挣扎判定阈值（超限即硬急停）。
        ws_heartbeat_timeout: 前端 WebSocket 心跳超时（秒），超时即硬急停。
        poll_interval: 后台监控轮询间隔（秒）。
    """

    attenuation_factor: float = 0.5
    heart_rate_channel: str = "heart_rate"
    heart_rate_warn_bpm: float = 130.0
    heart_rate_critical_bpm: float = 160.0
    heart_rate_critical_consecutive: int = 3
    heart_rate_reset_bpm: float = 110.0
    imu_channel: str = "imu_variance"
    imu_fall_threshold: float = 3.0
    ws_heartbeat_timeout: float = 2.0
    poll_interval: float = 0.25

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "GuardrailConfig":
        """从 ``guardrails`` 段解析配置，未提供的键回落到默认值。"""
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})


@dataclass
class SafetyConfig:
    """安全层运行时配置。

    Attributes:
        clamps: 执行器通道的数值截断规则集合。
        watchdog_timeout: 控制链路心跳超时（秒），超时自动归零。
        guardrails: 动态风控分级安全闸配置。
    """

    clamps: ClampSet
    watchdog_timeout: float = DEFAULT_WATCHDOG_TIMEOUT
    guardrails: GuardrailConfig = field(default_factory=GuardrailConfig)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SafetyConfig":
        wd = raw.get("watchdog") or {}
        timeout = float(wd.get("timeout", DEFAULT_WATCHDOG_TIMEOUT))
        if timeout <= 0:
            raise ValueError("watchdog.timeout 必须为正数（单位：秒）")

        clamps: list[Clamp] = []
        for channel, spec in (raw.get("clamps") or {}).items():
            clamps.append(
                Clamp(
                    channel=str(channel),
                    min_value=float(spec.get("min", -math.inf)),
                    max_value=float(spec.get("max", math.inf)),
                    unit=str(spec.get("unit", "")),
                )
            )
        return cls(
            clamps=ClampSet(clamps),
            watchdog_timeout=timeout,
            guardrails=GuardrailConfig.from_dict(raw.get("guardrails") or {}),
        )


def load_safety_config(path: str) -> SafetyConfig:
    """从文件加载安全配置（YAML，需 ``pyyaml``）。

    Raises:
        ImportError: 未安装 ``pyyaml``。
    """
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("加载 YAML 配置需要安装 pyyaml") from exc
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return SafetyConfig.from_dict(data)