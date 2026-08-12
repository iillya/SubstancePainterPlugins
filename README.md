# sp_tools — 属性面板图层工具

在 Substance 3D Painter 的“属性”面板中注入“每通道 混合模式 + 不透明度”控件，
实时作用于当前选中图层 / 文件夹 / 滤镜 / 生成器的对应通道。

## 功能

- 填充图层、绘画图层、文件夹、滤镜、生成器：逐通道显示混合模式与不透明度。
- 混合模式菜单与图层面板原生菜单一致（顺序 / 分隔线 / 文字直接克隆）。
- 不透明度弹窗与图层面板一致：标题 + 数值输入 + 滑块。
- 文件夹：控件插在属性面板“未发现任何属性”提示下方，行内容左右留 16px。
- 通道顺序与名称直接采用图层面板 `channelSelector` 下拉框（含自定义通道）。
- 内置“映射校准助手”：按当前工具 + 3D/2D 视图自动切换对齐 / 间距大小预设。

## 架构（混合式）

- `packages/sp_layer_tools_delegate_qt6.dll`：C++ 界面模块，负责查找属性面板
  锚点、注入控件面板、面板被重建后自动重新注入，并克隆图层面板原生菜单。
- `__init__.py`：Python 数据桥，读写 `sp.layerstack` 的混合模式与不透明度，
  把通道列表 / 图层当前值同步给 C++；同时包含映射校准助手。

刷新策略（事件驱动）：

- 图层切换 → `LayerStacksModelDataChanged`（80ms 去抖 + 选中节点对比）。
- 新建 / 删除通道 → 纹理集设置面板刷新触发（面板级事件过滤器）。
- 属性面板被 Painter 重建 → C++ 事件过滤器自动重新注入。

## 安装

把本目录（`sp_tools`）整体复制到：

```text
C:\Users\<用户名>\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\
```

重启 Painter 后生效。菜单“映射校准助手”可打开校准设置窗口。

> 原生 DLL 需要与 Painter 的 Qt6 匹配；更换 Painter 大版本后请重新编译。

## 编译原生模块

需要 Windows x64 + CMake + MSVC（Visual Studio 2022 Build Tools），
Qt SDK 依赖位于 `C:\Users\liuwenbo\Desktop\sp插件\public\sdks\qt\`
（`5.12.5/msvc2017_64` 与 `6.5.3/msvc2019_64`），
`CMakeLists.txt` 中以绝对路径引用：

```text
cmake -S source/sp_tools/c++ -B source/sp_tools/c++/build
cmake --build source/sp_tools/c++/build --config Release
```

编译产物：

- `sp_layer_tools_delegate_qt5.dll`（旧版 Painter / Qt5）
- `sp_layer_tools_delegate_qt6.dll`（Painter 10.1+ / Qt6）

两者都需放入 `packages/`，插件会按运行环境的 PySide 版本自动加载对应 DLL。

## 说明

- 插件只修改图层的显示参数（混合模式、不透明度），不修改任何项目数据文件。
