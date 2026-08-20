"""内置独立进程代理模块。

代理在网关外独立进程运行（``python -m btg.agents.*.main``），平台内核仅
登记其 manifest 与入口点，不在网关进程内托管生命周期，故此处不 import
任何重量级代理依赖。
"""
from __future__ import annotations

from btg.platform.manifest import ModuleKind, ModuleManifest
from btg.platform.module import AgentModule, register_module


@register_module
class GameAgentModule(AgentModule):
    """游戏事件代理：追踪游戏日志并映射为 Integration 控制指令。"""

    manifest = ModuleManifest(
        name="game_agent",
        version="0.1.0",
        kind=ModuleKind.AGENT,
        description="追踪游戏事件日志并映射为网关控制指令。",
        capabilities=["event_mapping", "control"],
    )
    entrypoint = "btg.agents.game_agent.main:main"


@register_module
class LlmMasterAgentModule(AgentModule):
    """同意门控的 LLM 主控代理。"""

    manifest = ModuleManifest(
        name="llm_master_agent",
        version="0.1.0",
        kind=ModuleKind.AGENT,
        description="遥测快照 -> LLM 决策 -> 安全包装 -> 网关控制。",
        capabilities=["llm_control", "safety_wrapper"],
    )
    entrypoint = "btg.agents.llm_master_agent.main:main"


@register_module
class ScenarioAgentModule(AgentModule):
    """声明式 YAML 剧本状态机代理。"""

    manifest = ModuleManifest(
        name="scenario_agent",
        version="0.1.0",
        kind=ModuleKind.AGENT,
        description="事件驱动的声明式 YAML 剧本编排代理。",
        capabilities=["scenario_orchestration"],
    )
    entrypoint = "btg.agents.scenario_agent.main:main"