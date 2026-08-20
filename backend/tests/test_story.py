"""剧情（Story）导入、模型校验与独立引擎的测试。"""
from __future__ import annotations

import asyncio

import pytest

from btg.platform.context import PlatformContext
from btg.platform.kernel import Kernel
from btg.story.engine import StoryEngine, StoryState
from btg.story.importers import (
    LLMStoryImporter,
    MockLLMTransport,
    RuleBasedStoryImporter,
    StoryImportError,
    make_importer,
)
from btg.story.models import Story
from btg.story.runtime import scripted_source
from btg.story.service import StoryService, StoryServiceError

SIMPLE = """\
# 标题：客厅初体验
## 第一章：开场
- greet
  > 旁白：今晚的暖光正好
  > 台词(A)：要一起么
  = stt text contains 好 -> next_step
  >> 超时 30 -> end
- next_step
  > 执行 B=15
  = telemetry heart_rate_bpm gte 120 -> end
- end
  > 旁白：收尾，晚安
"""


def _parse(text: str = SIMPLE, **kwargs) -> Story:
    return RuleBasedStoryImporter().parse(text, story_id=kwargs.get("story_id", "t"))

# --------------------------------------------------------------------------- #
# 数据模型校验
# --------------------------------------------------------------------------- #


class TestStoryModel:
    def test_rejects_unknown_fields(self):
        with pytest.raises(Exception):
            Story.model_validate({"id": "x", "title": "t", "start_scene": "a", "scenes": {"a": {"id": "a", "extra": 1}}})

    def test_start_scene_must_exist(self):
        with pytest.raises(Exception):
            Story.model_validate(
                {"id": "x", "title": "t", "start_scene": "missing", "scenes": {"a": {"id": "a"}}}
            )

    def test_rejects_unknown_transition_target(self):
        with pytest.raises(Exception):
            Story.model_validate(
                {"id": "x", "title": "t", "start_scene": "a",
                 "scenes": {"a": {"id": "a", "transitions": [{"next": "ghost", "field": "x"}]}}}
            )

    def test_metadata_digest(self):
        story = _parse()
        meta = story.metadata_digest()
        assert meta["id"] == "t" and meta["scene_count"] == 3

    def test_valid_reference_to_end(self):
        story = Story.model_validate(
            {"id": "x", "title": "t", "start_scene": "a",
             "scenes": {"a": {"id": "a", "transitions": [{"next": "__end__", "field": "x"}]}}}
        )
        assert story.start_scene == "a"

# --------------------------------------------------------------------------- #
# 规则导入器
# --------------------------------------------------------------------------- #


class TestRuleBasedImporter:
    def test_parse_structure(self):
        story = _parse()
        assert story.title == "客厅初体验"
        assert story.start_scene == "greet"
        assert story.chapters == ["第一章：开场"]
        assert list(story.scenes) == ["greet", "next_step", "end"]
        assert story.scenes["greet"].tts_text == "要一起么"
        assert story.scenes["greet"].transitions[0].value == "好"

    def test_execute_command(self):
        story = _parse()
        cmd = story.scenes["next_step"].actuator_cmds[0]
        assert cmd.model_dump() == {"channel": "B", "value": 15.0, "unit": "", "actuator_id": None}

    def test_execute_with_unit(self):
        text = "# t\n- a\n  > 执行 A=10@%s\n" % "%"
        story = _parse(text)
        assert story.scenes["a"].actuator_cmds[0].unit == "%"

    def test_timeout(self):
        story = _parse()
        to = story.scenes["greet"].timeout
        assert to.seconds == 30 and to.target == "end"

    def test_duplicate_scene_raises(self):
        with pytest.raises(StoryImportError):
            _parse("# t\n- a\n- a\n")

    def test_no_scenes_raises(self):
        with pytest.raises(StoryImportError):
            _parse("no scenes here")

    def test_bad_channel_raises(self):
        with pytest.raises(StoryImportError):
            _parse("# t\n- a\n  > 执行 C=10\n")

    def test_explicit_start_marker(self):
        story = _parse("# t\n- x\n- y\n@start y\n")
        assert story.start_scene == "y"

    def test_running_bound_pattern(self):
        # 无出口的单场景（`- a` 之后无转移）解析必须合法（终场），不抛错。
        story = _parse("# t\n- a\n")
        assert story.start_scene == "a" and list(story.scenes) == ["a"]

# --------------------------------------------------------------------------- #
# 剧情注册中心
# --------------------------------------------------------------------------- #


