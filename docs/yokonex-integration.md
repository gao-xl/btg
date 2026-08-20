# 役次元（YOKONEX）设备接入

BTG 通过役次元官方 `API-bridge` 的本地 HTTP 接口接入设备。设备配对、连接码登录、事件 ID 与实际波形/强度之间的映射都由役次元 App 和 bridge 管理；BTG 不保存连接码，也不直接实现或猜测厂商蓝牙帧。

此方式可复用役次元 App 中已支持的电击器、跳蛋/飞机杯、灌肠机等设备，但“接口测试通过”不代表具体硬件已经完成安全验收。

## 1. 准备役次元游戏配置

1. 在役次元 App 中创建“开发游戏”。
2. 为每个动作建立事件 ID，例如 `btg_low`、`btg_medium`、`btg_high`。
3. 由设备使用者在 App 中设置每个事件的设备、波形和安全阈值。
4. 保留全局停止事件 `_stop_all`。不要把任一普通事件配置为自动解除急停或提高 App 侧安全上限。

## 2. 启动官方 API-bridge

按照 <https://github.com/YCY-YOKONEX/API-bridge> 启动服务，并在 bridge 内登录连接码。默认地址为 `http://127.0.0.1:3001`。

bridge 的 HTTP API 本身没有认证。BTG 因此默认只接受回环地址。不要把 3001 端口暴露到局域网或公网；确需跨主机时，应先通过受信任、带认证且提供 HTTPS 的隧道保护，再显式设置 `allow_remote_bridge: true`。

## 3. 配置 BTG 通道

在 `config/devices.yaml` 中加入执行器通道。`levels` 使用包含式上界：目标值 30 会选择 `max_value: 50` 对应的事件。必须提供覆盖到 100 的最后一级；目标值 0 始终发送全局停止事件。

```yaml
channels:
  yokonex_output:
    type: actuator
    devices:
      - plugin: yokonex_im
        priority: 1
        config:
          bridge_url: http://127.0.0.1:3001
          timeout_seconds: 5
          stop_command_id: _stop_all
          levels:
            - { max_value: 25, command_id: btg_low }
            - { max_value: 50, command_id: btg_medium }
            - { max_value: 100, command_id: btg_high }
      - plugin: mock_actuator
        priority: 2
```

同时在 `config/safety.yaml` 中给同名通道设置 clamp。这个数值 clamp 只决定选择哪个事件 ID；实际物理输出仍由 App 中对应事件的配置决定，所以 App 侧安全阈值必须独立设置并人工复核。

```yaml
clamps:
  yokonex_output:
    min: 0
    max: 50
    unit: "%"
```

## 4. 失效与停止语义

- 启动时插件检查 `/health`，只有 `status=ok` 且 `imReady=true` 才接管通道。
- HTTP 非成功状态、`success=false` 或网络异常都会使插件标记为断连，现有冗余层随后可切换到备用执行器。
- 目标值 0、看门狗停机、网关关闭和执行器断开都会尝试发送 `_stop_all`。
- `_stop_all` 仍依赖 bridge、腾讯 IM、手机和设备链路。部署前必须另外验证设备本体的物理停止方式；网络停止不能替代实体急停。

## 验收边界

当前自动化测试只模拟 API-bridge 的 HTTP 响应，未登录真实连接码，未连接蓝牙设备，也未验证各型号的输出、延迟、断连行为和实体急停。首次实机测试应使用最低 App 阈值、无负载环境和可立即触达的物理停止路径。

直接 BLE 协议的交叉核对、已知分歧和非执行封包测试见 [yokonex-protocol-references.md](yokonex-protocol-references.md)。这些编码器不会扫描或写入设备，不能视为 BLE 硬件支持已经启用。
