# Bio-Telemetry Gateway (BTG) 系统架构白皮书

## 1. 设计哲学 (Design Philosophy)

BTG 是一个专为高危物理操作与生理遥测设计的开源边缘计算网关。本系统严格遵循以下四大设计哲学：

1. **彻底的前后端分离**：后端作为无状态的 API/流媒体服务器运行，前端通过标准协议通信，允许完全替换或自定义前端。
2. **故障安全与底线防御 (Fail-safe)**：内置硬件抽象层的数值截断与无心跳自动归零机制。
3. **高可用冗余 (Redundancy)**：支持传感器与执行器的逻辑分组与自动故障切换（Failover）。
4. **万物皆插件 (Plugin-Oriented)**：核心网关不包含任何特定厂商的硬件代码。所有设备与第三方平台均以统一模块（`Module`）形式通过平台内核发现并热插拔。

---

## 2. 平台内核与模块契约 (Platform Kernel & Module Contract)

在五层数据流之上，BTG 叠加了一个「平台 + 模块化」内核（`backend/src/btg/platform`），
把**核心网关**与**可插拔模块**彻底解耦：核心只依赖本包定义的契约，任何传感器、
执行器、第三方平台或代理都以统一模块形式被内核发现与编排。

### 2.1 模块契约

- **`ModuleManifest`**：模块自描述元数据，字段为 `name` / `version` / `kind` /
  `description` / `capabilities` / `dependencies` / `config_schema`。
- **`Module`** 抽象基类：实现幂等的 `setup()` / `start()` / `stop()` / `health()`
  生命周期，并通过 `PlatformContext` 访问平台能力。
- **`ModuleKind`**：判定模块归属，取值 `sensor` / `actuator` / `provider` /
  `agent` / `extension`。

设备类模块（sensor/actuator/provider）额外继承 `DeviceModule`，在
`plugin_names` 中声明其贡献给 `btg_sdk` 注册表的插件名，`setup()` 时校验
对应 `@register_*` 是否已登记。

### 2.2 双轨加载 (Dual-Track Loading)

内核通过三条轨道发现模块，按 `(kind, name)` 去重：

1. **内置（轨道 1）**：直接 `import btg.modules.sensors/actuators/providers/agents`，
   触发 `@register_module` 登记；
2. **pip 入口点（轨道 2）**：读取 `importlib.metadata` 中 `btg.plugins` 组；
3. **运行时目录（轨道 3）**：扫描 `backend/plugins/` 下每个顶层包，包可用
   `MODULES` 显式导出模块类，否则内核自动扫描包内的 `Module` 子类。

### 2.3 平台上下文 (PlatformContext)

模块只允许经 `PlatformContext` 与平台交互，守「模块间零耦合」边界：

- `event_bus`：进程内异步事件总线；
- `ring_buffer`：遥测环形缓冲；
- `config_manager`：全局配置中心；
- `settings`：网关进程级设置；
- `logger`：可复用日志器。

### 2.4 内核编排 (Kernel)

`Kernel` 是插件平台的唯一装配入口：`discover()` 完成三轨发现与实例化，
`setup() → start() → stop()`（逆序）编排生命周期。`Gateway` 只依赖内核公开的
发现结果，不再硬编码任何插件包路径。已发现模块经 `GET /api/v1/modules` 对外暴露。

---

## 3. 系统五层架构 (The 5-Layer Architecture)

BTG 核心按照数据流向与安全级别划分为五个严格解耦的层级，外加一个独立的第三方集成层。

```text
[ 客户端前端 / Vue3 ] <=== WebSocket / REST ===> [ 第三方平台 (HA/Tuya) ]
          │                                              │
          ▼                                              ▼
=================== 5. 消息总线层 (Bus) & 第三方集成 (Integration) ===================
  - RESTful API (配置/指令)      |  - Inbound (接收第三方指令)
  - WebSocket (>=10Hz 遥测流)    |  - Outbound (Webhook 推送)
====================================================================================
                                │
=================== 4. 多模态融合引擎 (Fusion Engine) ==============================
  - 聚合高频时间序列数据 (心率、IMU、音频 VAD)
  - 状态机计算 (基于规则引擎触发降级或模式切换)
====================================================================================
                                │
=================== 3. 安全沙箱与策略层 (Safety & Policy) ==========================
  - Clamps: 基于 YAML 的硬性数值截断 (如限制最大 PWM 为 50%)
  - Watchdog: 2秒连接超时自动归零 (取代传统的急停大红按钮逻辑)
  - Guardrail: 分级安全闸——软降级限幅 (×衰减系数) + 硬急停归零 (HR/IMU/WS 心跳三重触发)
  - Blackbox: 黑盒审计环形缓冲 (1 小时状态帧 + 因果链指针)
====================================================================================
                                │
=================== 2. 高可用冗余路由 (Redundancy Router) ==========================
  - 逻辑通道抽象 (Logical Channel Mapping)
  - 优先级主备切换 (如：Magene 心率带掉线 <-> 无缝切换至小米手环)
====================================================================================
=================== 1. 硬件抽象与插件层 (HAL & Plugins via SDK) ====================
  - BaseSensor / BaseActuator 抽象接口
  - 动态插件加载器 (Plugin Loader)
====================================================================================
          │                                              │
     [ 传感器组 ]                                   [ 执行器组 ]
```

