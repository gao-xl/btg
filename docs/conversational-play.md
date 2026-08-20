# 对话玩法层

本模块参考 YoKonex 的会话化玩法、A/B 通道与部位描述、波形目录、随机推荐等交互概念，重新实现为 BTG 内部的设备无关玩法层。没有复制其 AstrBot、役次元 WebSocket、计费或设备协议实现。

## 安全边界

- 玩法会话必须携带已有控制会话引用，并显式确认同意；该引用只用于关联，不能自行创建控制授权。
- AI 指令只允许推荐波形、随机推荐、降强、暂停、停止和清空建议。
- 推荐结果始终返回 `actuated: false`，不会从玩法 API 下发到 HAL。
- 会话只保存在内存中，默认最多 128 个并在 1 小时后过期，避免无界占用。
- 波形按用户为 A/B 通道声明的上限生成预览；预览不是设备命令。
- `reduce` 的目标值高于当前值时直接拒绝。
- 停止玩法会话只清理玩法上下文；物理急停仍使用系统既有急停/安全链路。

## API

- `GET /api/v1/play/waves`：列出 8 个内置、归一化波形。
- `POST /api/v1/play/sessions`：创建带通道、部位和预览上限的玩法会话。
- `GET /api/v1/play/sessions/{id}`：查询玩法会话。
- `POST /api/v1/play/sessions/{id}/decisions`：校验 LLM 对话与玩法建议，返回非执行预览。
- `DELETE /api/v1/play/sessions/{id}`：结束玩法会话。

创建会话示例：

```json
{
  "control_session_id": "existing-authorized-session",
  "consent_confirmed": true,
  "channels": "AB",
  "part_a": "左侧",
  "part_b": "右侧",
  "cap_a": 20,
  "cap_b": 25
}
```

模型建议示例：

```json
{
  "dialogue": "建议试试呼吸节奏。",
  "directive": {
    "action": "recommend_wave",
    "channel": "A",
    "wave": "breathe"
  }
}
```

若后续接入真实设备，必须另行实现“操作者确认 -> 既有控制会话校验 -> SafetyPolicy -> Provider/HAL”的路径；不得把本玩法 API 的预览直接解释成物理指令。
