"""设备反馈聚合模块：统一收集执行器回传的反馈信息（电量、信号、连接/
执行确认、异常等），提供快照、历史与健康度查询，作为规则引擎的下游配套。
"""
from .aggregator import FeedbackAggregator
from .collector import FeedbackCollector
from .models import DeviceHealth, compute_health

__all__ = [
    "DeviceHealth",
    "FeedbackAggregator",
    "FeedbackCollector",
    "compute_health",
]