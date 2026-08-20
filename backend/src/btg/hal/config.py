"""HAL 配置模型：将 devices.yaml 解析为结构化逻辑通道。

使用标准库 ``dataclasses``，与外部依赖解耦。YAML 文件加载见
``load_config``（需要 ``pyyaml``）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping

VALID_KINDS = ("sensor", "actuator")


@dataclass
class DeviceBinding:
    """单个物理设备绑定。

    Attributes:
        plugin: 对应 SDK ``@register_*`` 注册表中的实现名。
        priority: 优先级，数字越小越优先（1=主设备，2=备用…）。
        config: 传给插件实例的额外配置（如 ``mac``、``interval``）。
    """

    plugin: str
    priority: int = 1
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChannelConfig:
    """逻辑通道配置。

    Attributes:
        name: 逻辑通道名（如 ``"heart_rate"``）。
        kind: 通道类型 ``"sensor"`` 或 ``"actuator"``。
        devices: 按 priority 升序排列的主备设备列表。
    """

    name: str
    kind: str
    devices: List[DeviceBinding]


@dataclass
class DeviceConfig:
    """整机设备配置（多个逻辑通道）。"""

    channels: List[ChannelConfig]


def parse_channels(raw: Mapping[str, Any]) -> DeviceConfig:
    """解析 YAML/JSON 反序列化后的 ``channels`` 字典。

    Args:
        raw: 形如 ``{"heart_rate": {"type": "sensor", "devices": [...]}}``。

    Returns:
        DeviceConfig: 校验并排序后的通道配置。

    Raises:
        ValueError: 通道类型非法、缺少插件名或优先级非正数。
    """
    channels: List[ChannelConfig] = []
    for name, spec in raw.items():
        kind = spec.get("type")
        if kind not in VALID_KINDS:
            raise ValueError(f"通道 '{name}' 类型非法: {kind!r}，应属于 {VALID_KINDS}")
        devices: List[DeviceBinding] = []
        for d in spec.get("devices", []):
            plugin = d.get("plugin")
            if not plugin:
                raise ValueError(f"通道 '{name}' 存在缺少 plugin 的设备")
            priority = int(d.get("priority", 1))
            if priority < 1:
                raise ValueError(f"通道 '{name}' 设备 priority 必须为正整数")
            devices.append(
                DeviceBinding(
                    plugin=str(plugin),
                    priority=priority,
                    config=dict(d.get("config", {})),
                )
            )
        devices.sort(key=lambda x: x.priority)
        channels.append(ChannelConfig(name=name, kind=kind, devices=devices))
    return DeviceConfig(channels=channels)


def load_config(path: str) -> DeviceConfig:
    """从文件加载设备配置（YAML，需 ``pyyaml``）。

    Args:
        path: 配置文件路径。

    Raises:
        ImportError: 未安装 ``pyyaml``。
    """
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("加载 YAML 配置需要安装 pyyaml") from exc
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return parse_channels(data.get("channels", {}))