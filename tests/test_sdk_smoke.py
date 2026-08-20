"""SDK 冒烟测试：验证包可导入、注册装饰器与钩子可用。

独立运行：``python tests/test_sdk_smoke.py``
pytest 运行：``pytest tests/``
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))


def test_import_and_register() -> None:
    import btg_sdk
    from btg_sdk import BaseSensor, get_sensor_class, register_sensor

    assert btg_sdk.__version__ == "0.1.0"

    @register_sensor("smoke_hr")
    class _DemoSensor(BaseSensor):
        pass

    assert get_sensor_class("smoke_hr") is _DemoSensor


def test_duplicate_registration_raises() -> None:
    import pytest
    from btg_sdk import BaseSensor, register_sensor

    @register_sensor("smoke_dup")
    class _A(BaseSensor):
        pass

    with pytest.raises(ValueError):

        @register_sensor("smoke_dup")
        class _B(BaseSensor):
            pass


def test_hooks() -> None:
    from btg_sdk import hook

    hook.clear_hooks()

    @hook.on_telemetry_received
    async def _clean(reading):  # noqa: ANN001, ANN201
        return None

    assert len(hook.get_hooks("telemetry_received")) == 1


if __name__ == "__main__":
    test_import_and_register()
    try:
        test_duplicate_registration_raises()
    except ImportError:
        print("pytest 未安装，跳过重复注册用例")
    test_hooks()
    print("smoke ok")