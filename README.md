# sp_tools —— Substance 3D Painter 属性面板图层工具

在 Substance 3D Painter 的“属性”面板中注入“逐通道混合模式与不透明度”控件，实时作用于当前选中的图层、文件夹、滤镜与生成器；同时内置“映射校准助手”，根据当前工具与 3D/2D 视图自动切换对齐与间距大小预设。

## 功能特性

- **逐通道混合模式与不透明度**：填充图层、绘画图层、文件夹、滤镜与生成器均可逐通道显示并调整混合模式与不透明度。
- **原生一致的混合模式菜单**：菜单顺序、分隔线与文字直接克隆图层面板原生菜单，交互与原生一致。
- **原生一致的不透明度弹窗**：标题、数值输入与滑块样式与图层面板一致。
- **文件夹支持**：控件插入属性面板“未发现任何属性”提示下方，行内容左右各留 16px。
- **通道顺序与名称**：直接采用图层面板 `channelSelector` 下拉框的顺序与文字，自定义通道同样支持。
- **双向同步**：切换图层、或在同一图层内修改混合模式与不透明度时，控件均自动刷新。
- **映射校准助手**：根据当前工具与 3D/2D 视图，自动切换“校准”与“间距大小”预设。

## 界面说明

Painter 菜单栏新增“**SP工具**”菜单，点击后打开“**Substance Painter工具**”设置窗口，包含以下内容：

- **属性面板图层工具**：开关“在属性面板中注入混合模式/不透明度控件”。取消勾选即停止注入，重新勾选立即恢复；宿主版本缺少 `sp.layerstack` 接口时自动置灰。
- **映射校准受影响的工具**：选择需要自动校准的工具组（绘画、几何体填充、橡皮、涂抹、沿路径绘制、克隆、映射、材质选择器）。
- **3D 视图预设 / 2D 视图预设**：分别设置校准（镜头、切线|Wrap包裹、切线|平面、UV）与间距大小（物体、视图、纹理）。
- **自动校准开关**：一键启用或停止自动校准。

窗口底部为作者署名与 GitHub 仓库链接。

## 架构

插件采用“C++ 界面模块 + Python 数据桥”的混合架构：

- **C++ 原生模块**（`native/sp_layer_tools_delegate_qt5.dll` 与 `sp_layer_tools_delegate_qt6.dll`）：负责定位属性面板锚点、注入控件面板、面板被重建后自动重新注入，并克隆图层面板原生菜单；按运行环境的 PySide 版本自动加载对应 DLL。
- **Python 数据桥**（`__init__.py`）：通过官方 `sp.layerstack` 接口读写图层的混合模式与不透明度，将通道列表与图层当前值同步给 C++，同时实现映射校准助手。

### 刷新策略（事件驱动）

- 图层切换或图层数值变化 → `LayerStacksModelDataChanged`（80ms 去抖；结构变化时重建面板，数值变化时仅同步数值）。老版本没有该事件时，自动退回 `TextureStateEvent` 兜底。
- 新建或删除通道 → 纹理集设置面板刷新触发（面板级事件过滤器）。
- 属性面板被 Painter 重建 → C++ 事件过滤器自动重新注入控件。

## 兼容性

- 操作系统：Windows 10 / 11（64 位）。
- 图层工具依赖官方 `sp.layerstack` 接口，该接口自 Substance 3D Painter 10.0 起提供；7.x–9.x 仅有映射校准助手可用，图层工具开关将自动置灰。

| Substance 3D Painter | Qt / PySide | 原生 DLL | 属性面板图层工具 | 映射校准助手 |
| --- | --- | --- | --- | --- |
| 7.2–9.x | Qt5 / PySide2 | `_qt5.dll` | 不可用（无 `sp.layerstack`） | 可用 |
| 10.0 | Qt5 / PySide2 | `_qt5.dll` | 可用 | 可用 |
| 10.1+ | Qt6 / PySide6 | `_qt6.dll` | 可用 | 可用 |

- Python 源码按 3.7 语法兼容校验，老版本（Python 3.7 / PySide2）与新版本（Python 3.11 / PySide6）共用同一份 `__init__.py`。

## 安装

将本目录（`sp_tools`）整体复制到 Painter 的插件目录：

```text
C:\Users\<用户名>\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\
```

重启 Painter 后生效。点击菜单栏“SP工具”即可打开设置窗口。

> 原生 DLL 必须与 Painter 的 Qt 主版本匹配：7.2–10.0 使用 Qt5 版，10.1 及以上使用 Qt6 版。打包脚本会同时产出两个 DLL，插件按运行环境自动选择。

## 编译原生模块

需要 Windows x64、CMake 与 MSVC（Visual Studio 2022 Build Tools）。Qt SDK 位于 `sp_tools\sdks\qt\`（`5.12.5/msvc2017_64` 与 `6.5.3/msvc2019_64`），`CMakeLists.txt` 中以相对路径引用。

在插件根目录执行：

```text
python source/cpp/build_package.py
```

编译产物：

- `sp_layer_tools_delegate_qt5.dll`（Painter 7.2–10.0 / Qt5）；
- `sp_layer_tools_delegate_qt6.dll`（Painter 10.1+ / Qt6）。

两者均需放入 `native/` 目录，插件会按运行环境的 PySide 版本自动加载对应的 DLL。

## 安全说明

- 插件只修改图层的显示参数（混合模式、不透明度），不修改任何项目数据文件。
- 数值写入通过官方 `sp.layerstack` 接口完成，并处于 `ScopedModification` 作用域内，可正常进入撤销栈。

## 作者与仓库

本插件由 [bilibili 神说要凑数](https://space.bilibili.com/281243426) 制作，源码仓库见 [GitHub：iillya/sp_tools](https://github.com/iillya/sp_tools)。
