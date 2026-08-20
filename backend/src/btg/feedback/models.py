"""设备反馈的健康度模型。

根据设备最近一条反馈的类别与时效，计算一个可读的健康状态，供规则引擎、
前端面板或第三方平台消费。
"""
from __future__ import annotations

from typing import Optional

from btg_sdk import DeviceFeedback, FeedbackKind


class DeviceHealth:
    """健康度状态常量（开放集合，字符串标识）。"""

    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    STALE = "stale"
    UNKNOWN = "unknown"


def compute_health(
    feedback: Optional[DeviceFeedback],
    *,
    now: float,
    stale_after_seconds: float,
) -> str:
    """根据最近一条反馈计算健康度。

    Args:
        feedback: 设备最近一条反馈，None 表示从未收到反馈。
        now: 当前时间戳（Unix epoch 秒）。
        stale_after_seconds: 超过该时长无新反馈则判定为 ``STALE``。
    """
    if feedback is None:
        return DeviceHealth.UNKNOWN
    if (now - feedback.timestamp) > stale_after_seconds:
        return DeviceHealth.STALE

    kind = feedback.kind
    if kind == FeedbackKind.ERROR:
        return DeviceHealth.DEGRADED
    if kind == FeedbackKind.CONNECTION:
        online = feedback.value is None or feedback.value >= 0.5
        return DeviceHealth.ONLINE if online else DeviceHealth.OFFLINE
    if kind in (FeedbackKind.ACK, FeedbackKind.BATTERY, FeedbackKind.SIGNAL):
        return DeviceHealth.ONLINE
    return DeviceHealth.UNKNOWN