"""剧情（Story）数据模型：章节化场景图 + 跨章分支转移。

与 scenario_agent 的扁平场景不同，剧情支持：
- 章节（``chapters``）将场景归组，用于叙事推进与进度展示；
- 每个场景可有多个分支转移（``transitions``），按事件逐条匹配，
  命中即跳转到目标场景（可跨章节）或 ``__end__``。

模型全部字段严格校验（``extra="forbid"``），供 REST 输入与可选的
LLM 返鞘做统一校验，任何不合法结构都在导入阶段被拒绝。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: 指向剧情终点的特殊目标场景 id。
END = "__end__"

#: 转移规则支持的比较运算符。
STORY_OPERATORS = frozenset({"equals", "contains", "gt", "gte", "lt", "lte"})

Channel = Literal["A", "B", "AB"]
EventType = Literal["telemetry", "stt"]


class StoryActuatorCommand(BaseModel):
    """剧情中一条要对执行器执行的非破坏性指令。"""

    model_config = ConfigDict(extra="forbid")

    channel: Channel
    value: float
    unit: str = Field(default="", max_length=32)
    actuator_id: str | None = Field(default=None, max_length=64)


class StoryTransition(BaseModel):
    """一个场景的分支转移规则。

    事件先经 ``event_type``、``field``、``operator``、``value`` 判定是否命中，
    命中则 ``target`` 成为下一场景。``target`` 可指向任一既有场景（跨章节）
    或 ``END``。
    """

    model_config = ConfigDict(extra="forbid")

    event_type: EventType = "telemetry"
    field: str = Field(min_length=1, max_length=64)
    operator: str = Field(default="equals", max_length=8)
    value: Any = None
    target: str = Field(alias="next")

    @model_validator(mode="after")
    def _check_operator(self) -> "StoryTransition":
        if self.operator not in STORY_OPERATORS:
            raise ValueError(f"unsupported operator: {self.operator}")
        return self


class StoryTimeout(BaseModel):
    """场景等待超时转移；超时后走向 ``target``。"""

    model_config = ConfigDict(extra="forbid")

    seconds: float = Field(gt=0.0)
    target: str = Field(alias="next")


class StoryScene(BaseModel):
    """一个剧情场景节点：台词/旁白 + 执行指令 + 分支（及超时）。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    chapter: str = "未分组"
    tts_text: str | None = Field(default=None, max_length=2000)
    actor_text: str | None = Field(default=None, max_length=2000)
    actuator_cmds: list[StoryActuatorCommand] = Field(default_factory=list)
    transitions: list[StoryTransition] = Field(default_factory=list)
    timeout: StoryTimeout | None = None


class Story(BaseModel):
    """一部完整剧情的只读契约。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    chapters: list[str] = Field(default_factory=list)
    start_scene: str = Field(min_length=1, max_length=64)
    scenes: dict[str, StoryScene]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_graph(self) -> "Story":
        if self.start_scene not in self.scenes:
            raise ValueError("start_scene must name an existing scene")
        for scene in self.scenes.values():
            for transition in scene.transitions:
                if transition.target != END and transition.target not in self.scenes:
                    raise ValueError(f"scene {scene.id} references unknown target {transition.target}")
            if scene.timeout is not None and scene.timeout.target != END and scene.timeout.target not in self.scenes:
                raise ValueError(f"scene {scene.id} timeout references unknown target {scene.timeout.target}")
        return self

    def metadata_digest(self) -> dict[str, Any]:
        """供列表/健康检查使用的轻量元数据。"""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "chapters": list(self.chapters),
            "start_scene": self.start_scene,
            "scene_count": len(self.scenes),
        }