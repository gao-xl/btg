# Scenario Agent

独立的 YAML 剧本调度进程。它通过网关，而非直接控制硬件：网关必须继续负责认证、控制会话/同意状态、数值截断、审计与急停。

安装依赖后，以模块方式运行：

```powershell
python -m pip install -r agents/scenario_agent/requirements.txt
$env:BTG_AGENT_TOKEN = "..."
$env:BTG_CONTROL_SESSION_ID = "..."
python -m agents.scenario_agent.main agents/scenario_agent/examples/heart_rate_voice.yaml
```

网关遥测 WebSocket 应发送扁平化 JSON，例如 `{"type":"telemetry","heart_rate_bpm":123}`；STT 事件为 `{"type":"stt","text":"继续"}`。任一 `stop`、`pause` 或 `emergency_stop` 事件都会停止场景转移。`tts.request` 与 `scenario.*` 事件会发送到发布 WebSocket，供前端或 Voice Agent 消费。

`wait_condition` 仅支持 `equals`、`contains`、`gt`、`gte`、`lt`、`lte`，避免在 YAML 中执行表达式或代码。详见 [示例剧本](examples/heart_rate_voice.yaml)。
