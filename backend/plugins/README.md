# BTG 运行时插件目录

本目录是插件双轨加载的**第三轨道（目录热插拔）**：内核启动时扫描本目录下的
每个顶层包并自动发现其中的插件模块，无需修改核心代码即可扩展网关能力。

## 加载规则

- 本目录下每个**顶层包**都会被 import。
- 包可通过 `MODULES` 显式声明要注册的模块类（推荐），例如：

  ```python
  # my_plugin/__init__.py
  from btg.platform import Module, ModuleKind, ModuleManifest

  class MyModule(Module):
      manifest = ModuleManifest(
          name="my_module",
          kind=ModuleKind.EXTENSION,
          description="...",
      )

  MODULES = [MyModule]
  ```

- 若未声明 `MODULES`，内核会扫描包内定义的 `Module` 子类。
- 传感器/执行器/第三方平台的设备实现类仍需通过 `btg_sdk` 的
  `@register_sensor` / `@register_actuator` / `@register_provider` 登记，
  并在对应模块的 `plugin_names` 中声明，详见 `src/btg/modules/*`。

## 验证

启动网关后访问 `GET /api/v1/modules`，应能看到本目录下插件模块的
元数据清单。