---

## 4. 高可用冗余设计 (Redundancy & Failover)

系统放弃了传统的"一对一"设备绑定，采用"逻辑通道 (Logical Channel)"设计。

在 `devices.yaml` 中，用户可以为一个逻辑指标分配多个物理设备：

```yaml
channels:
  heart_rate:
    type: sensor
    devices:
      - plugin: "btg_plugin_magene"
        mac: "XX:XX:XX:XX:XX:XX"
        priority: 1   # 主设备
      - plugin: "btg_plugin_miband"
        mac: "YY:YY:YY:YY:YY:YY"
        priority: 2   # 备用设备
```

**故障切换机制**：若 `priority: 1` 的设备掉线或超时，系统底层（HAL Redundancy 层）会自动拉起 `priority: 2` 的设备并注入总线，上层融合引擎与前端完全无感，数据流不会中断。

---

## 5. 第三方开发者扩展指南 (Extensibility)

BTG 提供了极其友好的二开空间，插件可按统一模块契约交付，通过双轨加载（pip
入口点 / `plugins/` 目录）自动接入。

### 5.1 硬件扩展 (基于 btg-sdk)

第三方开发者只需安装轻量级的 SDK（`pip install btg-sdk`），无需 clone 整个网关代码，即可开发设备驱动：

```python
from btg_sdk import BaseSensor, register_sensor

@register_sensor("my_custom_band")
class MyCustomBand(BaseSensor):
    async def connect(self):
        ...

    async def read_stream(self):
        ...
```

再定义一个模块包装，供平台内核发现：

```python
from btg.platform import ModuleKind, ModuleManifest, SensorModule, register_module

@register_module
class MyBandModule(SensorModule):
    manifest = ModuleManifest(
        name="my_custom_band",
        kind=ModuleKind.SENSOR,
        description="示例自定义手环传感器。",
        capabilities=["stream"],
    )
    plugin_names = ["my_custom_band"]
```

将写好的包放入 `plugins/` 目录（或作为独立 Python 包安装并在 `btg.plugins`
入口点组登记），内核运行时加载器将自动发现并挂载。

### 5.2 业务逻辑注入 (Hooks)

SDK 提供了生命周期钩子，允许开发者在不修改核心源码的情况下改变系统行为：

- `@hook.on_telemetry_received`：数据进入融合引擎前清洗。
- `@hook.on_safety_check`：自定义更复杂的安全拦截逻辑。
- `@hook.on_state_change`：状态机状态发生变化时。

### 5.3 外部系统集成 (Integration API)

- **主动控制**：通过 `POST /integration/v1/control` 传入标准 JSON 改变网关运行模式。
- **被动订阅**：提供完善的 Webhook 注册机制，设备状态变化时主动推送至第三方服务器。

---

## 6. 目录结构 (Repository Layout)

