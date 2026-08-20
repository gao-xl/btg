"""BTG 智能体子包：与网关解耦、可独立进程运行的边缘代理。

- ``game_agent``：追踪游戏事件日志并映射为 Integration 控制指令；
- ``llm_master_agent``：同意门控的 LLM 主控代理（遥测快照 → LLM 决策 → 安全包装）；
- ``scenario_agent``：声明式 YAML 剧本状态机（事件驱动场景编排）。

各代理均为独立进程设计（``python -m btg.agents.<name>.main``），仅通过
网关的 REST / WebSocket 契约通信，不直接触碰硬件。
"""
from btg.agents import game_agent, llm_master_agent, scenario_agent

__all__ = ["game_agent", "llm_master_agent", "scenario_agent"]
