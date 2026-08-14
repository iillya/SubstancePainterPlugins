# Substance 3D Painter工具

为 Substance 3D Painter 提供两个工具：属性面板图层工具与映射校准助手。

## 安装

将 `Releases` 发布包解压到：

```text
C:\Users\<用户名>\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\
```

重启 Painter 后，菜单栏出现“SP工具”入口。

## 功能

### 属性面板图层工具

在“属性”面板中注入逐通道的混合模式与不透明度控件，适用于填充图层、绘画图层、文件夹、滤镜与生成器。菜单、弹窗与通道顺序均与图层面板原生一致；切换图层或修改数值时自动同步，也可在“SP工具”窗口中随时关闭。

> 依赖官方 `sp.layerstack` 接口，自 Painter 10.0 起可用；7.x–9.x 自动禁用。

### 映射校准助手

根据当前工具与 3D/2D 视图，自动切换“校准”与“间距大小”预设。可在“SP工具”窗口中选择受影响的工具组、设置 3D/2D 预设，并一键开关自动校准。

## 兼容性

- Windows 10 / 11（64 位）。
- Painter 7.2–10.0（Qt5 / PySide2），10.1+（Qt6 / PySide6）。
- 图层工具需 Painter 10.0+；7.x–9.x 仅映射校准助手可用。

## 编译（可选）

需要 Windows x64、CMake 与 MSVC（Visual Studio 2022 Build Tools），Qt SDK 位于 `sp_tools\sdks\qt\`。在插件根目录执行：

```text
python source/cpp/build_package.py
```

产物为 `sp_layer_tools_delegate_qt5.dll` 与 `sp_layer_tools_delegate_qt6.dll`，需放入 `native/`。

## 安全说明

插件只修改图层的显示参数，不修改项目数据文件；数值写入走官方接口，可正常撤销。

## 作者与仓库

由 [bilibili 神说要凑数](https://space.bilibili.com/281243426) 制作，源码见 [GitHub：iillya/sp_tools](https://github.com/iillya/sp_tools)。
