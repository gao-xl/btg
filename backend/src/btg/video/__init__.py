"""摄像头视频运行态：可独立于采集管线控制的视频源管理与算法处理。

提供 :class:`CameraRuntime`，管理命名相机（USB / RTSP）的启停、最新帧缓存、
算法切换与运行指标。供 ``video_routes``（REST）与网关（生命周期清理）使用。
依赖可选的 OpenCV 与 PyYAML；缺失时相机清单仍可维护，仅启动采集会报错。
"""
from __future__ import annotations

from .runtime import CameraRuntime, CameraDef

__all__ = ["CameraRuntime", "CameraDef"]