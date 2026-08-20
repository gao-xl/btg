"""剧情导入与执行模块。

提供把"自然语言剧情"转成可执行场景脚本的导入能力，并配以独立的
章节化剧情执行引擎。对外只暴露三个稳定句柄：

- :class:`btg.story.importers.StoryImporter`：导入轨道（规则解析 / LLM）;
- :class:`btg.story.models.Story`：结构化剧情契约;
- :class:`btg.story.engine.StoryEngine`：独立执行状态机。
"""
from __future__ import annotations

from .engine import ActuatorWriter, EventSink, EventSource, StoryEngine, StoryState
from .importers import (
    LLMStoryImporter,
    LLMTransport,
    MockLLMTransport,
    OpenAICompatLLMTransport,
    RuleBasedStoryImporter,
    StoryImportError,
    StoryImporter,
    make_importer,
)
from .models import END, Channel, Story, StoryActuatorCommand, StoryScene, StoryTimeout, StoryTransition
from .service import StoryService, StoryServiceError, slugify

__all__ = [
    "Story",
    "StoryScene",
    "StoryTransition",
    "StoryTimeout",
    "StoryActuatorCommand",
    "Channel",
    "END",
    "StoryImporter",
    "StoryImportError",
    "RuleBasedStoryImporter",
    "LLMStoryImporter",
    "LLMTransport",
    "MockLLMTransport",
    "OpenAICompatLLMTransport",
    "make_importer",
    "StoryEngine",
    "StoryState",
    "ActuatorWriter",
    "EventSource",
    "EventSink",
    "StoryService",
    "StoryServiceError",
    "slugify",
]