"""融合引擎：串接聚合 → 规则 → 状态机 → 下行指令的编排核心。

数据流：从 HAL 的遥测队列取出 ``Reading`` →（``on_telemetry_received``
钩子清洗）→ 聚合器写入 → 规则集评估 → 状态机迁移 → 命中规则的指令目标
经 ``actuator_command`` 事件广播，交由下游安全层截断后下发执行器。

引擎本身不关心具体传感器/执行器实现，只依赖共享数据类型与钩子，
保持与 HAL/Safety 两层的解耦。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from btg.core.events import EventBus
from btg_sdk import ActuatorCommand, Reading, hook

from .aggregator import TelemetryAggregator
from .rules import Rule, RuleSet
from .state import StateMachine, STATE_FAULT

logger = logging.getLogger(__name__)


class FusionEngine:
    """多模态融合引擎（面向单事件循环）。"""

    def __init__(
        self,
        bus: EventBus,
        rules: List[Rule],
        *,
        window_seconds: float = 10.0,
        initial_state: str = "init",
    ) -> None:
        self.bus = bus
        self.aggregator = TelemetryAggregator(window_seconds=window_seconds)
        self.rules = RuleSet(rules)
        self.state_machine = StateMachine(bus, initial=initial_state)
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    async def start(self, in_queue: asyncio.Queue) -> None:
        """启动消费协程，持续从 ``in_queue`` 读取并处理读数。"""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(in_queue))

    async def stop(self) -> None:
        """停止消费协程（幂等）。"""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self, in_queue: asyncio.Queue) -> None:
        while True:
            reading = await in_queue.get()
            try:
                await self.ingest(reading)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "融合引擎处理读数异常 channel=%s", getattr(reading, "channel", "?")
                )

    # ------------------------------------------------------------------ #
    # 核心处理
    # ------------------------------------------------------------------ #
    async def ingest(self, reading: Reading) -> List[ActuatorCommand]:
        """处理单条读数，返回需下发的指令目标（可能为空）。

        清洗钩子可改造或丢弃读数：钩子返回 ``None`` 表示丢弃；返回
        ``Reading`` 则以返回值继续处理。
        """
        cleaned = reading
        for fn in hook.get_hooks("telemetry_received"):
            result = await fn(cleaned)
            if result is None:
                return []
            cleaned = result

        self.aggregator.push(cleaned)
        return await self.evaluate()

    async def evaluate(self) -> List[ActuatorCommand]:
        """基于当前聚合体能进行评估并迁移状态，返回下行指令。"""
        snapshots = self.aggregator.snapshots()
        result = self.rules.evaluate(snapshots)

        if result.matched is None:
            return []

        rule = result.matched
        await self.state_machine.transition(
            rule.target_state,
            reason=rule.name,
            confidence=rule.confidence,
            context={"commands": [c.value for c in result.commands]},
        )

        if result.commands:
            await self.bus.publish(
                "actuator_command",
                commands=result.commands,
                source_rule=rule.name,
            )
        return result.commands

    async def mark_fault(self, reason: str = "") -> None:
        """显式进入故障态（供看门狗超时或安全层触发降级）。"""
        await self.state_machine.transition(STATE_FAULT, reason=reason)