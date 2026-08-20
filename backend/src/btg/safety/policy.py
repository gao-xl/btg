"""安全策略层：串接钩子 → 数值截断 → 看门狗喂狗。

这是所有下行指令进入执行器前的必经管道。调用方（总线/融合引擎）将
``ActuatorCommand`` 交给 ``SafetyPolicy.check_command()``：

1. 执行 ``@hook.on_safety_check`` 钩子（第三方可自定义拦截逻辑）；
2. 对数值做硬性截断（clamp），返回安全后的指令；
3. 应用分级安全闸（软降级限幅 / 硬急停归零）；
4. 刷新看门狗心跳，证明控制链路存活。

钩子抛出的 ``SafetyViolationError``（或其他异常）向调用方传播，表示
指令被拒绝，不会下发到执行器。

另外提供一个无参 ``pump_watchdog()`` 便捷方法：即使无指令下发（如规则
引擎空转、前端仅轮询），上位机也应周期性调用维持心跳。
"""
from __future__ import annotations

import math
from typing import Optional

from btg_sdk import ActuatorCommand, hook

from .clamps import ClampSet
from .guardrail import Guardrail
from .watchdog import Watchdog


class SafetyPolicy:
    """整合第三方钩子、数值截断、分级安全闸与看门狗的安全决策入口。

    ``global_max`` 是对所有执行器通道生效的全局强度上限（对应配置中心
    的 ``max_system_intensity``），可在运行时被热更新为更严格的值。

    ``guardrail`` 为动态风控分级安全闸（可选注入）：软降级时按衰减系数
    限幅，硬急停触发后对所有下行指令直接归零。
    """

    def __init__(
        self,
        clamps: ClampSet,
        watchdog: Watchdog,
        *,
        global_max: float = math.inf,
        guardrail: Optional[Guardrail] = None,
    ) -> None:
        self.clamps = clamps
        self.watchdog = watchdog
        self.global_max = global_max
        self.guardrail = guardrail

    async def check_command(self, command: ActuatorCommand) -> ActuatorCommand:
        """校验并归一化一条下行指令。

        依次运行所有 ``on_safety_check`` 钩子，再截断数值，应用分级安全闸，
        最后喂狗。返回（可能已被截断的）安全指令；钩子抛异常则拒绝该指令并上抛。

        Raises:
            SafetyViolationError: 第三方钩子判定指令不安全。
        """
        for fn in hook.get_hooks("safety_check"):
            await fn(command)

        value, clamped = self.clamps.clamp(command.channel, command.value)
        if value > self.global_max:
            value = self.global_max
            clamped = True

        if self.guardrail is not None:
            attenuated = self.guardrail.apply(value)
            if attenuated != value:
                value = attenuated
                clamped = True

        self.watchdog.feed()
        if clamped:
            return ActuatorCommand(
                channel=command.channel,
                actuator_id=command.actuator_id,
                value=value,
                unit=command.unit,
                timestamp=command.timestamp,
            )
        return command

    def pump_watchdog(self) -> None:
        """无指令下发时仍维持心跳（供上位机周期性调用）。"""
        self.watchdog.feed()

    async def start(self) -> None:
        """启动看门狗与分级安全闸后台监控。"""
        await self.watchdog.start()
        if self.guardrail is not None:
            await self.guardrail.start()

    async def stop(self) -> None:
        """停止看门狗与分级安全闸后台监控。"""
        if self.guardrail is not None:
            await self.guardrail.stop()
        await self.watchdog.stop()