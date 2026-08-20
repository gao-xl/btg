"""硬性数值截断：对下发到执行器的指令做最后一道边界防御。

设计原则（详见 ``docs/architecture.md``）：无论上层融合引擎、规则引擎或
第三方平台下达何种数值，本层都会在执行器真正收到指令前，将其钳制到
``safety.yaml`` 声明的物理安全区间内（如限制 TENS 电流不超过 50 mA）。

截断是「钳制」(clamp) 而非「拒绝」(reject)：值被压到边界后继续下发，
由审计日志记录原始值与被截断的事实，便于事后回溯与报警。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

from btg.core.logging import get_audit_logger

audit = get_audit_logger()


@dataclass(frozen=True, slots=True)
class Clamp:
    """单个执行器通道的硬性数值边界。

    Attributes:
        channel: 逻辑执行通道名（如 ``"tens_intensity"``）。
        min_value: 允许的最小值（含）；缺省为负无穷（不限制下限）。
        max_value: 允许的最大值（含）；缺省为正无穷（不限制上限）。
        unit: 物理单位（``"mA"``、``"Hz"``、``"%"`` 等），用于日志可读性。
    """

    channel: str
    min_value: float = -math.inf
    max_value: float = math.inf
    unit: str = ""

    def __post_init__(self) -> None:
        if self.min_value > self.max_value:
            raise ValueError(
                f"通道 '{self.channel}' 的 min_value 不能大于 max_value"
            )

    def apply(self, value: float) -> float:
        """将 ``value`` 钳制到 ``[min_value, max_value]``。"""
        return min(max(value, self.min_value), self.max_value)

    def is_violation(self, value: float) -> bool:
        """返回 ``value`` 是否越界。"""
        return value < self.min_value or value > self.max_value


class ClampSet:
    """以逻辑通道为 key 的截断规则集合。"""

    def __init__(self, clamps: Iterable[Clamp]) -> None:
        self._by_channel: Dict[str, Clamp] = {}
        for c in clamps:
            if c.channel in self._by_channel:
                raise ValueError(f"通道 '{c.channel}' 存在重复的 clamp 规则")
            self._by_channel[c.channel] = c

    def get(self, channel: str) -> Optional[Clamp]:
        """返回某通道的截断规则，未配置返回 None。"""
        return self._by_channel.get(channel)

    def clamp(self, channel: str, value: float) -> Tuple[float, bool]:
        """钳制数值，返回 ``(钳制后值, 是否发生截断)``。

        未配置规则的通道原样返回，``clamped`` 恒为 False。
        """
        rule = self._by_channel.get(channel)
        if rule is None:
            return value, False
        if not rule.is_violation(value):
            return value, False
        clamped = rule.apply(value)
        audit.warning(
            "数值截断 channel=%s original=%s clamped=%s unit=%s",
            channel,
            value,
            clamped,
            rule.unit,
        )
        return clamped, True

    def __len__(self) -> int:
        return len(self._by_channel)