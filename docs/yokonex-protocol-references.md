# 役次元协议实现交叉核对

本文件记录用于核对役次元接入的公开实现。它们是协议兼容性参考，不作为可直接信任的硬件安全证明。

## 参考项目

| 项目 | 可核对内容 | 本项目处理 |
| --- | --- | --- |
| [YCY-YOKONEX-OpenSource](https://github.com/YCY-YOKONEX/YCY-YOKONEX-OpenSource) | 厂商 BLE、IM、WebSocket/HTTP 文档 | 作为协议字段的首要来源 |
| [MagicRabbit666/YCY-Control](https://github.com/MagicRabbit666/YCY-Control) | 杯子 2.0 的 FF40/FF41/FF42、三马达帧和电量通知 | 只核对共同帧；不移植随机控制、暂停后自动恢复或受限许可证代码 |
| [DT-DT001/SLK_MOD](https://github.com/DT-DT001/SLK_MOD) | 电击器一/二代、杯子/跳蛋的封包与已知向量自测 | 采用其与厂商文档一致的保守强度上限和测试向量，不复制游戏联动逻辑 |
| [MrLing1202/astrbot_plugin_YCY_YoKonex](https://github.com/MrLing1202/astrbot_plugin_YCY_YoKonex) | WebSocket 强度/波形控制与停止队列语义 | 不接入：该路径允许模型直接改变强度，与 BTG 的安全职责冲突 |
| [julezhou/ycy_control](https://github.com/julezhou/ycy_control) | MIT 许可的电击器、杯子/跳蛋和灌肠机命令生成与解析 | 用于二次核对字段；暂不把扫描、无限重连或实机写入并入 BTG |

## 当前实现状态

- `yokonex_im`：可运行的官方 API-bridge 适配器，仍需使用者在役次元 App 中配置事件和安全阈值。
- `yokonex_packets.py`：纯函数 BLE 编码器，无扫描、无连接、无写入，覆盖电击器一代固定模式、二代固定/实时模式、杯子/跳蛋三马达速率和显式停止帧。
- 灌肠机：暂不加入可执行编码器。官方协议使用 AES，且泵方向、持续时间和压力风险需要独立的设备级状态机、超时与物理停止验收，不能复用单一 0–100 强度通道。
- 真实 BLE 输出：未启用。后续实现必须增加显式上锁/解锁、短租约、断连归零、通知确认、设备身份绑定和实体急停验收。

## 已知分歧

杯子 A 马达的部分实现允许 21–40 表示反转，另一些经过测试的实现仅允许 0–20。当前编码器只接受多个来源一致的 0–20 安全子集；在官方型号和反转行为完成实机确认前不开放 21–40。

电击器协议原始字段可表达高于 180 的值，但当前编码器采用交叉测试实现中的 0–180 上限。最终物理安全上限仍必须由 `safety.yaml` 设置为更低、经设备使用者确认的值。
