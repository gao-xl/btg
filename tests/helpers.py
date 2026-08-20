"""测试共用工具：构建带内存配置的 Gateway、配置与 app。

被各冒烟测试文件复用，避免重复装配逻辑。独立运行时通过 ``sys.path``
注入 ``sdk`` 与 ``backend/src`` 根。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "sdk", _ROOT / "backend" / "src", _ROOT / "tests"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from btg.config import ConfigManager  # noqa: E402
from btg.gateway import Gateway  # noqa: E402
from btg.hal import parse_channels  # noqa: E402
from btg.safety import SafetyConfig  # noqa: E402
from btg.settings import AppSettings  # noqa: E402


def make_device_config(base_value: float = 120.0, interval: float = 0.02) -> Any:
    """返回含 heart_rate 传感器与 tens_intensity 执行器的内存配置。"""
    return parse_channels({
        "heart_rate": {
            "type": "sensor",
            "devices": [
                {
                    "plugin": "mock_sensor",
                    "priority": 1,
                    "config": {
                        "channel": "heart_rate",
                        "unit": "bpm",
                        "base_value": base_value,
                        "interval": interval,
                    },
                },
            ],
        },
        "tens_intensity": {
            "type": "actuator",
            "devices": [
                {"plugin": "mock_actuator", "priority": 1},
            ],
        },
    })


def make_safety_config(max_value: float = 50.0, timeout: float = 30.0) -> SafetyConfig:
    """返回 tens_intensity 截断上限为 ``max_value`` 的安全配置。"""
    return SafetyConfig.from_dict({
        "watchdog": {"timeout": timeout},
        "clamps": {"tens_intensity": {"min": 0, "max": max_value, "unit": "mA"}},
    })


def build_gateway(
    tmp_path: Path,
    *,
    rules: Optional[List[Any]] = None,
    providers: Optional[List[Dict[str, Any]]] = None,
    base_value: float = 120.0,
    max_intensity: float = 50.0,
    config_changes: Optional[Dict[str, Any]] = None,
) -> Gateway:
    """构建一个使用临时配置文件的网关（不启动）。"""
    settings = AppSettings(
        device_config_path=tmp_path / "devices.yaml",
        safety_config_path=tmp_path / "safety.yaml",
        settings_path=tmp_path / "settings.yaml",
    )
    if providers is not None:
        settings = settings.model_copy(update={"providers": providers})

    cm = ConfigManager(tmp_path / "settings.yaml")
    if config_changes:
        cm.update_settings(config_changes)

    return Gateway(
        settings=settings,
        config_manager=cm,
        device_config=make_device_config(base_value=base_value),
        safety_config=make_safety_config(max_value=max_intensity),
        rules=rules,
    )