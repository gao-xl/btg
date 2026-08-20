# BTG — Bio-Telemetry Gateway

基于 ARM 开发板（瑞芯微 / 树莓派等）的**人体状态监控 + IoT 设备调整系统**。

BTG 通过摄像头、麦克风、迈金、小米手环蓝牙广播等多种监控设备识别人体状态，
根据预设模式或第三方 API 控制，动态调整 IoT 设备的运行状态。系统采用
**边缘 + 云端管理后台**架构，预留传感器 / 识别器 / 控制器插件接口，支持第三方二开。

> ⚠️ 本项目为内部使用场景设计，开源协议为 MIT。接入 DG-LAB 郊狼等设备时，
> 请遵守设备厂商协议的非商用条款。

---

## ✨ 核心特性

### 平台内核（Platform Kernel）
- **插件化模块架构**：传感器 / 执行器 / 数据源 / 代理 / 扩展模块统一经 `btg.plugins`
  entry-point 双轨加载（内置包 + 第三方包），支持热插拔与二开。
- **硬件抽象层（HAL）**：逻辑通道配置、冗余路由（主备设备自动故障切换）。
- **安全沙箱（Safety）**：数值截断（Clamp）、看门狗（Watchdog）、分级安全闸（Guardrail）。
- **多模态融合（Fusion）**：聚合高频时间序列，规则引擎触发状态机迁移。
- **事件总线**：进程内异步发布 / 订阅，解耦系统各层。
- **配置中心**：REST API 动态调整核心运行参数并热更新。

### 🛡️ 动态风控与自适应安全边界（Guardrail & Safety Dashboard）
- **软降级**：AI 激进出力或心率达预警线时触发限幅器（×衰减系数），而非直接切断。
- **硬急停**：WebSocket 心跳掉线、心率连续超限或 IMU 剧烈挣扎时，内核绕过上层直接下发硬件归零指令。
- **黑盒审计**：环形缓冲保留最近 1 小时状态帧，每条带时间戳与因果链指针（`原因 ➔ 动作 ➔ 结果`）。

### 🔗 动态设备工作流编排器（Visual Node-Based Automation）
Node-RED 极简版：**触发节点**（心率阈值 / 突变率、视觉痛苦指数、执行器反馈、手动触发）、
**条件节点**（AND / OR / 阈值比较）、**动作节点**（设置通道强度 / 物理位置 / 强制 AI 话术）。
前端拖拽连线导出 JSON，后端图遍历解释器按 Tick（默认 5Hz）实时执行。

### 🎭 动态剧本 / 人格切换器（Persona & Scenario Marketplace）
一个剧本包 = System Prompt + 硬件映射策略（`heart_rate_multiplier` /
`allow_ai_full_control` / `max_allowed_intensity`）。一键切换 AI 人格与硬件策略，
社区工坊支持从远端 API 拉取剧本。

### 🧬 历史心率与惩罚复盘曲线（Timeline & Replay / Session Log）
赛车级 Telemetry 会话回放：同一时间轴渲染**生理指标 / 硬件状态 / AI 动作**三条平行轨道，
支持导出含 SVG 图表 + 完整 JSON 黑盒日志的压缩包。

---

## 🏗️ 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  边缘端（ARM 开发板）                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ 传感器插件     │  │ 识别器插件     │  │ 控制器插件        │   │
│  │ 摄像头/麦克风   │  │ 状态识别/融合   │  │ 执行器/第三方API  │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │ WebSocket / REST
┌──────────────────────────▼──────────────────────────────────┐
│  云端管理后台（BTG Gateway）                                  │
│  Platform Kernel → HAL / Safety / Fusion / Bus / Integration │
│  + Workflow / Persona / Replay / Story 扩展模块              │
└──────────────────────────────────────────────────────────────┘
```

## 📁 目录结构

```
├── backend/                 # BTG 网关后端（FastAPI + 平台内核）
│   └── src/btg/
│       ├── platform/        # 平台内核：manifest / module / registry / loader / kernel
│       ├── hal/             # 硬件抽象层：传感器 / 执行器 / 冗余路由
│       ├── safety/          # 安全层：clamps / watchdog / guardrail / policy
│       ├── fusion/          # 多模态融合引擎
│       ├── bus/             # 总线层：REST 端点 + WebSocket 遥测流
│       ├── integration/     # 第三方接入：inbound / outbound / webhook
│       ├── agents/          # 网关内代理：game / llm_master / scenario
│       ├── story/           # 剧情导入与场景执行引擎
│       ├── workflow/        # 工作流编排器
│       ├── persona/         # 剧本人格市场
│       ├── replay/          # 复盘曲线（会话录制 + 报告导出）
│       └── config/          # 配置中心与热更新引擎
├── sdk/                     # btg_sdk：第三方插件 SDK 核心基类
├── board_agent/             # ARM 板端代理（采集 / 识别 / 控制）
├── frontend/                # Vue 3 + Vite + Tailwind 控制台
├── btg-nexus/               # 备用 Vue 前端
├── bio-telemetry-console/   # 静态 HTML 控制台（设计资产）
├── config/                  # 运行时配置（*.example.yaml 提交，实际配置忽略）
├── docs/                    # 架构文档
└── tests/                   # 全量测试
```

## 🚀 快速开始

### 后端

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -e .[dev]
python -m btg.gateway                            # 启动网关（默认 :8000）
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

开发模式默认把 `/api`、`/integration`、`/ws` 代理到 `http://localhost:8000`。

### 测试

```bash
python -m pytest tests/
```

## 📄 文档

- [架构文档](docs/architecture.md)：平台内核契约、模块开发指南、扩展模块说明。

## 📜 License

[MIT](LICENSE) © BTG Contributors
