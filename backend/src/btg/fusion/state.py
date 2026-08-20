"""人体状态机：管理状态演化，向钩子与事件总线广播状态迁移。

状态字符串采用开放集合（源码中不硬编码枚举），以支持第三方插件自定义
状态；但内置一批约定常供融合引擎与规则引用（见模块级常量）。

每次状态迁移通过 ``on_state_change`` 钩子与 ``state_change`` 事件广播，
便于第三方注入自定义逻辑，或由整个下行流水线（安全层/执行器）响应。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from btg.core.events import EventBus
from btg_sdk import hook

# 内置约定状态（开放扩展，无需枚举约束）
STATE_INIT = "init"
STATE_RESTING = "resting"
STATE_ACTIVE = "active"
STATE_ELEVATED = "elevated"
STATE_ALARM = "alarm"
STATE_FAULT = "fault"


@dataclass(frozen=True, slots=True)
class StateTransition:
    """一次状态迁移记录。

    Attributes:
        previous: 迁移前状态名。
        current: 迁移后状态名。
        reason: 触发迁移的原因（通常为匹配的规则名）。
        confidence: 置信度（0.0~1.0），由规则引擎给出。
        timestamp: 迁移发生时间戳（Unix epoch 秒）。
    """

    previous: str
    current: str
    reason: str
    confidence: float
    timestamp: float


class StateMachine:
    """持有当前状态并在迁移时广播事件与钩子。

    迁移到相同状态（状态名不变）时不重复广播，避免无效抖动。
    """

    def __init__(
        self,
        bus: EventBus,
        initial: str = STATE_INIT,
        history_size: int = 256,
    ) -> None:
        self.bus = bus
        self._current = initial
        self._history: list[StateTransition] = []
        self._history_size = max(1, history_size)

    @property
    def current(self) -> str:
        """当前状态名。"""
        return self._current

    @property
    def history(self) -> list[StateTransition]:
        """最近的状态迁移记录（副本，按时间升序）。"""
        return list(self._history)

    async def transition(
        self,
        new_state: str,
        *,
        reason: str = "",
        confidence: float = 1.0,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """尝试迁移状态。

        Returns:
            bool: 是否发生了实际迁移（状态名确实变化）。
        """
        if new_state == self._current:
            return False

        previous = self._current
        self._current = new_state
        transition = StateTransition(
            previous=previous,
            current=new_state,
            reason=reason,
            confidence=confidence,
            timestamp=time.time(),
        )
        self._history.append(transition)
        if len(self._history) > self._history_size:
            del self._history[: len(self._history) - self._history_size]

        # 广播：先钩子，后事件总线
        for fn in hook.get_hooks("state_change"):
            await fn(state=new_state, previous=previous, reason=reason,
                      confidence=confidence, context=context)
        await self.bus.publish(
            "state_change",
            state=new_state,
            previous=previous,
            reason=reason,
            confidence=confidence,
            context=context or {},
        )
        return True