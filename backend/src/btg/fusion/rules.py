"""规则引擎：根据聚合快照评估并产出「模式/状态 + 下行指令」。

规则以声明式数据描述，引擎按优先级顺序评估，第一条命中的规则胜出：

- 规则命中 → 给出目标状态（交由状态机迁移）与一组下行指令目标值
  （``ActuatorCommand`` 风格，channel/value，经由安全层截断后下发执行器）。
- 规则可声明 ``cooldown``（冷却期，秒）：命中一次后，冷却期内不再重复
  触发同一规则，避免高频抖动。

第三方可通过 ``register_rule`` / ``RuleSet`` 注入自定义规则，或用
``@hook.on_telemetry_received`` 在进入融合引擎前清洗/改造数据。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional

from btg_sdk import ActuatorCommand

from .aggregator import ChannelSnapshot

# 规则条件：接收所有通道快照，返回是否命中
Condition = Callable[[Dict[str, ChannelSnapshot]], bool]


@dataclass
class Rule:
    """单条融合规则。

    Attributes:
        name: 规则唯一名（用于审计与冷却追踪）。
        target_state: 命中后进入的状态名。
        condition: 命中条件，接收通道快照映射。
        confidence: 命中置信度（0.0~1.0）。
        commands: 命中时附带的下行指令目标（channel/value/unit）。
        priority: 优先级，数字越小越先评估（默认 100）。
        cooldown: 冷却期（秒），0 表示不冷却。
    """

    name: str
    target_state: str
    condition: Condition
    confidence: float = 1.0
    commands: List[ActuatorCommand] = field(default_factory=list)
    priority: int = 100
    cooldown: float = 0.0


@dataclass(frozen=True, slots=True)
class RuleResult:
    """规则集评估结果。

    Attributes:
        matched: 命中的规则（无命中则为 None）。
        commands: 需下发的指令目标（无命中为空列表）。
    """

    matched: Optional[Rule] = None
    commands: List[ActuatorCommand] = field(default_factory=list)


class RuleSet:
    """按优先级排序的规则集合，评估后产出命中的规则与指令。"""

    def __init__(self, rules: Iterable[Rule]) -> None:
        self._rules = sorted(rules, key=lambda r: (r.priority, r.name))
        self._last_hit: Dict[str, float] = {}

    @property
    def rules(self) -> List[Rule]:
        return list(self._rules)

    def evaluate(self, snapshots: Dict[str, ChannelSnapshot]) -> RuleResult:
        """评估规则集，返回第一条命中的非冷却规则结果。"""
        now = time.time()
        for rule in self._rules:
            if self._in_cooldown(rule, now):
                continue
            if rule.condition(snapshots):
                self._last_hit[rule.name] = now
                return RuleResult(matched=rule, commands=list(rule.commands))
        return RuleResult(matched=None, commands=[])

    def _in_cooldown(self, rule: Rule, now: float) -> bool:
        if rule.cooldown <= 0:
            return False
        last = self._last_hit.get(rule.name)
        return last is not None and (now - last) < rule.cooldown

    def reset(self) -> None:
        """清空冷却状态（测试隔离或手动重启）。"""
        self._last_hit.clear()