"""指令分发器：下行指令进入安全层校验后路由到执行器冗余组。

融合引擎发布的 ``actuator_command`` 事件、REST 手动指令、第三方
integration 控制，最终都汇聚到本模块的 ``dispatch()``，共用同一条
安全管道（第三方钩子 → 数值截断 → 看门狗喂狗 → 执行器下发）。
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from btg.core.events import EventBus
from btg.core.exceptions import (
    DeviceConnectionError,
    InvalidCommandError,
    SafetyViolationError,
)
from btg.core.logging import get_audit_logger
from btg_sdk import ActuatorCommand

logger = logging.getLogger(__name__)
audit = get_audit_logger()


class CommandDispatcher:
    """将（经安全层校验过的）指令下发到逻辑通道对应的执行器冗余组。"""

    def __init__(self, safety_policy: Any, channel_manager: Any) -> None:
        # 依赖通过鸭子类型注入，避免与 safety/hal 形成包级耦合。
        self.safety_policy = safety_policy
        self.channel_manager = channel_manager

    async def dispatch(self, command: ActuatorCommand) -> ActuatorCommand:
        """校验并下发单条指令，返回安全后的指令。

        Raises:
            SafetyViolationError: 第三方钩子判定指令不安全。
            InvalidCommandError: 指令指向未配置的执行通道。
            DeviceConnectionError: 执行器下发失败（含备用切换全部失败）。
        """
        safe = await self.safety_policy.check_command(command)
        group = self.channel_manager.actuator_groups.get(safe.channel)
        if group is None:
            raise InvalidCommandError(f"未配置的执行通道: {safe.channel}")
        ok = await group.set_target(safe.value)
        if not ok:
            raise DeviceConnectionError(f"执行通道 {safe.channel} 下发失败")
        return safe

    async def on_commands(
        self,
        commands: List[ActuatorCommand],
        source_rule: str = "",
        **kwargs: Any,
    ) -> None:
        """事件处理器：批量下发融合引擎产出的指令，隔离单条失败。"""
        for command in commands:
            try:
                await self.dispatch(command)
            except SafetyViolationError as exc:
                audit.warning("指令被安全策略拒绝 rule=%s channel=%s: %s",
                              source_rule, command.channel, exc)
            except (InvalidCommandError, DeviceConnectionError) as exc:
                logger.error("指令下发失败 rule=%s channel=%s: %s",
                             source_rule, command.channel, exc)

    def subscribe(self, bus: EventBus) -> None:
        """订阅 ``actuator_command`` 事件。"""
        bus.subscribe("actuator_command", self.on_commands)