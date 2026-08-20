"""生命周期钩子：第三方可在不改核心源码的前提下注入业务逻辑。

用法::

    from btg_sdk import hook

    @hook.on_telemetry_received
    async def clean(reading: Reading) -> None:
        ...

    @hook.on_safety_check
    async def extra_check(command: ActuatorCommand) -> None:
        ...
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict, List

HookFn = Callable[..., Awaitable[Any]]

_HOOKS: Dict[str, List[HookFn]] = defaultdict(list)


def _make_hook(name: str, doc: str) -> Callable[[HookFn], HookFn]:
    def decorator(fn: HookFn) -> HookFn:
        _HOOKS[name].append(fn)
        return fn

    decorator.__doc__ = doc
    return decorator


on_telemetry_received = _make_hook(
    "telemetry_received",
    "数据进入融合引擎前清洗。",
)
on_safety_check = _make_hook(
    "safety_check",
    "自定义更复杂的安全拦截逻辑。",
)
on_state_change = _make_hook(
    "state_change",
    "状态机状态发生变化时。",
)


def get_hooks(name: str) -> List[HookFn]:
    """返回指定钩子点注册的所有回调（副本）。"""
    return list(_HOOKS[name])


def clear_hooks() -> None:
    """清空所有钩子（主要用于测试隔离）。"""
    _HOOKS.clear()