class TestStoryService:
    def test_import_and_list(self):
        service = StoryService()
        story = asyncio.run(service.import_story(SIMPLE, story_id="demo", title="客厅初体验"))
        assert story.id == "demo"
        assert service.list()[0]["title"] == "客厅初体验"
        assert service.get("demo").start_scene == "greet"

    def test_duplicate_id_rejected(self):
        service = StoryService()
        asyncio.run(service.import_story(SIMPLE, story_id="demo"))
        with pytest.raises(StoryServiceError):
            asyncio.run(service.import_story(SIMPLE, story_id="demo"))

    def test_delete(self):
        service = StoryService()
        asyncio.run(service.import_story(SIMPLE, story_id="demo"))
        asyncio.run(service.delete("demo"))
        with pytest.raises(StoryServiceError):
            service.get("demo")

    def test_autogen_id_from_title(self):
        service = StoryService()
        story = asyncio.run(service.import_story(SIMPLE, story_id=None, title="深夜Hello_故事"))
        # 中文被归一化为 ascii 安全的 id
        assert story.id == "hello"

    def test_slugify(self):
        from btg.story.service import slugify

        assert slugify("Hello 世界 Test!") == "hello-test"
        assert slugify("###") == ""

# --------------------------------------------------------------------------- #
# LLM 导入器 / 环境选择
# --------------------------------------------------------------------------- #


class TestLLMImporter:
    def test_mock_transport_returns_valid_story(self):
        importer = LLMStoryImporter(MockLLMTransport())
        story = asyncio.run(importer.import_story("any", story_id="mock"))
        assert story.id == "mock" and story.title

    def test_rejects_non_json(self):
        class Bad:
            async def complete(self, s, u):
                return "not json"

        with pytest.raises(StoryImportError):
            asyncio.run(LLMStoryImporter(Bad()).import_story("x", story_id="x"))

    def test_make_importer_default_rule(self):
        assert isinstance(make_importer({}), RuleBasedStoryImporter)

    def test_make_importer_openai_without_key_falls_back_to_rule(self):
        assert isinstance(make_importer({"BTG_STORY_LLM_PROVIDER": "openai"}), RuleBasedStoryImporter)

    def test_make_importer_mock(self):
        assert isinstance(make_importer({"BTG_STORY_LLM_PROVIDER": "mock"}), LLMStoryImporter)

# --------------------------------------------------------------------------- #
# 独立剧情引擎
# --------------------------------------------------------------------------- #


class FakeWriter:
    def __init__(self):
        self.calls: list[tuple] = []

    async def send_actuator_command(self, command, *, story_id, scene_id):
        self.calls.append((command.channel, command.value, scene_id))


class FakeSink:
    def __init__(self):
        self.events: list[dict] = []

    async def publish(self, event):
        self.events.append(event)


def _engine(path_events, writer=None, sink=None, story=None):
    writer = writer or FakeWriter()
    sink = sink or FakeSink()
    story = story or _parse()
    return StoryEngine(story, writer, scripted_source(path_events), sink), writer, sink


class TestStoryEngine:
    def test_flow_to_terminal_end(self):
        events = [{"type": "stt", "text": "好啊继续"}, {"type": "telemetry", "heart_rate_bpm": 125}]
        engine, writer, sink = _engine(events)
        assert asyncio.run(engine.run()) == StoryState.COMPLETED
        entered = [e["scene_id"] for e in sink.events if e["type"] == "story.scene_entered"]
        assert entered == ["greet", "next_step", "end"]
        # greet 无指令；next_step 下发 B=15
        assert ("B", 15.0, "next_step") in writer.calls

    def test_branch_surpasses_chapter(self):
        text = "# t\n## c1\n- a\n  = telemetry heart_rate_bpm gte 130 -> b\n## c2\n- b\n  > 执行 A=5\n"
        events = [{"type": "telemetry", "heart_rate_bpm": 140}]
        engine, _, sink = _engine(events, story=_parse(text))
        assert asyncio.run(engine.run()) == StoryState.COMPLETED
        assert [e["scene_id"] for e in sink.events if e["type"] == "story.scene_entered"] == ["a", "b"]

    def test_request_stop_aborts(self):
        engine, writer, sink = _engine([{"type": "telemetry", "heart_rate_bpm": 60}])
        engine.request_stop()
        result = asyncio.run(engine.run())
        assert result == StoryState.STOPPED

    def test_stop_event_aborts(self):
        engine, _, _ = _engine([{"type": "stop"}, {"type": "telemetry", "heart_rate_bpm": 999}])
        assert asyncio.run(engine.run()) == StoryState.STOPPED

    def test_engine_runs_only_once(self):
        engine, _, _ = _engine([])
        asyncio.run(engine.run())
        with pytest.raises(RuntimeError):
            asyncio.run(engine.run())

# --------------------------------------------------------------------------- #
# 平台集成
# --------------------------------------------------------------------------- #


class TestPlatformIntegration:
    def test_kernel_discovers_story_module(self):
        kernel = Kernel(PlatformContext()).discover()
        names = [m.name for m in kernel.registry.all()]
        assert "story_engine" in names

    def test_story_module_exposes_service(self):
        kernel = Kernel(PlatformContext()).discover()
        module = kernel.registry.get("extension", "story_engine")
        assert hasattr(module, "service")

    def test_module_health(self):
        import asyncio as _aio

        kernel = Kernel(PlatformContext()).discover()
        module = kernel.registry.get("extension", "story_engine")
        health = _aio.run(module.health())
        assert health["status"] == "ok" and health["stories"] == 0