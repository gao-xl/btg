"""BTG SDK 共享数据类型定义。

本模块定义硬件插件与网关核心之间交换的数据契约。所有数值字段必须在
docstring 中标注物理单位（如 ``bpm``、``mA``、``Hz``、``%``）与时间单位。

约定
----
- 时间戳统一使用 Unix epoch（秒，float，UTC）。
- ``unit`` 字段用于让上层安全层（数值截断）与融合层正确理解量纲。
- 数据结构使用 ``frozen=True`` 以适配并发流水线；若后续版本需追加字段，
  应通过 ``Reading.extra`` 等扩展槽位做向后兼容，而非破坏现有字段。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True, slots=True)
class Reading:
    """单个采样读数（传感器 → 冗余路由 → 总线）。

    Attributes:
        channel: 逻辑通道名（如 ``"heart_rate"``），用于冗余路由聚合。
        sensor_id: 物理传感器实例 ID，在同一逻辑通道内唯一。
        value: 采样数值。
        unit: 物理单位，例如 ``"bpm"``、``"g"``、``"dB"``、``"mA"``、
            ``"Hz"``、``"%"``。
        timestamp: 采样时间戳，Unix epoch 秒（float，UTC）。
        extra: 扩展键值对，供后续版本向后兼容地追加字段。
    """

    channel: str
    sensor_id: str
    value: float
    unit: str
    timestamp: float
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ActuatorCommand:
    """下发到执行器的指令（已通过安全层校验/截断）。

    Attributes:
        channel: 逻辑执行通道名（如 ``"tens_intensity"``）。
        actuator_id: 物理执行器实例 ID。
        value: 目标输出值，语义由 ``unit`` 决定。
        unit: 物理单位（``"mA"``、``"Hz"``、``"%"`` 等）。
        timestamp: 指令生成时间戳，Unix epoch 秒（float，UTC）。
    """

    channel: str
    actuator_id: str
    value: float
    unit: str
    timestamp: float


class FeedbackKind:
    """设备反馈类别常量（字符串标识，开放扩展）。

    用于 :class:`DeviceFeedback.kind`，区分执行器回传的不同信息类型：
    电量、信号、连接状态、执行确认、异常等。
    """

    BATTERY = "battery"
    SIGNAL = "signal"
    CONNECTION = "connection"
    ACK = "ack"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class DeviceFeedback:
    """执行器回传的一条设备反馈信息。

    与 :class:`Reading`（传感器上行）并列，表示「执行器/输出设备」的上行
    反馈：电量、信号强度、连接状态、执行确认或异常等。

    Attributes:
        device_id: 设备/执行器实例标识，在同一网关内唯一；跨实例聚合以
            此字段为键。
        kind: 反馈类别，取 :class:`FeedbackKind` 中的常量。
        channel: 逻辑通道名（设备级反馈可为空串，如电量/连接状态）。
        value: 可选数值（如电量 0.0~1.0、信号强度、连接布尔 0/1）。
        unit: 可选单位，若 ``value`` 有物理含义则标注（``"%"``、``"ratio"``、
            ``"bool"`` 等）。
        message: 可选文本描述（如错误信息、连接状态说明）。
        timestamp: 反馈产生时间戳，Unix epoch 秒（float，UTC）。
        extra: 扩展键值对，供后续版本向后兼容地追加字段。
    """

    device_id: str
    kind: str
    channel: str = ""
    value: Optional[float] = None
    unit: str = ""
    message: str = ""
    timestamp: float = field(default_factory=time.time)
    extra: Dict[str, Any] = field(default_factory=dict)