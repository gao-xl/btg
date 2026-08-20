"""Built-in, device-neutral waveform previews inspired by YoKonex.

Values are normalized percentages.  This module never talks to an actuator;
the catalog is presentation and recommendation data only.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Waveform:
    key: str
    name: str
    description: str
    frames: tuple[int, ...]

    def preview(self, cap: int) -> list[int]:
        """Scale normalized frames into an operator-declared display envelope."""
        if not 0 <= cap <= 100:
            raise ValueError("cap must be in [0, 100]")
        return [round(frame * cap / 100) for frame in self.frames]


class WaveformCatalog:
    """Small immutable catalog; no uploaded files or executable payloads."""

    def __init__(self) -> None:
        waves = (
            Waveform("breathe", "呼吸", "平缓起伏", (0, 20, 40, 60, 80, 100, 80, 60, 40, 20)),
            Waveform("tide", "潮汐", "长周期渐入渐出", (0, 10, 25, 45, 70, 90, 100, 90, 70, 45, 25, 10)),
            Waveform("combo", "连击", "短促分组节奏", (60, 0, 60, 0, 25, 0, 80, 0, 80, 0, 0, 0)),
            Waveform("fast_pinch", "快速按捏", "快速强弱交替", (80, 0, 40, 0, 80, 0, 40, 0)),
            Waveform("pinch_crescendo", "按捏渐强", "逐级增强的推荐形态", (10, 0, 20, 0, 35, 0, 50, 0, 70, 0, 90, 0)),
            Waveform("heartbeat", "心跳", "双拍与停顿", (85, 0, 45, 0, 0, 0, 85, 0, 45, 0, 0, 0)),
            Waveform("compress", "压缩", "由强到弱再回升", (100, 80, 60, 40, 20, 10, 20, 40, 60, 80)),
            Waveform("rhythm_step", "节奏步伐", "规律阶梯节拍", (20, 20, 50, 0, 20, 20, 75, 0, 20, 20, 100, 0)),
        )
        self._waves = {wave.key: wave for wave in waves}

    def keys(self) -> tuple[str, ...]:
        return tuple(self._waves)

    def get(self, key: str) -> Waveform:
        try:
            return self._waves[key]
        except KeyError as exc:
            raise KeyError(f"unknown waveform: {key}") from exc

    def public_list(self) -> list[dict[str, object]]:
        return [
            {
                "key": wave.key,
                "name": wave.name,
                "description": wave.description,
                "frame_count": len(wave.frames),
                "normalized_preview": list(wave.frames),
            }
            for wave in self._waves.values()
        ]
