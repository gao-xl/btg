"""硬件与集成插件的抽象基类。

设计原则（详见 ``docs/architecture.md``）：

- 核心网关业务层绝不 import 任何具体厂商型号，只依赖本模块定义的接口。
- 所有网络 I/O 与硬件 I/O 均为 ``async/await``，禁止同步阻塞调用。
- ``disconnect()`` / ``stop()`` 必须幂等，供资源释放与故障安全路径调用。
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod


class BaseSensor(ABC):
    """传感器抽象接口。

    实现者需在 ``read_stream()`` 内部处理断连重连（``try/except/finally``），
    并在连接被外部终止或不可恢复时正常退出协程，以触发冗余层故障切换。
    """

    @abstractmethod
    async def connect(self) -> bool:
        """建立物理连接（BLE 连接、打开串口等）。

        Returns:
            bool: 连接成功返回 True。

        Raises:
            ConnectionError: 无法建立连接时抛出，由冗余层触发备用设备切换。
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """释放物理资源。必须幂等，可被重复调用。"""
        ...

    @abstractmethod
    async def read_stream(self, out_queue: asyncio.Queue) -> None:
        """持续读取采样数据并写入 ``out_queue``（长任务）。

        实现者应保持长任务运行，将每次采样以 ``Reading`` 实例（见
        ``btg_sdk.types.Reading``）通过 ``out_queue.put_nowait()`` 写出，
        直至被取消或发生不可恢复断连才退出，由冗余层接管故障切换。

        Args:
            out_queue: 异步队列，用于向总线推送采样读数。
        """
        ...


class BaseActuator(ABC):
    """执行器抽象接口（TENS 电刺激器、震动电机、继电器等）。

    ``set_target()`` 收到的值已经过安全层截断/校验；实现侧仍应保留
    最终边界防御，但无需重复业务级策略判断。
    """

    @abstractmethod
    async def connect(self) -> bool:
        """建立物理连接。

        Returns:
            bool: 连接成功返回 True。

        Raises:
            ConnectionError: 无法建立连接时抛出。
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """释放物理资源。必须幂等，可被重复调用。"""
        ...

    @abstractmethod
    async def set_target(self, channel: str, value: float) -> bool:
        """下发目标强度/频率。

        Args:
            channel: 逻辑执行通道名（如 ``"intensity"``、``"frequency"``）。
            value: 目标值，语义由通道决定（典型单位 ``mA``、``Hz``、``%``）。

        Returns:
            bool: 下发成功返回 True。

        Raises:
            ValueError: 数值越界（虽经安全层截断，仍做最后防御）。
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """紧急/故障安全归零：立即停止输出并物理断开。必须幂等。

        供 Watchdog 心跳超时触发，或安全策略判定降级时调用。
        """
        ...

    async def collect_feedback(self) -> list:
        """可选：采集该执行器回传的设备反馈信息（默认返回空列表）。

        返回 :class:`btg_sdk.DeviceFeedback` 实例列表，供反馈聚合模块统一
        收集中。未实现反馈能力的执行器无需覆写本方法。
        """
        return []


class ThirdPartyProvider(ABC):
    """第三方平台接入接口（Home Assistant / Tuya / 通用 HTTP Webhook 等）。

    负责将网关的遥测/状态向外推送（Outbound）。第三方主动下发控制
    （Inbound，``POST /integration/v1/control``）由 ``integration`` 层接收
    后转入内部安全管道，不在此接口层实现。
    """

    @abstractmethod
    async def push_telemetry(self, data: dict) -> bool:
        """向第三方推送遥测/状态数据（Webhook 风格）。

        Args:
            data: JSON 可序列化的事件载荷，字段由实现方与第三方约定。

        Returns:
            bool: 推送成功返回 True。

        Raises:
            ConnectionError: 推送失败（网络断开/超时）时抛出，由调用方决定重试。
        """
        ...