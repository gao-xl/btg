"""全局配置中心（Configuration Center）。

集中管理系统可热更新的运行参数（安全阈值、看门狗超时、心率目标等），
统一提供三点能力：

1. 从 ``config/settings.yaml`` 加载配置，文件缺失时用默认值并自动创建；
2. 内存读取与局部更新，更新校验通过后同步持久化回 YAML（原子写入）；
3. 变更通知，供安全层、看门狗等内部模块实时订阅。

模块级单例 ``config_manager`` 供全系统共享；REST 端点见
``btg.bus.settings_routes``。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

# 仓库根目录：backend/src/btg/config/ -> btg -> src -> backend -> 仓库根
_CONFIG_DIR = Path(__file__).resolve().parents[4] / "config"
DEFAULT_CONFIG_PATH = _CONFIG_DIR / "settings.yaml"

SettingsListener = Callable[["SystemSettings"], None]


class AISettings(BaseModel):
    """AI / LLM 主控配置模型（可由设置页热更新，持久化到 ``settings.yaml``）。

    注意：``api_key`` 为明文凭据，仅持久化在本地 ``settings.yaml``（须被 gitignore）。
    REST GET 会将其脱敏为 ``null`` 并返回 ``has_api_key`` 标记；PUT 时空字符串表示
    “不修改已存密钥”，由 :meth:`ConfigManager.update_settings` 特殊处理。

    Attributes:
        provider: 厂商，``mock``（离线兜底）/ ``openai``（OpenAI 兼容）/ ``anthropic``。
        base_url: 自定义 API 基址；留空则按厂商默认值（openai: api.openai.com / anthropic: api.anthropic.com）。
        model: 模型名；留空则按厂商默认值。
        api_key: 凭据；留空且 ``has_api_key`` 为真时表示保留既有密钥。
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["mock", "openai", "anthropic"] = Field(
        default="mock", description="AI 厂商"
    )
    base_url: str = Field(default="", description="自定义 API 基址（留空用厂商默认）")
    model: str = Field(default="", description="模型名（留空用厂商默认）")
    api_key: str = Field(default="", description="API 凭据（明文，本地存储）")


class SystemSettings(BaseModel):
    """全局系统配置模型。

    Attributes:
        max_system_intensity: 全局最高强度限制（任意物理量强度上限，非负）。
        watchdog_timeout_sec: 看门狗心跳超时时间（秒，必须为正）。
        edging_target_hr: 心率寸止目标值（bpm，非负）。
        system_mode: 系统运行模式，仅允许 ``manual`` 或 ``api_script``。
        algorithm_mode: 视频算法模式，可选帧差或 MediaPipe Pose。
        ai: AI / LLM 主控配置（厂商、基址、模型、密钥）。
    """

    model_config = ConfigDict(extra="forbid")

    max_system_intensity: int = Field(default=50, ge=0, description="全局最高强度限制")
    watchdog_timeout_sec: float = Field(default=2.0, gt=0.0, description="看门狗超时时间（秒）")
    edging_target_hr: int = Field(default=135, ge=0, description="心率寸止目标值（bpm）")
    system_mode: Literal["manual", "api_script"] = Field(
        default="manual", description="系统运行模式"
    )
    algorithm_mode: Literal["classical_motion", "mediapipe_pose"] = Field(
        default="classical_motion", description="视频算法模式"
    )
    ai: AISettings = Field(default_factory=AISettings, description="AI / LLM 主控配置")
    feature_flags: Dict[str, bool] = Field(
        default_factory=dict,
        description="功能开关：key -> 是否启用（模块名或内置服务名）",
    )