```
bio-telemetry-gateway/
├── README.md
├── LICENSE                     # Apache-2.0
├── CONTRIBUTING.md
├── CHANGELOG.md
├── .gitignore  .dockerignore
├── docker-compose.yml          # 编排 backend + frontend（各自独立镜像）
│
├── sdk/                        # 插件 SDK：第三方二开唯一需要依赖的稳定公共接口
│   ├── pyproject.toml          # 包名 btg-sdk，可单独 pip install
│   └── btg_sdk/
│       ├── __init__.py         # 公共 API 出口 + __version__
│       ├── types.py            # Reading / ActuatorCommand 等共享数据类型
│       ├── base.py             # BaseSensor / BaseActuator / ThirdPartyProvider 抽象基类
│       ├── registry.py         # @register_sensor / @register_actuator / @register_provider
│       └── hooks.py            # on_telemetry_received / on_safety_check / on_state_change
│
├── backend/                    # 后端服务（独立，Python/FastAPI，仅经 API 对外）
│   ├── Dockerfile              # 独立镜像，arm64/amd64 多架构
│   ├── pyproject.toml          # 声明 btg.plugins 入口点组，供 pip 插件分发
│   ├── src/btg/
│   │   ├── main.py   settings.py   gateway.py(装配核心)
│   │   ├── platform/           # 平台内核：manifest/module/registry/loader/kernel/context
│   │   ├── modules/            # 内置插件模块：sensors/actuators/providers/agents
│   │   ├── core/               # 事件总线/遥测环形缓冲/黑盒审计/异常/日志
│   │   ├── hal/                # 硬件抽象 + redundancy.py(冗余组/故障切换)
│   │   ├── safety/             # clamps / watchdog / guardrail / policy（故障安全）
│   │   ├── fusion/             # 多模态融合状态机 + 聚合器 + 自适应基线
│   │   ├── bus/                # REST(/api/v1/*) + WebSocket(/ws, /ws/events[.../publish])
│   │   ├── integration/        # 第三方接入：external_api/inbound/outbound/providers
│   │   ├── agents/             # 网关内代理(独立进程)：game / llm_master / scenario
│   │   ├── story/              # 剧情导入与场景执行引擎
│   │   ├── workflow/           # 工作流编排器（Node-RED 极简版）
│   │   ├── persona/            # 剧本人格市场（scenario_manifest 契约 + 社区工坊）
│   │   ├── replay/             # 复盘曲线（会话录制 + 多维时空对齐回放 + 报告导出）
│   │   └── config/             # 配置中心与热更新引擎
│   └── plugins/                # 运行时插件投放目录(双轨加载·目录轨道，自动发现)
│
├── frontend/                   # 前端（独立，Vue3 + Vite + Tailwind + ECharts，仅调 API）
│   ├── Dockerfile
│   ├── package.json  vite.config.ts  tailwind.config.ts
│   └── src/  main.ts App.vue
│       ├── api/                # REST + WS 客户端(含心跳保活)
│       ├── store/              # Pinia
│       ├── components/  ControlSlider / TelemetryChart / DeviceStatus / ModeSelector
│       └── views/ Console.vue
│
├── config/                     # default.yaml / devices.yaml(冗余组) / safety.yaml(阈值)
├── examples/                   # 第三方二开示例：自定义传感器/执行器/provider
├── tests/                      # unit / integration
├── docs/                       # 本白皮书 + API + 插件接入指南
├── .github/workflows/          # 多架构 CI
└── scripts/                    # entrypoint.sh / dev.sh
```

---

## 7. 通信协议与 API 概览

| 通道 | 协议 | 用途 |
|---|---|---|
| 本地控制台 | REST `/api/v1/*` + WebSocket `/ws`（≥10Hz） | 配置、指令、实时遥测 |
| 第三方集成 | REST `/integration/v1/*` | 第三方控制模式 + Webhook 订阅 |
| 设备上云（可选） | MQTT `hms/{device_id}/*` | 多设备遥测/指令（后续阶段） |

所有对外接口版本化，新增字段保持向后兼容。

### 7.1 REST 契约

BTG 的 REST 接口不得使用未版本化路径：控制台和内部控制使用
`/api/v1/*`，第三方集成使用 `/integration/v1/*`。所有成功响应均使用
同一个信封，HTTP 状态码与 `code` 字段保持一致：

```json
{
  "status": "success",
  "code": 200,
  "timestamp": 1787180000.0,
  "data": {}
}
```

所有失败响应使用下列信封；`error.type` 是稳定的程序化错误类别，
`details` 仅用于结构化字段校验信息，不包含服务端堆栈或敏感配置：

```json
{
  "status": "error",
  "code": 422,
  "timestamp": 1787180000.0,
  "error": {
    "type": "validation_error",
    "message": "Request validation failed.",
    "details": []
  }
}
```

服务端路由必须使用 `api.contracts.success()` 返回成功结果，或抛出
`api.contracts.APIError`。FastAPI 应用必须由 `api.app.create_app()` 创建，
以安装请求校验、HTTP 异常和业务异常的统一错误处理器。独立 Agent 必须
在发送前校验 Pydantic 请求模型，并拒绝不符合上述成功信封的网关响应。

### 7.2 动态行为扩展（Behavioral Extensions）

