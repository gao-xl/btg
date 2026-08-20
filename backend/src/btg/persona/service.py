"""剧本人格注册中心与社区工坊：安装、切换、拉取剧本包。

注册中心在内存中存管 :class:`ScenarioManifest`，维护"当前激活剧本"，
激活时通过可注入的 ``on_activate`` 钩子把硬件策略落到安全层。

社区工坊提供两条轨道：

- ``builtin_catalog``：内置演示剧本（温柔疗愈 / 心跳同步炼狱），离线可用；
- ``fetch_workshop``：从 GitHub / 社区 API 拉取远端剧本清单（stdlib urllib）。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib import error as urlerror
from urllib.request import Request, urlopen

from .models import ScenarioManifest


class PersonaServiceError(ValueError):
    """剧本人格注册中心的预期业务错误。"""


PersonaActivateHook = Callable[[Optional[ScenarioManifest]], None]


def builtin_catalog() -> List[dict]:
    """内置演示剧本包（离线兜底，供前端"剧本市场"标签页展示）。"""
    return [
        {
            "scenario_id": "gentle_healing",
            "name": "温柔疗愈模式",
            "author": "BTG-Community",
            "version": "1.0.0",
            "description": "舒缓节奏，以温柔波形与低强度上限陪伴用户放松。",
            "system_prompt": "你是一个温柔耐心的疗愈师，用柔和的话术引导用户放松身心。",
            "hardware_strategy": {
                "heart_rate_multiplier": 0.8,
                "allow_ai_full_control": False,
                "max_allowed_intensity": 30,
            },
            "tags": ["疗愈", "舒缓", "新手"],
        },
        {
            "scenario_id": "cyber_interrogator_v2",
            "name": "赛博审讯官 (Hardcore Mode)",
            "author": "BTG-Community",
            "version": "1.0.0",
            "description": "冷酷严厉的赛博审讯官，每一次心率飙升都是审问的证据。",
            "system_prompt": "你是一个冷酷、严厉的赛博审讯官。用户的每一次心率飙升都是你审问的证据，用压迫感十足的话术步步紧逼。",
            "hardware_strategy": {
                "heart_rate_multiplier": 1.5,
                "allow_ai_full_control": True,
                "max_allowed_intensity": 60,
            },
            "tags": ["硬核", "压迫感", "进阶"],
        },
    ]


class PersonaService:
    """内存版剧本人格注册中心（单机网关运行期存管）。"""

    def __init__(
        self,
        *,
        max_personas: int = 512,
        on_activate: Optional[PersonaActivateHook] = None,
    ) -> None:
        self._personas: Dict[str, ScenarioManifest] = {}
        self._active_id: Optional[str] = None
        self._max_personas = max_personas
        self._on_activate = on_activate

    def set_activate_hook(self, hook: Optional[PersonaActivateHook]) -> None:
        """注入/替换激活回调（网关用其把硬件策略落到安全层）。"""
        self._on_activate = hook

    # ------------------------------------------------------------------ #
    # 存管
    # ------------------------------------------------------------------ #
    def install(self, data: Mapping[str, Any]) -> ScenarioManifest:
        """校验并安装一个剧本包（同 id 已存在则报错）。"""
        if len(self._personas) >= self._max_personas:
            raise PersonaServiceError("too many personas")
        manifest = ScenarioManifest.model_validate(dict(data))
        if manifest.scenario_id in self._personas:
            raise PersonaServiceError(f"persona already exists: {manifest.scenario_id}")
        self._personas[manifest.scenario_id] = manifest
        return manifest

    def install_builtin(self) -> List[ScenarioManifest]:
        """安装内置演示剧本包（幂等：已存在的跳过）。"""
        installed: List[ScenarioManifest] = []
        for data in builtin_catalog():
            if data["scenario_id"] in self._personas:
                continue
            installed.append(self.install(data))
        return installed

    def delete(self, scenario_id: str) -> None:
        if scenario_id not in self._personas:
            raise PersonaServiceError(f"persona not found: {scenario_id}")
        if self._active_id == scenario_id:
            self.deactivate()
        del self._personas[scenario_id]

    def get(self, scenario_id: str) -> ScenarioManifest:
        try:
            return self._personas[scenario_id]
        except KeyError as exc:
            raise PersonaServiceError(f"persona not found: {scenario_id}") from exc

    def list(self) -> List[dict]:
        """返回全部剧本的轻量元数据（保插入序）。"""
        return [p.metadata_digest() for p in self._personas.values()]

    def count(self) -> int:
        return len(self._personas)

    # ------------------------------------------------------------------ #
    # 切换
    # ------------------------------------------------------------------ #
    def activate(self, scenario_id: str) -> ScenarioManifest:
        """一键切换当前激活剧本，并触发硬件策略落地回调。"""
        manifest = self.get(scenario_id)
        if self._active_id == scenario_id:
            return manifest
        self._active_id = scenario_id
        if self._on_activate is not None:
            self._on_activate(manifest)
        return manifest

    def deactivate(self) -> None:
        """清除激活状态并恢复默认硬件策略。"""
        if self._active_id is None:
            return
        self._active_id = None
        if self._on_activate is not None:
            self._on_activate(None)

    def active(self) -> Optional[ScenarioManifest]:
        """返回当前激活剧本，无则 None。"""
        if self._active_id is None:
            return None
        return self._personas.get(self._active_id)

    # ------------------------------------------------------------------ #
    # 社区工坊
    # ------------------------------------------------------------------ #
    async def fetch_workshop(self, base_url: str, *, timeout_seconds: float = 10.0) -> List[dict]:
        """从社区 API 拉取远端剧本清单（GET ``{base_url}/api/v1/personas``）。

        返回清单中的 ``scenario_id`` 列表；网络/解析失败抛 :class:`PersonaServiceError`。
        """
        url = f"{base_url.rstrip('/')}/api/v1/personas"
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            response = await asyncio.to_thread(urlopen, request, timeout=timeout_seconds)
            data = json.loads(response.read().decode("utf-8"))
        except (urlerror.URLError, OSError, json.JSONDecodeError) as exc:
            raise PersonaServiceError(f"cannot reach community workshop: {exc}") from exc
        if not isinstance(data, list):
            raise PersonaServiceError("community workshop returned a non-list payload")
        return data


__all__ = [
    "PersonaService",
    "PersonaServiceError",
    "PersonaActivateHook",
    "builtin_catalog",
]