"""剧情导入器：把"自然语言剧情"转换为可执行的结构化 :class:`Story`。

两条导入轨道（可插拔）：

- :class:`RuleBasedStoryImporter`（默认，离线）：解析一套轻量的剧本标记 DSL，
  无需任何密钥即可把一段剧本文本转成场景脚本；
- :class:`LLMStoryImporter`（可选）：把自由文本交给 OpenAI 兼容 LLM，返回严格
  JSON 形式的剧情草稿，再经 :class:`Story` 统一校验，规避模型幻觉结构。

统一入口 :func:`make_importer` 依据 ``BTG_STORY_LLM_PROVIDER`` 环境变量选择，
缺省回退到规则解析，保证拿来即用。
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Protocol

from .models import Story, StoryActuatorCommand, StoryScene, StoryTimeout, StoryTransition

# --------------------------------------------------------------------------- #
# 剧本标记 DSL
# --------------------------------------------------------------------------- #
#   # 标题：卧室里的午夜
#   ## 第一章：相遇
#   - intro
#     > 旁白：夜色低垂，房间里只剩暖黄的光
#     > 台词(A)：你还醒着吗
#     = telemetry heart_rate_bpm gte 120 -> climax
#   - climax
#     > 台词(B)：我们继续
#     > 执行 A=30
#     >> 超时 30 -> end
# --------------------------------------------------------------------------- #

_TRANSITION_OPERATORS = frozenset({"equals", "contains", "gt", "gte", "lt", "lte"})


class StoryImporter(Protocol):
    """自然语言剧情 -> 结构化 :class:`Story`。"""

    async def import_story(self, text: str, *, story_id: str, title: str | None = None) -> Story: ...


class StoryImportError(ValueError):
    """当剧本文本无法被解析为合法剧情结构时抛出。"""


class RuleBasedStoryImporter:
    """基于剧本标记 DSL 的默认离线导入器。

    支持行：

    - ``# 标题：...``         剧情标题（可选）;
    - ``## 章节``             开启新章节;
    - ``- <scene_id>``       开启一个场景节点;
    - ``> 旁白：文本``        设置场景旁白（tts）;
    - ``> 台词(<通道>)：文本`` 设置带通道标注的台词（tts）;
    - ``> 执行 <通道>=<值>``  追加一条执行器指令;
    - ``= <event> <field> <op> <value> -> <target>`` 分支转移;
    - ``>> 超时 <秒> -> <target>``                    超时转移。

    第一个场景为 ``start_scene``，或用 ``@start <scene_id>`` 显式指定。
    """

    def __init__(self, *, default_operator: str = "equals") -> None:
        self._default_operator = default_operator

    async def import_story(self, text: str, *, story_id: str, title: str | None = None) -> Story:
        try:
            return self.parse(text, story_id=story_id, title=title)
        except StoryImportError:
            raise
        except Exception as exc:  # noqa: BLE001 - 统一折叠为导入错误
            raise StoryImportError(f"cannot import story: {exc}") from exc

    # ---- 公开解析（可被 CLI / 测试直接调用） ---------------------------------- #
    def parse(self, text: str, *, story_id: str, title: str | None = None) -> Story:
        scenes: dict[str, StoryScene] = {}
        chapters: list[str] = []
        start_scene: str | None = None
        current_chapter = "未分组"
        current: StoryScene | None = None
        resolved_title: str | None = title

        per_chapter_order: list[tuple[str, str]] = []  # (chapter, scene_id) 保序
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("##"):
                current_chapter = line.lstrip("#").lstrip().strip() or "未分组"
                current = None
                continue
            if line.startswith("#"):
                candidate = line.lstrip("#").lstrip().strip()
                if candidate.startswith("标题"):
                    candidate = candidate[len("标题"):].lstrip("：:").strip()
                resolved_title = candidate or resolved_title
                continue
            if line.startswith("@start"):
                marker = line[len("@start"):].strip()
                if marker not in scenes:
                    current = self._new_scene(marker, current_chapter, scenes, per_chapter_order)
                else:
                    current = scenes[marker]
                start_scene = marker
                continue
            if line.startswith("-"):
                scene_id = line.lstrip("-").lstrip().strip()
                current = self._new_scene(scene_id, current_chapter, scenes, per_chapter_order)
                if start_scene is None:
                    start_scene = scene_id
                continue

            if current is None:
                raise StoryImportError(f"content before any scene: {line!r}")
            self._consume_content_line(current, line)

        if not scenes:
            raise StoryImportError("story must contain at least one scene")
        if start_scene is None or start_scene not in scenes:
            raise StoryImportError("story has no valid start_scene")

        ordered_chapters: list[str] = []
        for chapter, _ in per_chapter_order:
            if chapter not in ordered_chapters:
                ordered_chapters.append(chapter)
        for scene in scenes.values():
            if scene.chapter not in ordered_chapters:
                ordered_chapters.append(scene.chapter)

        return Story(
            id=story_id,
            title=resolved_title or story_id,
            description="",
            chapters=ordered_chapters,
            start_scene=start_scene,
            scenes=scenes,
        )

    # ---- 内部装配 ------------------------------------------------------------ #
    @staticmethod
    def _new_scene(scene_id: str, chapter: str, scenes: dict, order: list) -> StoryScene:
        if not scene_id:
            raise StoryImportError("scene id must be non-empty")
        if scene_id in scenes:
            raise StoryImportError(f"duplicate scene id: {scene_id}")
        scene = StoryScene(id=scene_id, chapter=chapter)
        scenes[scene_id] = scene
        order.append((chapter, scene_id))
        return scene

    def _consume_content_line(self, scene: StoryScene, line: str) -> None:
        if line.startswith(">>"):
            self._consume_timeout(scene, line.lstrip(">").strip())
        elif line.startswith(">"):
            self._consume_stage_line(scene, line.lstrip(">").strip())
        elif line.startswith("="):
            self._consume_transition(scene, line.lstrip("=").strip())
        else:
            scene.actor_text = (scene.actor_text + "\n" + line) if scene.actor_text else line

    def _consume_stage_line(self, scene: StoryScene, body: str) -> None:
        if body.startswith("旁白"):
            scene.tts_text = self._strip_label(body, "旁白")
            return
        if body.startswith("台词"):
            channel, text = self._parse_dialogue(body)
            scene.tts_text = text
            if channel is not None:
                scene.actor_text = f"{channel} 通道：{text}"
            return
        if body.startswith("执行"):
            self._consume_execute(scene, body)
            return
        # 未知舞台行并入旁白
        scene.tts_text = (scene.tts_text or "") + (body if not scene.tts_text else "\n" + body)

    @staticmethod
    def _strip_label(body: str, label: str) -> str:
        return body[len(label):].lstrip("：:").strip()

    @staticmethod
    def _parse_dialogue(body: str) -> tuple[str | None, str]:
        rest = body[len("台词"):].strip()
        channel: str | None = None
        if rest.startswith("("):
            end = rest.find(")")
            if end != -1:
                channel = rest[1:end].strip() or None
                rest = rest[end + 1:].lstrip("：:").strip()
        else:
            rest = rest.lstrip("：:").strip()
        return channel, rest or "……"

    def _consume_execute(self, scene: StoryScene, body: str) -> None:
        rest = body[len("执行"):].strip().lstrip("：:")
        if "=" not in rest:
            raise StoryImportError(f"execute line must be <channel>=<value>: {body!r}")
        channel, _, value_part = rest.partition("=")
        value_part = value_part.strip()
        unit = ""
        if "@" in value_part:
            value_part, _, unit = value_part.partition("@")
        try:
            value = float(value_part)
        except ValueError as exc:
            raise StoryImportError(f"execute value must be numeric: {body!r}") from exc
        if channel.strip() not in {"A", "B", "AB"}:
            raise StoryImportError(f"execute channel must be A/B/AB: {body!r}")
        scene.actuator_cmds.append(
            StoryActuatorCommand(channel=channel.strip(), value=value, unit=unit.strip(), actuator_id=None)
        )

    def _consume_transition(self, scene: StoryScene, body: str) -> None:
        if "->" not in body:
            raise StoryImportError(f"transition must contain -> target: {body!r}")
        clause, _, target = body.partition("->")
        tokens = clause.strip().split()
        if len(tokens) < 2:
            raise StoryImportError(f"transition too short: {body!r}")
        event_type = tokens[0]
        field = tokens[1]
        operator = self._default_operator
        value: Any = None
        if len(tokens) >= 3:
            candidate = tokens[2]
            if candidate in _TRANSITION_OPERATORS:
                operator = candidate
                value_tokens = tokens[3:]
            else:
                value_tokens = tokens[2:]
            value = self._coerce_value(" ".join(value_tokens))
        if event_type not in {"telemetry", "stt"}:
            raise StoryImportError(f"unsupported event_type: {event_type}")
        scene.transitions.append(
            StoryTransition(next=target.strip(), event_type=event_type, field=field, operator=operator, value=value)
        )

    def _consume_timeout(self, scene: StoryScene, body: str) -> None:
        body = body.lstrip("超时").strip()
        if "->" not in body:
            raise StoryImportError(f"timeout line must contain -> target: {body!r}")
        seconds_part, _, target = body.partition("->")
        try:
            seconds = float(seconds_part.strip())
        except ValueError as exc:
            raise StoryImportError(f"timeout seconds must be numeric: {body!r}") from exc
        scene.timeout = StoryTimeout(seconds=seconds, next=target.strip())

    @staticmethod
    def _coerce_value(text: str) -> Any:
        text = text.strip()
        lowered = text.lower()
        if lowered in {"true", "yes"}:
            return True
        if lowered in {"false", "no"}:
            return False
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return text


class LLMStoryImporter:
    """把自由剧情文本交给 LLM 产出严格 JSON 剧情草稿，再统一校验。"""

    SYSTEM_PROMPT = (
        "You convert a human-written narrative script into a strict BTG Story JSON document. "
        "Return ONLY one JSON object matching this exact schema:\n"
        '{"id": string, "title": string, "description": string, '
        '"scenes": { "<sceneId>": { "id", "chapter", "tts_text": string|null, '
        '"actuator_cmds": [{"channel":"A"|"B"|"AB","value":number,"unit":string}], '
        '"transitions": [{"event_type":"telemetry"|"stt","field":string,"operator":'
        '"equals"|"contains"|"gt"|"gte"|"lt"|"lte","value":number|string|bool,"next":string}], '
        '"timeout": {"seconds":number,"next":string}|null } }, '
        '"start_scene": string, "chapters": [string] }\n'
        'Use scene ids like "scene_1". Every transition "next" and start_scene must reference '
        'an existing scene id, or use "__end__" to finish the story. Actuator values are never '
        'increased without an accompanying narrative cause.'
    )

    def __init__(self, transport: "LLMTransport") -> None:
        self._transport = transport

    async def import_story(self, text: str, *, story_id: str, title: str | None = None) -> Story:
        raw = await self._transport.complete(self.SYSTEM_PROMPT, text)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StoryImportError("LLM returned non-JSON story draft") from exc
        if not isinstance(data, dict):
            raise StoryImportError("LLM story draft must be a JSON object")
        data.setdefault("id", story_id)
        data.setdefault("title", title or story_id)
        if "chapters" not in data:
            data["chapters"] = list(dict.fromkeys(s.get("chapter", "未分组") for s in data.get("scenes", {}).values()))
        try:
            return Story.model_validate(data)
        except Exception as exc:  # noqa: BLE001 - 模型校验失败折叠为导入错误
            raise StoryImportError(f"LLM story draft failed validation: {exc}") from exc


class LLMTransport(Protocol):
    """可注入的 LLM 会话调用（解耦具体厂商）。"""

    async def complete(self, system_prompt: str, user_text: str) -> str: ...


class MockLLMTransport:
    """离线 LLM 传输：固定返回一个最小合法剧情（测试 / 无密钥兜底）。"""

    def __init__(self, draft: str | None = None) -> None:
        self._draft = draft or json.dumps(
            {"title": "Mock Story",
             "start_scene": "scene_1",
             "chapters": ["第一章"],
             "scenes": {"scene_1": {"id": "scene_1", "chapter": "第一章", "tts_text": "hello"}}}
        )

    async def complete(self, system_prompt: str, user_text: str) -> str:
        return self._draft


class OpenAICompatLLMTransport:
    """OpenAI 兼容 ``/v1/chat/completions`` 的异步传输（stdlib HTTP）。"""

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        from urllib.request import Request, urlopen

        self._url = f"{base_url.rstrip('/')}/v1/chat/completions"
        self._api_key = api_key
        self._model = model
        self._urlopen = urlopen
        self._Request = Request

    async def complete(self, system_prompt: str, user_text: str) -> str:
        payload = {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        request = self._Request(
            self._url, body,
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = await asyncio.to_thread(self._urlopen, request, timeout=20)
            data = json.loads(response.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, OSError) as exc:
            raise StoryImportError("LLM request failed") from exc


def make_importer(env: dict[str, str] | None = None) -> StoryImporter:
    """按环境变量构造导入器；缺省回退到规则解析（离线可用）。"""
    env = env if env is not None else os.environ
    provider = env.get("BTG_STORY_LLM_PROVIDER", "rule").strip().lower()
    if provider == "openai":
        key = env.get("OPENAI_API_KEY")
        if not key:
            # 未配置密钥时安全回退到规则解析，避免导入流程因网络依赖中断。
            return RuleBasedStoryImporter()
        return LLMStoryImporter(
            OpenAICompatLLMTransport(
                base_url=env.get("OPENAI_BASE_URL", "https://api.openai.com"),
                api_key=key,
                model=env.get("BTG_STORY_LLM_MODEL", "gpt-4.1-mini"),
            )
        )
    if provider == "mock":
        return LLMStoryImporter(MockLLMTransport())
    return RuleBasedStoryImporter()


def make_importer_from_settings(ai: Any) -> StoryImporter:
    """按配置中心的 ``AISettings`` 构造剧情导入器（设置页热配置）。

    与 :func:`make_importer` 的区别：凭据与模型来自 ``settings.yaml`` 的 ``ai``
    而非环境变量，便于通过 Web 设置页统一配置 AI。未配置密钥时安全回退规则解析。
    """
    provider = getattr(ai, "provider", None) or (ai.get("provider") if isinstance(ai, dict) else None) or "mock"
    key = getattr(ai, "api_key", None) or (ai.get("api_key") if isinstance(ai, dict) else None) or ""
    base_url = getattr(ai, "base_url", None) or (ai.get("base_url") if isinstance(ai, dict) else None) or ""
    model = getattr(ai, "model", None) or (ai.get("model") if isinstance(ai, dict) else None) or ""
    if provider == "openai" and key:
        return LLMStoryImporter(
            OpenAICompatLLMTransport(
                base_url=base_url or "https://api.openai.com",
                api_key=key,
                model=model or "gpt-4.1-mini",
            )
        )
    if provider == "mock":
        return LLMStoryImporter(MockLLMTransport())
    return RuleBasedStoryImporter()


__all__ = [
    "StoryImporter",
    "StoryImportError",
    "RuleBasedStoryImporter",
    "LLMStoryImporter",
    "LLMTransport",
    "MockLLMTransport",
    "OpenAICompatLLMTransport",
    "make_importer",
    "make_importer_from_settings",
]