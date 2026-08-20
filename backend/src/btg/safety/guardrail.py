"""动态风控分级安全闸（Guardrail）：软降级限幅 + 硬急停归零双保险。

设计原则（详见 ``docs/architecture.md``）：安全闸是「动态风控」的一等公民，
位于数值截断之下、看门狗之上：

- **软降级（soft degradation）**：当心率达到预警线、或上层显式报告 AI 激进
  输出时进入降级态。此后经 :meth:`apply` 的所有下行强度被乘以衰减系数
  （限幅器），而非直接切断，实现「降级但不中断」。
- **硬急停（hard emergency stop）**：由底层硬件的三重独立触发——心率连续
  超危险线、IMU 捕获摔倒/挣扎、前端 WebSocket 心跳超时。任一命中即调用
  注入的 ``on_hard_stop`` 回调（网关把全部执行器归零），并锁存直到显式复位。

所有决策帧写入黑盒审计（:class:`btg.core.AuditBlackbox`），带因果链指针。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import Any, Awaitable, Callable, Optional, Set

from btg.core.audit_blackbox import AuditBlackbox
from btg.core.logging import get_audit_logger
from btg_sdk import Reading

from .config import GuardrailConfig

audit = get_audit_logger()

HardStopCallback = Callable[[str], Awaitable[None]]


class Guardrail:
    """面向单事件循环的分级安全闸。

    通过 :meth:`ingest_reading` 摄入心率/IMU 读数（事件驱动），通过后台
    监控协程检测前端 WebSocket 心跳超时（时间驱动）。任何硬急停触发只生效
    一次（锁存），需显式调用 :meth:`reset` 复位。
    """

    def __init__(
        self,
        config: GuardrailConfig,
        *,
        on_hard_stop: HardStopCallback,
        blackbox: Optional[AuditBlackbox] = None,
    ) -> None:
        self.config = config
        self._on_hard_stop = on_hard_stop
        self._blackbox = blackbox

        self._degraded = False
        self._degrade_sources: Set[str] = set()
        self._critical_count = 0
        self._hard_triggered = False
        self._hard_reason = ""
        self._last_hr: Optional[float] = None
        self._last_imu: Optional[float] = None
        self._last_heartbeat: Optional[float] = None
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ #
    # 版本/状态查询
    # ------------------------------------------------------------------ #
    @property
    def degraded(self) -> bool:
        """是否处于软降级态。"""
        return self._degraded

    @property
    def hard_triggered(self) -> bool:
        """硬急停是否已触发（锁存）。"""
        return self._hard_triggered

    @property
    def hard_reason(self) -> str:
        """最近一次硬急停的触发原因（未触发为空串）。"""
        return self._hard_reason

    def snapshot(self) -> dict:
        """返回当前风控状态 + 配置快照（供看板/审计）。"""
        return {
            "degraded": self._degraded,
            "degrade_sources": sorted(self._degrade_sources),
            "hard_triggered": self._hard_triggered,
            "hard_reason": self._hard_reason,
            "critical_count": self._critical_count,
            "last_hr": self._last_hr,
            "last_imu": self._last_imu,
            "last_heartbeat": self._last_heartbeat,
            "config": asdict(self.config),
        }

    # ------------------------------------------------------------------ #
    # 软降级（限幅）
    # ------------------------------------------------------------------ #
    def apply(self, value: float) -> float:
        """对下行强度应用衰减。

        处于软降级态时返回 ``value * attenuation_factor``；已触发硬急停时
        返回 0.0（彻底切断）；否则原样返回。
        """
        if self._hard_triggered:
            return 0.0
        if self._degraded:
            return value * self.config.attenuation_factor
        return value

    def degrade(self, reason: str, *, source: str = "external") -> None:
        """显式进入软降级态（如上层判定 AI 激进输出）。

        Args:
            reason: 人类可读的触发原因。
            source: 降级来源标识（``"heart_rate"`` / ``"ai"`` / ``"external"``）。
        """
        self._degrade_sources.add(source)
        if not self._degraded:
            self._degraded = True
            self._record(
                "soft_degrade",
                cause=reason,
                action="apply_attenuation",
                result=f"factor={self.config.attenuation_factor}",
                source=source,
            )

    def restore(self, *, source: Optional[str] = None) -> None:
        """解除软降级态。

        Args:
            source: 仅清除指定来源；``None`` 表示清除全部来源并立即复原。
        """
        if source is None:
            self._degrade_sources.clear()
        else:
            self._degrade_sources.discard(source)
        if not self._degrade_sources and self._degraded:
            self._degraded = False
            self._record("soft_restore", action="clear_attenuation", result="degraded=false")

    # ------------------------------------------------------------------ #
    # 硬急停（归零）
    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        """复位硬急停锁存与软降级态（供看板手动恢复）。"""
        self._hard_triggered = False
        if self._hard_reason:
            self._record(
                "hard_reset",
                cause=self._hard_reason,
                action="clear_interlock",
                result="hard=false",
            )
            self._hard_reason = ""
        self._critical_count = 0
        self.restore()

    def _hard_stop(self, reason: str) -> None:
        if self._hard_triggered:
            return
        self._hard_triggered = True
        self._hard_reason = reason
        self._record("hard_interlock", cause=reason, action="zero_out_actuators", result="latched")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 无事件循环（如纯同步测试）：无法 await 回调，仅记录状态。
            audit.warning("硬急停触发但无运行中的事件循环，跳过归零回调: %s", reason)
            return
        loop.create_task(self._invoke_hard_stop(reason))

    async def _invoke_hard_stop(self, reason: str) -> None:
        try:
            await self._on_hard_stop(reason)
        except Exception:  # noqa: BLE001 - 归零失败不遮蔽已锁存的急停态
            audit.exception("硬急停归零回调执行失败: %s", reason)

    # ------------------------------------------------------------------ #
    # 遥测摄入（心率/IMU）
    # ------------------------------------------------------------------ #
    def ingest_reading(self, reading: Reading) -> None:
        """摄入一条遥测读数，驱动心率/IMU 分级风控。"""
        if reading.channel == self.config.heart_rate_channel:
            self._ingest_heart_rate(reading.value)
        elif reading.channel == self.config.imu_channel:
            self._ingest_imu(reading.value)

    def _ingest_heart_rate(self, value: float) -> None:
        self._last_hr = value
        if value >= self.config.heart_rate_critical_bpm:
            self._critical_count += 1
            if self._critical_count >= self.config.heart_rate_critical_consecutive:
                self._hard_stop(
                    f"心率连续超限 value={value} consecutive={self._critical_count}"
                )
                return
        else:
            self._critical_count = 0

        if self._hard_triggered:
            return

        if value >= self.config.heart_rate_warn_bpm:
            self.degrade(f"心率达到预警线 value={value}", source="heart_rate")
        elif value < self.config.heart_rate_reset_bpm:
            self.restore(source="heart_rate")

    def _ingest_imu(self, value: float) -> None:
        self._last_imu = value
        if value >= self.config.imu_fall_threshold:
            self._hard_stop(f"IMU 摔倒/挣扎超限 value={value}")

    # ------------------------------------------------------------------ #
    # 前端 WebSocket 心跳
    # ------------------------------------------------------------------ #
    def feed_heartbeat(self) -> None:
        """前端 WebSocket 心跳保活（每收到一次 ping 调用）。"""
        self._last_heartbeat = time.monotonic()

    def _check_heartbeat(self) -> None:
        if self._last_heartbeat is None or self._hard_triggered:
            return
        if time.monotonic() - self._last_heartbeat >= self.config.ws_heartbeat_timeout:
            self._hard_stop(
                f"前端 WebSocket 心跳超时 timeout={self.config.ws_heartbeat_timeout}s"
            )

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        """启动后台心跳监控协程（幂等）。"""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._monitor())

    async def _monitor(self) -> None:
        while True:
            await asyncio.sleep(self.config.poll_interval)
            self._check_heartbeat()

    async def stop(self) -> None:
        """停止后台监控协程（幂等）。"""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _record(self, event: str, *, cause: str = "", action: str = "", result: str = "", **data: Any) -> None:
        if self._blackbox is not None:
            self._blackbox.record(event, cause=cause, action=action, result=result, **data)
        audit.warning("风控事件 event=%s cause=%s action=%s result=%s", event, cause, action, result)