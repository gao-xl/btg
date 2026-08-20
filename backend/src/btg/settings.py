"""应用配置（host/port/日志/配置文件路径/插件发现）。

配置来自代码默认值，可用 ``BTG_*`` 环境变量覆盖（见 :meth:`AppSettings.from_env`）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

from pydantic import BaseModel, ConfigDict, Field

# backend/src/btg/settings.py -> btg -> src -> backend -> 仓库根
_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
_PLUGINS_DIR = Path(__file__).resolve().parents[2] / "plugins"


class AppSettings(BaseModel):
    """网关进程级配置（非运行时热更新项，热更新见配置中心 ``settings.yaml``）。"""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = Field(default="INFO")
    json_logs: bool = Field(default=False)

    device_config_path: Path = Field(default=_CONFIG_DIR / "devices.yaml")
    safety_config_path: Path = Field(default=_CONFIG_DIR / "safety.yaml")
    settings_path: Path = Field(default=_CONFIG_DIR / "settings.yaml")
    video_cameras_path: Path = Field(default=_CONFIG_DIR / "cameras.yaml")

    plugins_dir: Path = Field(default=_PLUGINS_DIR)
    plugin_entry_point_group: str = Field(default="btg.plugins")
    providers: List[dict] = Field(default_factory=list)

    fusion_window_seconds: float = Field(default=10.0, gt=0.0)
    telemetry_capacity: int = Field(default=4096, gt=0)
    feedback_poll_interval_seconds: float = Field(default=10.0, gt=0.0)
    feedback_stale_after_seconds: float = Field(default=30.0, gt=0.0)

    @classmethod
    def from_env(cls) -> "AppSettings":
        """从 ``BTG_*`` 环境变量覆盖默认配置。"""
        overrides: dict = {}
        if "BTG_HOST" in os.environ:
            overrides["host"] = os.environ["BTG_HOST"]
        if "BTG_PORT" in os.environ:
            overrides["port"] = int(os.environ["BTG_PORT"])
        if "BTG_LOG_LEVEL" in os.environ:
            overrides["log_level"] = os.environ["BTG_LOG_LEVEL"]
        if "BTG_JSON_LOGS" in os.environ:
            overrides["json_logs"] = os.environ["BTG_JSON_LOGS"].strip().lower() in (
                "1", "true", "yes", "on",
            )
        for env, field in (
            ("BTG_DEVICES_CONFIG", "device_config_path"),
            ("BTG_SAFETY_CONFIG", "safety_config_path"),
            ("BTG_SETTINGS_CONFIG", "settings_path"),
            ("BTG_CAMERAS_CONFIG", "video_cameras_path"),
        ):
            if env in os.environ:
                overrides[field] = Path(os.environ[env])
        return cls(**overrides)