"""功能开关管理（Feature Flags）。

统一管理两类开关：

- 平台模块：来自 :class:`btg.platform.Kernel` 发现的插件模块，启停走模块
  生命周期（``setup → start → stop``）；
- 内置服务：遥测采集、手动控制、AI 对话、玩法波形、故事引擎、第三方集成、
  设备反馈等，启停走对应网关组件生命周期或路由/采集泵门控。

开关状态持久化在配置中心 ``settings.yaml`` 的 ``feature_flags`` 字段，
运行期通过 ``PUT /api/v1/features`` 热更新。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:  # pragma: no cover - avoid runtime cycle with gateway.py
    from btg.gateway import Gateway

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeatureSpec:
    """内置服务开关定义。"""

    key: str
    label: str
    description: str
    default: bool = True
    locked: bool = False


BUILTIN_FEATURES: List[FeatureSpec] = [
    FeatureSpec("telemetry", "遥测采集", "传感器采样、遥测缓存与事件流"),
    FeatureSpec("manual_control", "手动控制", "REST/前端手动下发执行器指令"),
    FeatureSpec("ai_dialogue", "AI 对话", "LLM 主控代理对话与决策"),
    FeatureSpec("play_waves", "玩法波形", "玩法波形库与推荐会话"),
    FeatureSpec("story", "故事引擎", "剧情导入与场景执行"),
    FeatureSpec("workflow", "工作流编排", "触发/条件/动作节点的可视化自动化闭环"),
    FeatureSpec("persona", "剧本人格", "剧本/人格切换与社区工坊"),
    FeatureSpec("replay", "复盘曲线", "会话遥测录制与多维时空对齐回放"),
    FeatureSpec("integration", "第三方集成", "第三方平台出站推送与控制"),
    FeatureSpec("feedback", "设备反馈", "执行器回传反馈采集"),
    FeatureSpec("watchdog", "安全看门狗", "控制心跳超时归零（安全项）", locked=True),
    FeatureSpec("blackbox", "黑盒审计", "飞行数据记录器（安全项）", locked=True),
]


class FeatureManager:
    """功能开关：收集平台模块 + 内置服务，持久化并热更新启停。"""

    def __init__(self, gateway: "Gateway") -> None:
        self.gateway = gateway
        self._flags: Dict[str, bool] = dict(
            gateway.config_manager.get_settings().feature_flags
        )

    # ------------------------------------------------------------------ #
    # 读取
    # ------------------------------------------------------------------ #
    def is_enabled(self, key: str) -> bool:
        """功能是否启用：内置服务按默认值，模块默认启用。"""
        if key in self._flags:
            return self._flags[key]
        for spec in BUILTIN_FEATURES:
            if spec.key == key:
                return spec.default
        return True

    def list_features(self) -> List[Dict[str, Any]]:
        """返回平台模块 + 内置服务的完整开关清单。"""
        features: List[Dict[str, Any]] = []
        for module in self.gateway.kernel.snapshot():
            features.append({
                "key": module["name"],
                "label": module["name"],
                "description": module.get("description", ""),
                "group": "module",
                "kind": module.get("kind", ""),
                "enabled": self.is_enabled(module["name"]),
                "locked": False,
            })
        for spec in BUILTIN_FEATURES:
            features.append({
                "key": spec.key,
                "label": spec.label,
                "description": spec.description,
                "group": "service",
                "kind": "service",
                "enabled": self.is_enabled(spec.key),
                "locked": spec.locked,
            })
        return features

    def apply_initial(self) -> None:
        """启动前把持久化的模块开关应用到内核（不触发生命周期）。"""
        for module in self.gateway.kernel.snapshot():
            if not self.is_enabled(module["name"]):
                self.gateway.kernel.set_enabled(module["name"], False)

    # ------------------------------------------------------------------ #
    # 更新
    # ------------------------------------------------------------------ #
    async def apply(self, updates: Dict[str, bool]) -> List[Dict[str, Any]]:
        """应用开关变更：启停对应模块/服务并持久化。

        Args:
            updates: ``{key: enabled}`` 字典，仅包含要变更的项。

        Returns:
            更新后的完整开关清单。
        """
        known = {f["key"] for f in self.list_features()}
        changed = False
        for key, enabled in updates.items():
            if key not in known:
                logger.warning("忽略未知功能开关: %s", key)
                continue
            if self.is_enabled(key) == bool(enabled):
                continue
            if self._is_locked(key):
                logger.warning("安全项不可关闭: %s", key)
                continue
            await self._apply_one(key, bool(enabled))
            self._flags[key] = bool(enabled)
            changed = True

        if changed:
            self._persist()
        return self.list_features()

    def _is_locked(self, key: str) -> bool:
        for spec in BUILTIN_FEATURES:
            if spec.key == key:
                return spec.locked
        return False

    async def _apply_one(self, key: str, enabled: bool) -> None:
        """把单个开关落到对应组件（模块生命周期或服务启停）。"""
        gateway = self.gateway
        if key == "integration":
            if enabled:
                await gateway.integration.start()
            else:
                await gateway.integration.stop()
            return
        if key == "feedback":
            if enabled:
                await gateway.feedback_collector.start()
            else:
                await gateway.feedback_collector.stop()
            return
        # 其余服务为路由/采集泵门控，无需生命周期动作；模块名走内核启停。
        await gateway.kernel.set_module_enabled(key, enabled)

    def _persist(self) -> None:
        self.gateway.config_manager.update_settings({"feature_flags": dict(self._flags)})
