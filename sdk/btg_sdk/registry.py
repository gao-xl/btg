"""插件注册表与注册装饰器。

第三方插件通过 ``@register_sensor("my_band")`` 等装饰器登记实现类，
网关运行时加载器据此发现并实例化插件。同一名称重复注册会抛出
``ValueError``，以保证注册表一致性。
"""
from __future__ import annotations

from typing import Callable, Dict, Type

from .base import BaseActuator, BaseSensor, ThirdPartyProvider

_SENSOR_REGISTRY: Dict[str, Type[BaseSensor]] = {}
_ACTUATOR_REGISTRY: Dict[str, Type[BaseActuator]] = {}
_PROVIDER_REGISTRY: Dict[str, Type[ThirdPartyProvider]] = {}


def _register(
    registry: Dict[str, Type],
    kind: str,
    name: str,
    cls: Type,
) -> Type:
    if not name or not name.strip():
        raise ValueError(f"{kind} 插件名称不能为空")
    if name in registry:
        raise ValueError(f"{kind} 插件 '{name}' 已注册，检测到重复实现")
    registry[name] = cls
    return cls


def register_sensor(name: str) -> Callable[[Type[BaseSensor]], Type[BaseSensor]]:
    """将类登记为传感器插件。"""

    def decorator(cls: Type[BaseSensor]) -> Type[BaseSensor]:
        return _register(_SENSOR_REGISTRY, "sensor", name, cls)

    return decorator


def register_actuator(
    name: str,
) -> Callable[[Type[BaseActuator]], Type[BaseActuator]]:
    """将类登记为执行器插件。"""

    def decorator(cls: Type[BaseActuator]) -> Type[BaseActuator]:
        return _register(_ACTUATOR_REGISTRY, "actuator", name, cls)

    return decorator


def register_provider(
    name: str,
) -> Callable[[Type[ThirdPartyProvider]], Type[ThirdPartyProvider]]:
    """将类登记为第三方平台插件。"""

    def decorator(cls: Type[ThirdPartyProvider]) -> Type[ThirdPartyProvider]:
        return _register(_PROVIDER_REGISTRY, "provider", name, cls)

    return decorator


def get_sensor_class(name: str) -> Type[BaseSensor]:
    """按名称返回传感器实现类。

    Raises:
        KeyError: 未注册对应名称的传感器插件。
    """
    try:
        return _SENSOR_REGISTRY[name]
    except KeyError:
        raise KeyError(f"未注册的 sensor 插件: {name}") from None


def get_actuator_class(name: str) -> Type[BaseActuator]:
    """按名称返回执行器实现类。

    Raises:
        KeyError: 未注册对应名称的执行器插件。
    """
    try:
        return _ACTUATOR_REGISTRY[name]
    except KeyError:
        raise KeyError(f"未注册的 actuator 插件: {name}") from None


def get_provider_class(name: str) -> Type[ThirdPartyProvider]:
    """按名称返回第三方平台实现类。

    Raises:
        KeyError: 未注册对应名称的第三方平台插件。
    """
    try:
        return _PROVIDER_REGISTRY[name]
    except KeyError:
        raise KeyError(f"未注册的 provider 插件: {name}") from None


def clear_registry() -> None:
    """清空所有注册表（主要用于测试隔离）。"""
    _SENSOR_REGISTRY.clear()
    _ACTUATOR_REGISTRY.clear()
    _PROVIDER_REGISTRY.clear()