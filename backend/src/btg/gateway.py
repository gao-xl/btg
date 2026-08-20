"""网关装配核心：把平台内核 / HAL / fusion / safety / bus / integration
串成运行时。

``Gateway`` 是单节点网关的进程内装配器，负责：

- 通过 :class:`btg.platform.Kernel` 统一发现插件模块（内置 / 入口点 / 目录）；
- 解析设备/安全配置、构建通道管理器与融合引擎；
- 建立「传感器 → 队列 → 遥测缓存 + 事件总线 → 融合引擎」的采集管线；
- 建立「融合/手动/第三方指令 → 安全层 → 执行器」的下行管线；
- 订阅事件总线，把遥测与状态迁移转发给 WebSocket 与第三方平台；
- 采集执行器回传反馈并聚合，订阅配置中心热更新接线到安全层。

运行生命周期由 :func:`btg.bus.app.create_app` 的 lifespan 驱动（``start``/``stop``）。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from btg_sdk import ActuatorCommand, DeviceFeedback, Reading, get_provider_class

from btg.config import ConfigManager, SystemSettings
from btg.control import CommandDispatcher
from btg.core import AuditBlackbox, EventBus, TelemetryRingBuffer, get_logger
from btg.features import FeatureManager
from btg.feedback import FeedbackAggregator, FeedbackCollector
from btg.fusion import FusionEngine, Rule
from btg.hal import ChannelManager, DeviceConfig, load_config
from btg.hal.mqtt_bus import get_mqtt_bus
from btg.integration.manager import IntegrationManager
from btg.platform import Kernel, PlatformContext
from btg.play import PlaySessionManager
from btg.safety import (
    Guardrail,
    SafetyConfig,
    SafetyPolicy,
    Watchdog,
    load_safety_config,
)
from btg.settings import AppSettings
from btg.video import CameraRuntime
from btg.workflow import WorkflowRuntime

logger = get_logger(__name__)


def reading_to_dict(reading: Reading) -> Dict[str, Any]:
    """将采样读数序列化为可 JSON 输出的字典。"""
    return {
        "channel": reading.channel,
        "sensor_id": reading.sensor_id,
        "value": reading.value,
        "unit": reading.unit,
        "timestamp": reading.timestamp,
        "extra": dict(reading.extra or {}),
    }


class Gateway:
    """BTG 单节点网关的进程内运行时装配器。"""

    def __init__(
        self,
        *,
        settings: Optional[AppSettings] = None,
        config_manager: Optional[ConfigManager] = None,
        device_config: Optional[DeviceConfig] = None,
        safety_config: Optional[SafetyConfig] = None,
        rules: Optional[List[Rule]] = None,
    ) -> None:
        self.settings = settings or AppSettings()
        self.config_manager = config_manager or ConfigManager(self.settings.settings_path)

        self.event_bus = EventBus()
        self.ring_buffer = TelemetryRingBuffer(self.settings.telemetry_capacity)
        from btg.bus.websocket import TelemetryHub
        self.telemetry_hub = TelemetryHub()
        self.play_sessions = PlaySessionManager()

        # 插件平台内核：统一发现内置模块、pip 入口点与运行时插件目录。
        # discover() 同步完成 import（触发 @register_* 登记），供后续通道装配使用。
        self.kernel = Kernel(
            PlatformContext(
                event_bus=self.event_bus,
                ring_buffer=self.ring_buffer,
                config_manager=self.config_manager,
                settings=self.settings,
                logger=logger,
            ),
            self.settings,
        ).discover()

        # 剧情注册中心：由 story_engine 扩展模块提供，供 REST / 运行端取用。
        self.story_service = self._story_service()

        # 工作流编排器：由 workflow_engine 扩展模块提供注册中心，后端运行时单独装配。
        self.workflow_service = self._workflow_service()
        # 剧本人格市场：由 persona_market 扩展模块提供注册中心。
        self.persona_service = self._persona_service()
        # 复盘曲线：由 replay_log 扩展模块提供会话录制中心。
        self.replay_service = self._replay_service()

        # 功能开关：模块 + 内置服务，启动前把持久化状态应用到内核。
        self.features = FeatureManager(self)
        self.features.apply_initial()

        self.device_config = device_config or load_config(str(self.settings.device_config_path))
        self.safety_config = safety_config or load_safety_config(str(self.settings.safety_config_path))

        # 采集管线：传感器 -> 队列 ->（遥测缓存 + 事件总线）-> 融合引擎。
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=4096)
        self.channel_manager = ChannelManager(self.device_config, self._queue)
        self.channel_manager.build()

        self.fusion = FusionEngine(
            self.event_bus,
            list(rules or []),
            window_seconds=self.settings.fusion_window_seconds,
        )

        # 安全层：看门狗超时 -> 归零全部执行器 + 进入故障态。
        self.watchdog = Watchdog(
            self.safety_config.watchdog_timeout,
            self._on_watchdog_timeout,
        )
        # 黑盒审计：进程内「飞行数据记录器」，供风控因果链与复盘导出。
        self.blackbox = AuditBlackbox()
        # 分级安全闸：软降级限幅 + 硬急停归零（HR/IMU/WS 心跳三重触发）。
        self.guardrail = Guardrail(
            self.safety_config.guardrails,
            on_hard_stop=self._on_hard_interlock,
            blackbox=self.blackbox,
        )
        initial_max = float(self.config_manager.get_settings().max_system_intensity)
        self.safety_policy = SafetyPolicy(
            self.safety_config.clamps,
            self.watchdog,
            global_max=initial_max,
            guardrail=self.guardrail,
        )

        # 摄像头视频运行态（独立于遥测管线，前端视频控制页直接调度）。
        self.camera_runtime = CameraRuntime(self.settings.video_cameras_path)

        # 操作员急停状态：REST / 前端触发后保持，直到显式复位。
        self._estop_active = False
        self._estop_reason = ""

        # 剧本人格硬件策略落地：激活/清除时联动安全层最高强度。
        if self.persona_service is not None:
            self.persona_service.set_activate_hook(self._on_persona_activate)

        # 下行管线：指令分发器（安全层 -> 执行器冗余组）。
        self.dispatcher = CommandDispatcher(self.safety_policy, self.channel_manager)
        self.dispatcher.subscribe(self.event_bus)

        # 第三方 Outbound：订阅遥测/状态迁移并扇出到 provider。
        self.integration = IntegrationManager(self._build_providers(), self.event_bus)
        self.integration.subscribe(self.event_bus)

        # 设备反馈：执行器回传 -> 聚合器 + 事件总线广播。
        self.feedback = FeedbackAggregator(
            stale_after_seconds=self.settings.feedback_stale_after_seconds,
        )

        async def _record_feedback(feedback: DeviceFeedback) -> None:
            self.feedback.record(feedback)
            await self.event_bus.publish("device_feedback", feedback=feedback)

        self.feedback_collector = FeedbackCollector(
            self.channel_manager,
            interval_seconds=self.settings.feedback_poll_interval_seconds,
            sink=_record_feedback,
        )

        # 工作流编排器运行时：按 Tick 求值启用工作流并执行命中动作。
        self._workflow_triggers: set = set()
        self.workflow_runtime = WorkflowRuntime(
            self.workflow_service,
            context_provider=self.workflow_context,
            action_executor=self._execute_workflow_action,
        )

        self._wire_bus_forwarders()
        self._wire_config_reload()
        self._pump_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        """连接设备、启动看门狗、反馈采集与采集泵（幂等）。"""
        await self.kernel.setup()
        await self.channel_manager.start()
        await self.safety_policy.start()
        if self.features.is_enabled("integration"):
            await self.integration.start()
        if self.features.is_enabled("feedback"):
            await self.feedback_collector.start()
        if self.features.is_enabled("workflow"):
            await self.workflow_runtime.start()
        await self.kernel.start()
        if self._pump_task is None:
            self._pump_task = asyncio.create_task(self._pump())

    async def stop(self) -> None:
        """停止采集泵、第三方插件、看门狗、设备与插件模块（幂等）。"""
        if self._pump_task is not None:
            self._pump_task.cancel()
            try:
                await self._pump_task
            except asyncio.CancelledError:
                pass
            self._pump_task = None
        if self.features.is_enabled("feedback"):
            await self.feedback_collector.stop()
        if self.features.is_enabled("workflow"):
            await self.workflow_runtime.stop()
        if self.features.is_enabled("integration"):
            await self.integration.stop()
        await self.safety_policy.stop()
        await self.channel_manager.stop()
        await self.camera_runtime.stop_all()
        await self.kernel.stop()

    async def _pump(self) -> None:
        """采集泵：单消费者读取队列，写缓存、广播、送入融合引擎与安全闸。"""
        while True:
            reading = await self._queue.get()
            if not self.features.is_enabled("telemetry"):
                continue
            self.ring_buffer.push(reading)
            if self.replay_service is not None and self.features.is_enabled("replay"):
                self.replay_service.record_reading(reading)
            self.guardrail.ingest_reading(reading)
            try:
                await self.event_bus.publish("telemetry", reading=reading)
                await self.fusion.ingest(reading)
            except Exception:  # noqa: BLE001
                logger.exception("遥测处理异常 channel=%s", reading.channel)

    # ------------------------------------------------------------------ #
    # 下行指令入口（REST / integration 共用）
    # ------------------------------------------------------------------ #
    async def dispatch(self, command: ActuatorCommand) -> ActuatorCommand:
        """将单条指令经安全层校验后下发执行器。"""
        return await self.dispatcher.dispatch(command)

    # ------------------------------------------------------------------ #
    # 操作员急停（REST / 前端共用的显式硬停机入口）
    # ------------------------------------------------------------------ #
    async def estop(self, reason: str = "operator_estop") -> dict:
        """触发操作员急停：归零全部执行器、进入故障态并广播事件。

        急停状态保持到调用 :meth:`clear_estop` 显式复位。
        """
        self._estop_active = True
        self._estop_reason = reason
        self.blackbox.record(
            "operator_estop",
            cause=reason,
            action="hard_stop",
            result="all_channels=0",
        )
        await self.fusion.mark_fault(reason)
        await self._zero_all_actuators()
        await self.event_bus.publish("emergency_stop", reason=reason)
        return self.estop_status()

    def estop_status(self) -> dict:
        """返回当前急停 / 安全闸 / 看门狗状态，供前端与健康看板渲染。"""
        return {
            "estop_active": self._estop_active,
            "reason": self._estop_reason,
            "guardrail": self.guardrail.snapshot(),
            "watchdog_timeout": self.safety_config.watchdog_timeout,
            "state": self.fusion.state_machine.current,
        }

    async def clear_estop(self) -> dict:
        """复位操作员急停（仅清标；不自动恢复执行器强度）。"""
        self._estop_active = False
        self._estop_reason = ""
        await self.event_bus.publish("estop_cleared")
        return self.estop_status()

    # ------------------------------------------------------------------ #
    # 查询视图（REST / WebSocket 快照）
    # ------------------------------------------------------------------ #
    def snapshot_state(self) -> Dict[str, Any]:
        """返回当前状态机状态、最近迁移记录与各通道最新读数。"""
        settings = self.config_manager.get_settings()
        telemetry = {
            channel: reading_to_dict(reading)
            for channel, reading in self.ring_buffer.latest_all().items()
        }
        history = [
            {
                "previous": t.previous,
                "current": t.current,
                "reason": t.reason,
                "confidence": t.confidence,
                "timestamp": t.timestamp,
            }
            for t in self.fusion.state_machine.history
        ]
        return {
            "state": self.fusion.state_machine.current,
            "history": history,
            "telemetry": telemetry,
            "devices": self.feedback.snapshot(),
            "boards": get_mqtt_bus().boards(),
            "system_mode": settings.system_mode,
            "guardrail": self.guardrail.snapshot(),
        }

    def device_status(self) -> List[Dict[str, Any]]:
        """返回逻辑通道及其激活设备实例清单。"""
        channels: List[Dict[str, Any]] = []
        for name, group in self.channel_manager.sensor_groups.items():
            channels.append({
                "channel": name,
                "kind": "sensor",
                "active": group.active.instance_id if group.active is not None else None,
            })
        for name, group in self.channel_manager.actuator_groups.items():
            channels.append({
                "channel": name,
                "kind": "actuator",
                "active": group.active.instance_id if group.active is not None else None,
            })
        return channels

    def modules(self) -> List[Dict[str, Any]]:
        """返回平台已发现的插件模块清单。"""
        return self.kernel.snapshot()

    def _story_service(self):
        """从内核取回 story_engine 扩展模块挂载的剧情注册中心。"""
        module = self.kernel.registry.get("extension", "story_engine")
        return getattr(module, "service", None)

    def _extension_module(self, name: str):
        """按名字取回一个 ``extension`` 模块实例（不存在返回 None）。"""
        for module in self.kernel.registry.of_kind("extension"):
            if module.name == name:
                return module
        return None

    def _workflow_service(self):
        """取回 workflow_engine 扩展模块的工作流注册中心。"""
        module = self._extension_module("workflow_engine")
        return getattr(module, "service", None) if module else None

    def _persona_service(self):
        """取回 persona_market 扩展模块的剧本人格注册中心。"""
        module = self._extension_module("persona_market")
        return getattr(module, "service", None) if module else None

    def _replay_service(self):
        """取回 replay_log 扩展模块的会话录制中心。"""
        module = self._extension_module("replay_log")
        return getattr(module, "service", None) if module else None

    # ------------------------------------------------------------------ #
    # 装配细节
    # ------------------------------------------------------------------ #
    def _build_providers(self) -> List[Any]:
        providers: List[Any] = []
        for spec in self.settings.providers:
            cls = get_provider_class(spec["plugin"])
            providers.append(cls(config=spec.get("config", {})))
        return providers

    def _wire_bus_forwarders(self) -> None:
        @self.event_bus.on("telemetry")
        async def _forward_telemetry(reading: Reading, **kwargs: Any) -> None:
            self.telemetry_hub.publish({
                "type": "telemetry",
                **reading_to_dict(reading),
            })

        @self.event_bus.on("state_change")
        async def _forward_state(
            state: str,
            previous: str,
            reason: str,
            confidence: float,
            context: Dict[str, Any],
            **kwargs: Any,
        ) -> None:
            self.telemetry_hub.publish({
                "type": "state_change",
                "state": state,
                "previous": previous,
                "reason": reason,
                "confidence": confidence,
                "context": context or {},
                "timestamp": time.time(),
            })

        @self.event_bus.on("ai.prompt")
        async def _record_ai(prompt: str = "", **kwargs: Any) -> None:
            if self.replay_service is None or not self.features.is_enabled("replay"):
                return
            self.replay_service.record_ai(
                "ai_prompt",
                prompt,
                workflow_id=kwargs.get("workflow_id"),
                node_id=kwargs.get("node_id"),
                persona_hint=kwargs.get("persona_hint"),
            )

    def _wire_config_reload(self) -> None:
        self.config_manager.subscribe(self._on_settings_updated)

    def _on_persona_activate(self, manifest: Any = None) -> None:
        """剧本人格激活/清除时，把硬件策略落到安全层最高强度联动。

        ``manifest is None`` 表示清除当前激活，恢复配置中心的全局强度上限。
        """
        base = float(self.config_manager.get_settings().max_system_intensity)
        if manifest is not None:
            strategy = getattr(manifest, "hardware_strategy", None)
            limit = strategy.get("max_allowed_intensity") if isinstance(strategy, dict) else None
            if isinstance(limit, (int, float)):
                base = min(base, float(limit))
        self.safety_policy.global_max = base
        logger.info(
            "剧本人格硬件策略已应用 intensity=%s manifest=%s",
            base,
            getattr(manifest, "scenario_id", None),
        )

    def _on_settings_updated(self, settings: SystemSettings) -> None:
        """配置中心热更新 -> 安全层联动。"""
        self.safety_policy.global_max = float(settings.max_system_intensity)
        self.watchdog.set_timeout(settings.watchdog_timeout_sec)
        logger.info("安全层已应用热更新配置 intensity=%s watchdog_timeout=%s",
                    settings.max_system_intensity, settings.watchdog_timeout_sec)

    async def _on_watchdog_timeout(self) -> None:
        """看门狗心跳超时：进入故障态并归零全部执行器。"""
        await self.fusion.mark_fault("watchdog_timeout")
        for channel, group in self.channel_manager.actuator_groups.items():
            try:
                await group.stop()
            except Exception:
                logger.exception("看门狗归零执行器失败 channel=%s", channel)

    async def _on_hard_interlock(self, reason: str) -> None:
        """分级安全闸硬急停：绕过 AI/上层，直接归零全部执行器并进入故障态。"""
        self.blackbox.record(
            "hard_interlock_exec",
            cause=reason,
            action="zero_out_all_actuators",
            result="all_channels=0",
        )
        self._estop_active = True
        self._estop_reason = reason
        await self.fusion.mark_fault(reason)
        await self._zero_all_actuators()
        await self.event_bus.publish("guardrail_hard_stop", reason=reason)

    async def _zero_all_actuators(self) -> None:
        """把全部执行器通道归零（最佳努力，单通道失败不阻断其余通道）。"""
        for channel, group in self.channel_manager.actuator_groups.items():
            try:
                ok = await group.set_target(0.0)
                if not ok and group.active is not None:
                    await group.stop()
            except Exception:  # noqa: BLE001 - 归零失败不影响其他通道
                logger.exception("执行器通道归零失败 channel=%s", channel)

    # ------------------------------------------------------------------ #
    # 工作流编排器运行时适配
    # ------------------------------------------------------------------ #
    async def workflow_context(self) -> Dict[str, Any]:
        """构建工作流解释器的运行时上下文（心率/视觉/设备反馈/手动触发）。

        从遥测缓存与设备反馈聚合出解释器所需字段；手动触发采用"消费一次"
        语义——每 Tick 读出后即清空，避免同一安全词被反复命中。
        """
        latest = self.ring_buffer.latest_all()

        def channel_value(channel: str) -> Optional[float]:
            reading = latest.get(channel)
            return reading.value if reading is not None else None

        heart_rate = channel_value("heart_rate")
        heart_rate_delta: Optional[float] = None
        hr_history = self.ring_buffer.history("heart_rate", 2)
        if len(hr_history) >= 2:
            heart_rate_delta = hr_history[-1].value - hr_history[-2].value

        actuator: Dict[str, Optional[float]] = {
            "battery": channel_value("battery_pct"),
            "position": channel_value("position"),
            "channel_a_level": channel_value("channel_a_level"),
            "channel_b_level": channel_value("channel_b_level"),
        }
        # 设备反馈兜底：电量类别归一化到 0--100。
        if actuator["battery"] is None:
            for feedback in self.feedback.latest_all().values():
                if feedback.kind == "battery" and feedback.value is not None:
                    value = float(feedback.value)
                    actuator["battery"] = value * 100.0 if value <= 1.0 else value
                    break

        triggers = set(self._workflow_triggers)
        self._workflow_triggers.clear()
        return {
            "heart_rate": heart_rate,
            "heart_rate_delta": heart_rate_delta,
            "vision": {
                "pain": channel_value("pain_score"),
                "struggle": channel_value("struggle_score"),
            },
            "actuator": actuator,
            "manual_triggers": triggers,
        }

    def push_workflow_trigger(self, key: str) -> None:
        """注入一条手动触发（前端快捷键 / 安全词），供下一 Tick 消耗。"""
        self._workflow_triggers.add(key)

    async def _execute_workflow_action(self, action: Dict[str, Any]) -> None:
        """执行一条工作流命中动作：设强度/设位置下发执行器，AI 话术广播事件。"""
        kind = action.get("kind")
        trace = f"workflow={action.get('workflow_id')} node={action.get('node_id')}"
        if kind == "set_actuator_intensity":
            command = ActuatorCommand(
                channel=action["channel"],
                actuator_id="",
                value=float(action["value"]),
                unit=action.get("unit") or "",
                timestamp=time.time(),
            )
            safe = await self.dispatcher.dispatch(command)
            self.blackbox.record(
                "workflow_action",
                cause=trace,
                action=f"set_actuator_intensity {safe.channel}={safe.value}",
                result="dispatched",
            )
        elif kind == "set_actuator_position":
            command = ActuatorCommand(
                channel=action["channel"],
                actuator_id="",
                value=float(action["position"]),
                unit="ratio",
                timestamp=time.time(),
            )
            safe = await self.dispatcher.dispatch(command)
            self.blackbox.record(
                "workflow_action",
                cause=trace,
                action=f"set_actuator_position {safe.channel}={safe.value}",
                result="dispatched",
            )
        elif kind == "invoke_ai_prompt":
            await self.event_bus.publish(
                "ai.prompt",
                prompt=action.get("prompt", ""),
                persona_hint=action.get("persona_hint", ""),
                workflow_id=action.get("workflow_id"),
                node_id=action.get("node_id"),
            )
            self.blackbox.record(
                "workflow_action",
                cause=trace,
                action="invoke_ai_prompt",
                result=f"prompt={action.get('prompt', '')[:80]}",
            )
        else:
            logger.warning("未知工作流动作被忽略 kind=%s", kind)
