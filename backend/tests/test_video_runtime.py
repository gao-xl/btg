"""CameraRuntime 与视频/急停/健康/模块运维端点的单元测试。"""
from __future__ import annotations

import pytest

from btg.video import CameraDef, CameraRuntime


def test_camera_def_defaults():
    cam = CameraDef(name="cam0")
    assert cam.source_type == "usb"
    assert cam.usb_index == 0
    assert cam.algorithm_mode == "classical_motion"
    assert cam.auto_start is False


def test_invalid_source_type_rejected():
    with pytest.raises(Exception):
        CameraDef(name="cam0", source_type="webrtc")


def test_add_get_remove(tmp_path):
    runtime = CameraRuntime(config_path=tmp_path / "cameras.yaml")
    runtime.add_camera(CameraDef(name="front", source_type="rtsp", rtsp_url="rtsp://x"))
    cam = runtime.get("front")
    assert cam is not None and cam.rtsp_url == "rtsp://x"
    assert runtime.remove_camera("front") is True
    assert runtime.get("front") is None


def test_add_persists_to_disk(tmp_path):
    path = tmp_path / "cameras.yaml"
    CameraRuntime(config_path=path).add_camera(CameraDef(name="a", usb_index=1))
    runtime = CameraRuntime(config_path=path)
    assert runtime.get("a") is not None
    assert runtime.get("a").usb_index == 1


def test_state_of_stopped_when_undefined(tmp_path):
    runtime = CameraRuntime(config_path=tmp_path / "cameras.yaml")
    assert runtime.state_of("nope")["state"] == "stopped"


def test_start_unknown_raises_keyerror(tmp_path):
    runtime = CameraRuntime(config_path=tmp_path / "cameras.yaml")
    with pytest.raises(KeyError):
        import asyncio
        asyncio.get_event_loop().run_until_complete(runtime.start("missing"))