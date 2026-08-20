"""剧情注册中心：导入、存管与选取已导入的剧情。"""
from __future__ import annotations

import re
from typing import Callable

from .importers import StoryImporter, make_importer
from .models import Story


class StoryServiceError(ValueError):
    """剧情注册中心的预期业务错误。"""


def slugify(text: str) -> str:
    """把标题转成安全的剧情 id（仅 ``[a-z0-9_-]``）。"""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", text)
    slug = re.sub(r"-{2,}", "-", slug).strip("-_").lower()
    return slug[:60]


class StoryService:
    """内存版剧情注册中心（单机网关运行期存管）。

    ``import_story`` 走可插拔的 :class:`StoryImporter`（默认规则解析），并将
    解析结果注册进内存仓储。运行通过返回后的 :class:`Story` 交给
    :mod:`btg.story.engine` / CLI 消费。
    """

    def __init__(
        self,
        importer: StoryImporter | None = None,
        *,
        max_stories: int = 512,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._importer = importer or make_importer()
        self._stories: dict[str, Story] = {}
        self._max_stories = max_stories
        self._monotonic = 0

    async def import_story(self, text: str, *, story_id: str | None = None, title: str | None = None) -> Story:
        """将一段剧本文本导入并注册为剧情。"""
        if len(self._stories) >= self._max_stories:
            raise StoryServiceError("too many imported stories")
        resolved_id = story_id or (slugify(title) if title else None) or self._next_id()
        if resolved_id in self._stories:
            raise StoryServiceError(f"story already exists: {resolved_id}")
        story = await self._importer.import_story(text, story_id=resolved_id, title=title)
        self._stories[resolved_id] = story
        return story

    def list(self) -> list[dict]:
        """返回全部剧情的轻量元数据（保插入序）。"""
        return [story.metadata_digest() for story in self._stories.values()]

    def get(self, story_id: str) -> Story:
        try:
            return self._stories[story_id]
        except KeyError as exc:
            raise StoryServiceError(f"story not found: {story_id}") from exc

    async def delete(self, story_id: str) -> None:
        if story_id not in self._stories:
            raise StoryServiceError(f"story not found: {story_id}")
        del self._stories[story_id]

    def __len__(self) -> int:
        return len(self._stories)

    def count(self) -> int:
        return len(self._stories)

    def _next_id(self) -> str:
        self._monotonic += 1
        return f"story_{self._monotonic}"


__all__ = ["StoryService", "StoryServiceError", "slugify"]