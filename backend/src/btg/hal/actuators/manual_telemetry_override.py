"""手动遥测与位置校准通道模块。

允许前端用户或操作员手动录入、更新设备的虚拟位置、主观刺激深度或
校准参数，并将其注入系统的融合引擎与遥测总线。

核心设计：

1. **ManualOverrideStore**：内存级状态存储，按 device_id 维护手动覆盖值。
   每次写入自动触发事件总线广播与 WebSocket 推送。

2. **状态合并**：手动覆盖值与硬件自动遥测合并。如果硬件本身没有位置
   反馈，手动值即为「权威位置（Authoritative Position）」。

3. **输入校验**：manual_position 限制在 0–100，subjective_intensity 限制
   在 0–100，timestamp 必须为正数。

使用示例::

    store = ManualOverrideStore(event_bus=bus, hub=hub)
    override = await store.update(ManualOverrideRequest(
        device_id="coyote_pro_01",
        manual_position=75.0,
        subjective_intensity=40,
    ))
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from btg.core.events import EventBus


# ── 请求/响应模型 ──────────────────────────────────────────────────────────


class ManualOverrideRequest(BaseModel):
    """前端提交的手动覆盖请求。"""

    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, description="目标设备 ID")
    manual_position: float = Field(
        ge=0.0, le=100.0,
        description="用户手动录入的当前位置百分比 (0–100)",
    )
    subjective_intensity: int = Field(
        default=0, ge=0, le=100,
        description="用户主观感受强度 (0–100)",
    )
    timestamp: float = Field(
        default=0.0, gt=0.0,
        description="录入时间戳（Unix epoch 秒），0 表示使用服务器当前时间",
    )
    source: str = Field(
        default="operator",
        description="录入来源标识（operator / ai / scenario）",
    )
    note: str = Field(
        default="",
        description="可选备注信息",
    )


@dataclass(frozen=True, slots=True)
class ManualOverride:
    """一条已生效的手动覆盖记录。"""

    device_id: str
    manual_position: float
    subjective_intensity: int
    authoritative_position: float
    timestamp: float
    source: str
    note: str
    updated_at: float = field(default_factory=time.time)


# ── 存储与广播 ────────────────────────────────────────────────────────────


class ManualOverrideStore:
    """手动覆盖状态存储：按 device_id 维护最新覆盖值，写入即广播。

    本类面向单 asyncio 事件循环使用，``update`` 为同步快速路径 +
    异步广播，无需加锁。
    """

    def __init__(
        self,
        *,
        event_bus: Optional[EventBus] = None,
        hub: Any = None,
        on_broadcast: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> None:
        """
        Args:
            event_bus: 网关事件总线，用于发布 ``manual_override`` 事件。
            hub: WebSocket 广播枢纽（``TelemetryHub``），用于推送到前端。
            on_broadcast: 可选的自定义广播回调（测试/扩展用）。
        """
        self._event_bus = event_bus
        self._hub = hub
        self._on_broadcast = on_broadcast
        self._overrides: Dict[str, ManualOverride] = {}
        self._history: Dict[str, List[ManualOverride]] = {}

    async def update(self, request: ManualOverrideRequest) -> ManualOverride:
        """处理一条手动覆盖请求，合并状态并广播。

        Returns:
            合并后的 ManualOverride 记录。
        """
        now = time.time()
        ts = request.timestamp if request.timestamp > 0 else now

        # 如果已有旧覆盖，以旧值为基准合并；否则以请求值为权威位置
        existing = self._overrides.get(request.device_id)
        if existing is not None:
            # 合并策略：手动位置以新值为准，主观强度取新值（若非默认）
            auth_position = request.manual_position
            subj = (
                request.subjective_intensity
                if request.subjective_intensity > 0
                else existing.subjective_intensity
            )
        else:
            auth_position = request.manual_position
            subj = request.subjective_intensity

        override = ManualOverride(
            device_id=request.device_id,
            manual_position=request.manual_position,
            subjective_intensity=subj,
            authoritative_position=auth_position,
            timestamp=ts,
            source=request.source,
            note=request.note,
            updated_at=now,
        )

        self._overrides[request.device_id] = override

        # 追加历史
        hist = self._history.get(request.device_id)
        if hist is None:
            hist = []
            self._history[request.device_id] = hist
        hist.append(override)
        if len(hist) > 256:
            self._history[request.device_id] = hist[-256:]

        # 广播
        await self._broadcast(override)

        return override

    def get(self, device_id: str) -> Optional[ManualOverride]:
        """返回某设备的最新手动覆盖，无数据返回 None。"""
        return self._overrides.get(device_id)

    def get_all(self) -> Dict[str, ManualOverride]:
        """返回所有设备的最新手动覆盖（副本）。"""
        return dict(self._overrides)

    def get_authoritative_position(self, device_id: str) -> Optional[float]:
        """返回某设备的权威位置（手动覆盖或 None）。"""
        override = self._overrides.get(device_id)
        return override.authoritative_position if override else None

    def get_merged_telemetry(
        self,
        device_id: str,
        hardware_telemetry: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """将手动覆盖与硬件遥测合并，返回合并后的全息状态。

        如果硬件遥测中缺少位置字段，以手动覆盖的权威位置补全。
        """
        override = self._overrides.get(device_id)
        merged: Dict[str, Any] = dict(hardware_telemetry or {})

        if override is not None:
            merged["manual_position"] = override.manual_position
            merged["subjective_intensity"] = override.subjective_intensity
            merged["authoritative_position"] = override.authoritative_position
            merged["override_source"] = override.source
            merged["override_timestamp"] = override.updated_at

            # 如果硬件没有位置反馈，手动值即权威位置
            if "position" not in merged or merged["position"] is None:
                merged["position"] = override.authoritative_position
                merged["position_source"] = "manual_override"
            else:
                merged["position_source"] = "hardware"
        else:
            if "position" in hardware_telemetry:
                merged["position_source"] = "hardware"

        return merged

    def history(
        self, device_id: str, *, limit: Optional[int] = None
    ) -> List[ManualOverride]:
        """按时间升序返回某设备覆盖历史（副本）。"""
        hist = self._history.get(device_id, [])
        items = list(hist)
        if limit is not None:
            items = items[-limit:]
        return items

    def clear(self, device_id: Optional[str] = None) -> None:
        """清空覆盖记录（幂等）。"""
        if device_id is not None:
            self._overrides.pop(device_id, None)
            self._history.pop(device_id, None)
        else:
            self._overrides.clear()
            self._history.clear()

    def snapshot(self) -> Dict[str, Any]:
        """返回所有设备覆盖的可 JSON 序列化快照。"""
        return {
            device_id: {
                "device_id": o.device_id,
                "manual_position": o.manual_position,
                "subjective_intensity": o.subjective_intensity,
                "authoritative_position": o.authoritative_position,
                "timestamp": o.timestamp,
                "source": o.source,
                "note": o.note,
                "updated_at": o.updated_at,
            }
            for device_id, o in self._overrides.items()
        }

    # ── 内部 ──────────────────────────────────────────────────────────────

    async def _broadcast(self, override: ManualOverride) -> None:
        """通过事件总线和 WebSocket 广播覆盖事件。"""
        payload = {
            "type": "manual_override",
            "device_id": override.device_id,
            "manual_position": override.manual_position,
            "subjective_intensity": override.subjective_intensity,
            "authoritative_position": override.authoritative_position,
            "timestamp": override.timestamp,
            "source": override.source,
            "note": override.note,
            "updated_at": override.updated_at,
        }

        # 事件总线
        if self._event_bus is not None:
            try:
                await self._event_bus.publish("manual_override", override=payload)
            except Exception:  # noqa: BLE001
                pass

        # WebSocket 广播
        if self._hub is not None:
            try:
                self._hub.publish(payload)
            except Exception:  # noqa: BLE001
                pass

        # 自定义回调
        if self._on_broadcast is not None:
            try:
                result = self._on_broadcast(payload)
                if hasattr(result, "__await__"):
                    await result
            except Exception:  # noqa: BLE001
                pass