class ConfigManager:
    """加载、读取、更新并持久化全局配置，并广播变更通知。"""

    def __init__(self, config_path: Optional[Path | str] = None) -> None:
        self._config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._settings: SystemSettings = self._load()
        self._listeners: List[SettingsListener] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # 读取
    # ------------------------------------------------------------------ #
    @property
    def config_path(self) -> Path:
        """当前配置文件绝对路径。"""
        return self._config_path

    def get_settings(self) -> SystemSettings:
        """返回当前配置快照（pydantic 模型，含真实 ``ai.api_key``）。

        内部模块（主控代理、剧情导入器）应使用此方法读取真实凭据；
        对外 REST 端点应使用 :meth:`get_public_settings` 以避免泄露密钥。
        """
        return self._settings

    def get_public_settings(self) -> Dict[str, Any]:
        """返回对外安全的配置快照：``ai.api_key`` 脱敏为 ``null`` 并附加 ``has_api_key``。"""
        data = self._settings.model_dump()
        ai = dict(data.get("ai") or {})
        if ai.get("api_key"):
            ai["api_key"] = None
            ai["has_api_key"] = True
        else:
            ai["has_api_key"] = False
        data["ai"] = ai
        return data

    # ------------------------------------------------------------------ #
    # 更新
    # ------------------------------------------------------------------ #
    def update_settings(self, new_settings: Dict[str, Any]) -> SystemSettings:
        """局部更新配置，校验通过后写入内存并原子持久化到 YAML。

        传入的字典仅需包含要修改的字段；未知字段或非法值会触发
        ``pydantic.ValidationError`` 并由调用方（API 路由）转为 400。

        ``ai`` 子字段做**深合并**：只传入部分字段不会清空未传字段。
        当 ``ai.api_key`` 为空字符串且既有配置已存密钥时，保留原密钥
        （前端以空值表达“不修改”）。

        Raises:
            ValidationError: 字段非法、类型不符或出现未声明字段。
            OSError: 持久化写入失败（磁盘不可写等）。
        """
        with self._lock:
            current = self._settings.model_dump()
            merged: Dict[str, Any] = dict(current)
            for key, value in new_settings.items():
                if key == "ai" and isinstance(value, dict):
                    merged["ai"] = {**(current.get("ai") or {}), **value}
                else:
                    merged[key] = value

            ai = merged.get("ai")
            if isinstance(ai, dict):
                incoming_key = (ai.get("api_key") or "").strip()
                existing_key = (current.get("ai") or {}).get("api_key") or ""
                if not incoming_key and existing_key:
                    ai["api_key"] = existing_key
                merged["ai"] = ai

            updated = SystemSettings.model_validate(merged)
            self._persist(updated)
            self._settings = updated

        self._notify(updated)
        logger.info("系统配置已更新: %s", updated.model_dump(exclude={"ai": {"api_key"}}))
        return updated

    # ------------------------------------------------------------------ #
    # 变更订阅
    # ------------------------------------------------------------------ #
    def subscribe(self, listener: SettingsListener) -> None:
        """注册配置变更监听器（幂等，重复注册忽略）。"""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def _notify(self, settings: SystemSettings) -> None:
        for listener in list(self._listeners):
            try:
                listener(settings)
            except Exception:  # noqa: BLE001
                logger.exception("配置变更监听器执行异常: %r", listener)

    # ------------------------------------------------------------------ #
    # 持久化
    # ------------------------------------------------------------------ #
    def _load(self) -> SystemSettings:
        """从磁盘加载配置；文件缺失/损坏/非法时回退默认值。"""
        path = self._config_path
        if not path.exists():
            defaults = SystemSettings()
            try:
                self._persist(defaults)
            except OSError:
                logger.exception("初始化默认配置写入失败: %s", path)
            return defaults

        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError, UnicodeDecodeError):
            logger.exception("加载配置文件失败，回退默认值: %s", path)
            return SystemSettings()

        if not isinstance(raw, dict):
            logger.error("配置文件内容非字典，回退默认值: %s", path)
            return SystemSettings()

        try:
            return SystemSettings.model_validate(raw)
        except ValidationError:
            logger.exception("配置文件字段非法，回退默认值: %s", path)
            return SystemSettings()

    def _persist(self, settings: SystemSettings) -> None:
        """原子写入配置：先写临时文件再 replace，避免写坏 YAML。"""
        path = self._config_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                settings.model_dump(),
                f,
                allow_unicode=True,
                sort_keys=False,
            )
        tmp_path.replace(path)


# 全局单例，供各模块与 API 路由共享
config_manager = ConfigManager()