平台以 `extension` 模块形式内置四类「赛博闭环」能力，均由内核发现、经
`/api/v1/*` 暴露，并可用 `PUT /api/v1/features` 独立启停（安全项锁定的除外）。

#### 7.2.1 动态风控与黑盒审计（`safety/` + `core/`）

- **软降级**：AI 激进出力或心率达预警线时，`Guardrail` 触发限幅器（×衰减系数），
  而非直接切断。
- **硬急停**：WebSocket 心跳掉线超时、心率连续超限或 IMU 剧烈挣扎时，内核绕过
  AI/上层，直接下发硬件归零指令。
- **黑盒审计**：`AuditBlackbox` 以环形缓冲保留最近 1 小时状态帧，每条帧带时间戳与
  因果链指针（`parent_id`），可沿链回溯「原因 ➔ 动作 ➔ 结果」。

端点：`GET /api/v1/guardrails`、`POST /api/v1/guardrails/reset`、
`GET /api/v1/blackbox`、`GET /api/v1/blackbox/{frame_id}/chain`。

#### 7.2.2 设备工作流编排器（`workflow/`）

Node-RED 极简版：触发节点（`heart_rate` / `vision_score` /
`actuator_feedback` / `manual_trigger`）、条件节点（`logic_and` / `logic_or` /
`threshold_comparator`）、动作节点（`set_actuator_intensity` /
`set_actuator_position` / `invoke_ai_prompt`）组成有向图。前端拖拽连线后导出精简
JSON，后端 `WorkflowEngine`（图遍历解释器）在每个 Tick（默认 5Hz）求值并执行命中动作。

端点：`GET/POST /api/v1/workflow`、`GET/PUT/DELETE /api/v1/workflow/{id}`、
`POST /api/v1/workflow/{id}/enable`、`POST /api/v1/workflow/{id}/tick`、
`POST /api/v1/workflow/trigger`。

#### 7.2.3 剧本人格市场（`persona/`）

一个剧本包（`scenario_manifest.json`）＝ System Prompt ＋ 硬件映射策略
（`heart_rate_multiplier` / `allow_ai_full_control` / `max_allowed_intensity`）。
`PersonaService` 存管剧本、维护「当前激活剧本」，激活/清除时经回调把硬件策略落到
安全层最高强度上限；社区工坊支持从远端 API 拉取剧本清单。

端点：`GET/POST /api/v1/persona`、`GET /api/v1/persona/workshop`、
`GET /api/v1/persona/active`、`POST /api/v1/persona/{id}/activate`、
`POST /api/v1/persona/deactivate`、`GET/DELETE /api/v1/persona/{id}`。

#### 7.2.4 历史心率与惩罚复盘（`replay/`）

赛车级 Telemetry 会话回放：`ReplayService` 录制「生理指标 / 硬件状态 / AI 动作」
三轨道遥测帧，采集泵自动归类写入活动会话，AI 话术由 `ai.prompt` 事件归档；
`report.py` 生成自包含 SVG 多维时间对齐画布，`/export` 导出含 SVG + 遥测 JSON +
黑盒 JSON 的压缩包。

端点：`POST /api/v1/replay/sessions`、`GET /api/v1/replay/sessions`、
`GET /api/v1/replay/sessions/{id}`、`GET /api/v1/replay/sessions/{id}/series`、
`GET /api/v1/replay/sessions/{id}/svg`、`GET /api/v1/replay/sessions/{id}/export`、
`POST /api/v1/replay/sessions/{id}/end`、`DELETE /api/v1/replay/sessions/{id}`。

---

## 8. 开发路线图

1. **SDK 底座**：定义抽象基类、注册表、钩子与共享类型（本阶段）。
2. **平台内核**：`platform/`（manifest/module/registry/loader/kernel）→ `modules/`（内置模块改造）。
3. **后端核心**：`core/`（事件总线、遥测环形缓冲）→ `hal/`（含冗余路由）→ `safety/`（clamps/watchdog/policy）→ `fusion/` → `bus/` → `integration/`。
4. **前端控制台**：Vue3 控制台（推子、实时图表、模式切换、设备状态）。
5. **真实插件装填**：迈金/小米手环 BLE、摄像头、麦克风、第三方平台适配器（按需逐个落地）。

---

## 9. 开源约定

- 协议：Apache-2.0；依赖全部开源，禁止引入专有运行时。
- 提交：遵循 Conventional Commits；核心接口变更须在 CHANGELOG 标注 Breaking Change。
- 插件契约：`btg-sdk` 采用语义化版本，主版本号变更才允许破坏性改动。