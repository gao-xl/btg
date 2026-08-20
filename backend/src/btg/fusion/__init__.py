"""BTG 多模态融合引擎：聚合器、规则集与状态机。"""
from .adaptive_monitor import (
    AdaptiveBaselineTracker,
    AdaptiveBiometricLearningEngine,
    BaselinePhase,
    InterventionLevel,
    MetricConfig,
)
from .aggregator import ChannelSnapshot, TelemetryAggregator
from .engine import FusionEngine
from .rules import Rule, RuleResult, RuleSet
from .state import (
    STATE_ACTIVE,
    STATE_ALARM,
    STATE_ELEVATED,
    STATE_FAULT,
    STATE_INIT,
    STATE_RESTING,
    StateMachine,
    StateTransition,
)

__all__ = [
    "AdaptiveBaselineTracker",
    "AdaptiveBiometricLearningEngine",
    "BaselinePhase",
    "ChannelSnapshot",
    "FusionEngine",
    "InterventionLevel",
    "MetricConfig",
    "Rule",
    "RuleResult",
    "RuleSet",
    "STATE_ACTIVE",
    "STATE_ALARM",
    "STATE_ELEVATED",
    "STATE_FAULT",
    "STATE_INIT",
    "STATE_RESTING",
    "StateMachine",
    "StateTransition",
    "TelemetryAggregator",
]
