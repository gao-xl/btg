"""开发/联调用 mock 执行器插件（无真实硬件）。"""
from __future__ import annotations

from typing import Any, Dict, Mapping

from btg_sdk import BaseActuator, register_actuator


@register_actuator("mock_actuator")
class MockActuator(BaseActuator):
    """记录目标值的虚拟执行器。

    配置项：
    - ``fail_on_set``: True 时 ``set_target`` 返回 False（模拟下发失败）。
    """

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.instance_id = str(config.get("instance_id", "mock_actuator"))
        self.fail_on_set = bool(config.get("fail_on_set", False))
        self.targets: Dict[str, float] = {}
        self.stopped = False

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        pass

    async def set_target(self, channel: str, value: float) -> bool:
        if self.fail_on_set:
            return False
        self.targets[channel] = value
        return True

    async def stop(self) -> None:
        self.stopped = True