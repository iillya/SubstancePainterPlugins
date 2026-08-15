# -*- coding: utf-8 -*-
"""
sp_tools — Substance 3D Painter 属性面板图层工具插件（混合式架构）

架构：
  * C++ 原生模块（packages/sp_tools_delegate_qt6.dll）负责界面：
    查找属性面板通道按钮、注入“每通道 混合模式 + 不透明度”控件面板、
    控件生命周期与面板被重建后的自动重注入。
  * Python 负责数据：读写图层的混合模式与不透明度（sp.layerstack），
    通过 ctypes 与 C++ 双向同步（通道列表 / 当前值下行，控件改动上行）。

支持：Adobe Substance 3D Painter 7.2-10.0（PySide2 / Qt5）与
      10.1+（PySide6 / Qt6），按运行环境自动选择对应原生 DLL。
"""

import ctypes
import os
import re

import substance_painter as sp
import substance_painter.logging as sp_logging

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    QT_MAJOR = 6
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    QT_MAJOR = 5

try:
    from shiboken6 import getCppPointer, isValid as _is_valid
except ImportError:
    from shiboken2 import getCppPointer, isValid as _is_valid

# 宿主 SP 是否提供 sp.layerstack（图层混合模式/不透明度数据接口）。
# Painter 7.x（如 2021）没有该模块：图层 UI 整体禁用，校准助手不受影响。
_HAS_LAYERSTACK = bool(getattr(sp, "layerstack", None)) and \
    hasattr(getattr(sp, "layerstack", None), "BlendingMode")

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
NATIVE_DIR = os.path.join(PLUGIN_DIR, "native")
DELEGATE_DLL_PATH = os.path.join(
    NATIVE_DIR,
    "sp_layer_tools_delegate_qt5.dll" if QT_MAJOR == 5
    else "sp_layer_tools_delegate_qt6.dll",
)

# 混合模式中文名；键为“去符号小写”形式，兼容 PASS_THROUGH / PASSTHROUGH 等写法
BLEND_MODE_NAMES = {
    "normal": "正常",
    "passthrough": "穿透",
    "disable": "禁用",
    "replace": "替换",
    "multiply": "正片叠底",
    "divide": "除法",
    "inversedivide": "反向除法",
    "darken": "变暗",
    "lighten": "变亮",
    "lineardodge": "线性减淡",
    "subtract": "减去",
    "inversesubtract": "反向减去",
    "difference": "差值",
    "exclusion": "排除",
    "signedaddition": "有符号叠加",
    "overlay": "叠加",
    "screen": "滤色",
    "linearburn": "线性加深",
    "colorburn": "颜色加深",
    "colordodge": "颜色减淡",
    "softlight": "柔光",
    "hardlight": "强光",
    "vividlight": "亮光",
    "linearlight": "线性光",
    "pinlight": "点光",
    "tint": "色调",
    "saturation": "饱和度",
    "color": "颜色",
    "value": "明度",
    "normalmapcombine": "法线贴图合并",
    "normalmapdetail": "法线贴图细节",
    "normalmapinversedetail": "法线贴图反向细节",
}

STANDARD_CHANNEL_DISPLAY = {
    "basecolor": "颜色",
    "color": "颜色",
    "metallic": "金属度",
    "roughness": "粗糙度",
    "normal": "法线",
    "height": "高度",
    "opacity": "不透明度",
    "emissive": "自发光",
    "ao": "环境光遮蔽",
    "displacement": "置换",
    "glossiness": "光泽度",
    "specular": "高光",
    "specularedgecolor": "高光边缘颜色",
    "translucency": "半透明",
    "scattering": "散射",
    "scattercolor": "散射颜色",
    "transmissive": "透射",
    "reflection": "反射",
    "ior": "折射率",
    "diffuse": "漫反射",
    "specularlevel": "高光级别",
    "anisotropylevel": "各向异性级别",
    "anisotropyangle": "各向异性角度",
    "sheenopacity": "光泽不透明度",
    "sheenroughness": "光泽粗糙度",
    "sheencolor": "光泽颜色",
    "coatopacity": "涂层不透明度",
    "coatcolor": "涂层颜色",
    "coatroughness": "涂层粗糙度",
    "coatnormal": "涂层法线",
    "blendingmask": "混合遮罩",
    "bentnormals": "弯曲法线",
    "curvature": "曲率",
    "thickness": "厚度",
    "position": "位置",
    "id": "ID",
    "worldspacenormal": "世界空间法线",
}


def _safe(obj):
    try:
        return obj is not None and _is_valid(obj)
    except Exception:
        return False


def _normalize(name):
    # 保留中文字符，方便匹配中文标签
    return re.sub(r"[^a-z0-9\u3400-\u9fff]", "", str(name).lower())


def _channel_display_name(channel):
    """通道的显示名：标准通道用中文映射，User 通道用自定义标签。"""
    name = getattr(channel, "name", "") or ""
    normalized = _normalize(name)
    display = STANDARD_CHANNEL_DISPLAY.get(normalized)
    if display:
        return display
    try:
        label = channel.label()
        if label and label.strip():
            return label.strip()
    except Exception:
        pass
    return name


def _build_channel_list():
    """读取当前图层栈的通道列表（保持通道集顺序）。"""
    try:
        stack = sp.textureset.get_active_stack()
        return list(stack.all_channels().keys())
    except Exception:
        return []


def _build_channel_map():
    """读取当前图层栈的 {ChannelType: Channel} 映射（底层 API）。"""
    try:
        stack = sp.textureset.get_active_stack()
        return dict(stack.all_channels())
    except Exception:
        return {}


def _enum_member(enum, name):
    """按多种命名写法解析枚举成员（PASS_THROUGH / Passthrough / passthrough…）。"""
    if not name:
        return None
    variants = [name, name.upper(), name.lower(), name.title()]
    compact = re.sub(r"[_\- ]", "", name)
    variants += [compact, compact.upper(), compact.lower()]
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    variants += [snake, snake.upper(), snake.lower()]
    for candidate in variants:
        member = getattr(enum, candidate, None)
        if member is not None:
            return member
    return None


# ==========================================
# ctypes 绑定 C++ 原生模块
# ==========================================
_native = None
_VALUE_CALLBACK_TYPE = ctypes.CFUNCTYPE(
    None, ctypes.c_int, ctypes.c_wchar_p, ctypes.c_double
)
_RESOLVE_CALLBACK_TYPE = ctypes.CFUNCTYPE(
    None, ctypes.c_int, ctypes.POINTER(ctypes.c_wchar_p)
)
_VALUE_REQUEST_TYPE = ctypes.CFUNCTYPE(None)
_FOLDER_RESOLVE_CALLBACK_TYPE = ctypes.CFUNCTYPE(None)
_TEXTURE_SETTINGS_CALLBACK_TYPE = ctypes.CFUNCTYPE(None)
_VIEW_CHANGED_CALLBACK_TYPE = ctypes.CFUNCTYPE(None)
_ALIGN_TICK_CALLBACK_TYPE = ctypes.CFUNCTYPE(None)
_value_callback_handle = None
_resolve_callback_handle = None
_value_request_handle = None
_folder_resolve_handle = None
_texture_settings_handle = None
_view_changed_handle = None
_align_tick_handle = None
_NATIVE_CHANNELS = []  # [(ChannelType, label)]，顺序与按钮一致
_LAST_FOLDER_PROBE_NAME = ""  # 已提示过“不支持接口”的文件夹名（防刷屏）


def _load_native():
    global _native
    if _native is not None:
        return _native
    try:
        dll = ctypes.CDLL(DELEGATE_DLL_PATH)
        dll.sp_tools_api_version.restype = ctypes.c_int
        dll.sp_tools_set_enabled.argtypes = [ctypes.c_int]
        dll.sp_tools_set_enabled.restype = None
        dll.sp_tools_set_value_callback.argtypes = [ctypes.c_void_p]
        dll.sp_tools_set_value_callback.restype = None
        dll.sp_tools_set_resolve_callback.argtypes = [ctypes.c_void_p]
        dll.sp_tools_set_resolve_callback.restype = None
        dll.sp_tools_set_value_request_callback.argtypes = [ctypes.c_void_p]
        dll.sp_tools_set_value_request_callback.restype = None
        dll.sp_tools_set_folder_resolve_callback.argtypes = [ctypes.c_void_p]
        dll.sp_tools_set_folder_resolve_callback.restype = None
        dll.sp_tools_set_texture_settings_callback.argtypes = [ctypes.c_void_p]
        dll.sp_tools_set_texture_settings_callback.restype = None
        dll.sp_tools_set_view_changed_callback.argtypes = [ctypes.c_void_p]
        dll.sp_tools_set_view_changed_callback.restype = None
        dll.sp_tools_set_align_tick_callback.argtypes = [ctypes.c_void_p]
        dll.sp_tools_set_align_tick_callback.restype = None
        dll.sp_tools_set_layer_tools_available.argtypes = [ctypes.c_int]
        dll.sp_tools_set_layer_tools_available.restype = None
        dll.sp_tools_set_folder_mode.argtypes = [ctypes.c_int]
        dll.sp_tools_set_folder_mode.restype = None
        dll.sp_tools_set_blend_modes.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_wchar_p),
            ctypes.POINTER(ctypes.c_wchar_p),
            ctypes.POINTER(ctypes.c_int),
        ]
        dll.sp_tools_set_blend_modes.restype = None
        dll.sp_tools_set_channels.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_wchar_p),
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        dll.sp_tools_set_channels.restype = None
        dll.sp_tools_set_value.argtypes = [
            ctypes.c_int, ctypes.c_wchar_p, ctypes.c_double
        ]
        dll.sp_tools_set_value.restype = None
        dll.sp_tools_reinject.argtypes = []
        dll.sp_tools_reinject.restype = None
        dll.sp_tools_shutdown.argtypes = []
        dll.sp_tools_shutdown.restype = None
        dll.sp_tools_install.argtypes = [ctypes.c_void_p]
        dll.sp_tools_install.restype = ctypes.c_int
        if dll.sp_tools_api_version() != 5:
            print(">>> sp_tools: 原生模块 API 版本不匹配")
            return None
        _native = dll
    except Exception as exc:
        print(">>> sp_tools 原生模块加载失败:", exc)
        _native = None
    return _native


def _wstr_array(strings):
    array = (ctypes.c_wchar_p * len(strings))()
    for i, value in enumerate(strings):
        array[i] = str(value)
    return array


def _on_value_changed(index, mode_name, opacity):
    """C++ 控件改动回调：把新值写回当前图层的对应通道。"""
    if _PLUGIN_CLOSING or _SESSION_CLOSING:
        return
    try:
        layer = _selected_layer()
        if layer is None:
            return
        if index < 0 or index >= len(_NATIVE_CHANNELS):
            return
        channel = _NATIVE_CHANNELS[index][0]
        if channel is None and _is_folder_layer(layer):
            channel = _folder_blending_channel(layer)
            if channel is None:
                return
        with sp.layerstack.ScopedModification("sp_tools 调整图层"):
            mode = (_enum_member(sp.layerstack.BlendingMode, mode_name)
                    if mode_name else None)
            if mode is not None and layer.get_blending_mode(channel) != mode:
                layer.set_blending_mode(mode, channel)
            if opacity is not None and opacity >= 0.0:
                opacity_value = opacity / 100.0
                if abs(layer.get_opacity(channel) - opacity_value) > 1e-6:
                    layer.set_opacity(opacity_value, channel)
    except Exception as exc:
        print(">>> sp_tools 应用图层参数失败:", exc)


def _on_resolve_channels(count, texts):
    """C++ 请求解析通道：直接按纹理集通道列表全量下发（不靠按钮文字）。"""
    if _PLUGIN_CLOSING or _SESSION_CLOSING:
        return
    try:
        _push_channels_to_native()
    except Exception as exc:
        print(">>> sp_tools 解析通道失败:", exc)


def _push_channels_to_native():
    """把当前纹理集全部通道按图层面板 channelSelector 顺序下发，行数=通道数。"""
    pairs = _channel_pairs_in_ui_order()
    if pairs:
        _publish_native_channels(pairs)
    else:
        _publish_native_channels([(None, "文件夹")])


def _find_channel_selector_combo():
    """图层面板 channelSelector 下拉框（通道 UI 顺序的权威来源）。"""
    dock = _layers_dock()
    if not _safe(dock):
        return None
    for combo in dock.findChildren(QtWidgets.QComboBox):
        if _safe(combo) and combo.objectName() == "channelSelector":
            return combo
    return None


def _channel_pairs_in_ui_order():
    """按 channelSelector 下拉框顺序返回 [(ChannelType, 下拉框文字)]，
    通道名也直接复用 Painter 的显示文字，不自造。"""
    combo = _find_channel_selector_combo()
    allch = _build_channel_map()
    if combo is None or not allch:
        return [(channel, _channel_display_name(channel))
                for channel in _build_channel_list()]
    by_value = {}
    by_name = {}
    for channel_type, channel in allch.items():
        try:
            by_value[int(channel_type)] = channel_type
        except Exception:
            pass
        type_name = getattr(channel_type, "name", None)
        if type_name:
            by_name[_normalize(type_name)] = channel_type
        try:
            cid = getattr(channel, "channel_id", None)
            if cid is not None:
                by_value[cid] = channel_type
        except Exception:
            pass
    ordered = []
    used = set()
    for i in range(combo.count()):
        resolved = None
        try:
            data = combo.itemData(i)
        except Exception:
            data = None
        if data is not None and not isinstance(data, (int, str)):
            try:
                data = int(data)
            except Exception:
                data = None
        if data is not None:
            if data in by_value:
                resolved = by_value[data]
            elif isinstance(data, str):
                resolved = by_name.get(_normalize(data))
        label = combo.itemText(i)
        if resolved is not None and resolved not in used:
            ordered.append((resolved, label))
            used.add(resolved)
    # 补上未出现在下拉框里的通道，保证不丢
    for channel_type in allch:
        if channel_type not in used:
            ordered.append((channel_type, _channel_display_name(channel_type)))
    if ordered:
        return ordered
    return [(channel, _channel_display_name(channel))
            for channel in _build_channel_list()]


def _publish_native_channels(pairs):
    """填充/绘画图层与文件夹共用的通道下发：回填 _NATIVE_CHANNELS 并同步给 C++。"""
    global _NATIVE_CHANNELS
    dll = _load_native()
    if dll is None:
        return
    _NATIVE_CHANNELS = list(pairs)
    ids = [getattr(channel, "name", "") or ""
           for channel, _label in _NATIVE_CHANNELS]
    labels = [label for _channel, label in _NATIVE_CHANNELS]
    dll.sp_tools_set_channels(len(ids), _wstr_array(ids), _wstr_array(labels))


def _on_resolve_folder():
    """C++ 进入文件夹模式时请求通道列表：与填充图层一样按通道显示。"""
    if _PLUGIN_CLOSING or _SESSION_CLOSING:
        return
    try:
        _push_channels_to_native()
    except Exception as exc:
        print(">>> sp_tools 解析文件夹通道失败:", exc)


def _on_value_request():
    """C++ 控件面板就绪后请求当前图层各通道的值。"""
    if _PLUGIN_CLOSING or _SESSION_CLOSING:
        return
    _sync_values_to_native()


def _selected_layer():
    try:
        stack = sp.textureset.get_active_stack()
        for node in sp.layerstack.get_selected_nodes(stack):
            if hasattr(node, "has_blending") and node.has_blending():
                return node
        # 文件夹：即使 has_blending() 为 False，也允许显示控件（属性面板为空，由我们创建）
        for node in sp.layerstack.get_selected_nodes(stack):
            if _is_folder_layer(node):
                return node
    except Exception:
        return None
    return None


def _is_folder_layer(layer):
    """判断节点是否为文件夹（GroupLayerNode）。"""
    try:
        return isinstance(layer, sp.layerstack.GroupLayerNode)
    except Exception:
        return False


def _folder_blending_channel(layer):
    """文件夹的混合模式通道：优先全局单值（None），否则回退到第一个可用通道。"""
    if layer is None:
        return None
    try:
        layer.get_blending_mode(None)
        layer.get_opacity(None)
        return None
    except Exception:
        pass
    try:
        for channel in _build_channel_list():
            layer.get_blending_mode(channel)
            layer.get_opacity(channel)
            return channel
    except Exception:
        pass
    return None


def _sync_blend_modes_to_native():
    if not _HAS_LAYERSTACK:
        return
    dll = _load_native()
    if dll is None:
        return
    enum = sp.layerstack.BlendingMode
    member_map = getattr(enum, "__members__", None)
    entries = []  # (name, label, value)
    if isinstance(member_map, dict):
        for name, member in member_map.items():
            try:
                value = int(member)
            except Exception:
                value = -1
            entries.append((name, BLEND_MODE_NAMES.get(_normalize(name), name),
                            value))
    else:
        for key, label in BLEND_MODE_NAMES.items():
            member = _enum_member(enum, key)
            if member is not None:
                try:
                    value = int(member)
                except Exception:
                    value = -1
                entries.append((member.name, label, value))
    entries.sort(key=lambda item: (0 if item[1] == "正常"
                                   else 1 if item[1] == "穿透"
                                   else 2, item[1]))
    names = [name for name, _label, _value in entries]
    labels = [label for _name, label, _value in entries]
    values = (ctypes.c_int * len(entries))(
        *[value for _name, _label, value in entries])
    dll.sp_tools_set_blend_modes(len(entries), _wstr_array(names),
                                 _wstr_array(labels), values)


def _sync_values_to_native():
    global _LAST_FOLDER_PROBE_NAME
    dll = _load_native()
    if dll is None:
        return
    try:
        layer = _selected_layer()
        folder = _is_folder_layer(layer)
        # 先切换 C++ 的“文件夹模式”，内部会清空通道并请求按通道重建面板
        dll.sp_tools_set_folder_mode(1 if folder else 0)
        any_loaded = False
        for index, (channel, _label) in enumerate(_NATIVE_CHANNELS):
            if layer is None:
                dll.sp_tools_set_value(index, "", -1.0)
                continue
            try:
                mode = layer.get_blending_mode(channel)
                opacity = layer.get_opacity(channel) * 100.0
                dll.sp_tools_set_value(index,
                                       getattr(mode, "name", "") or "",
                                       opacity)
                any_loaded = True
            except Exception:
                dll.sp_tools_set_value(index, "", -1.0)
        if (folder and layer is not None and not any_loaded
                and _NATIVE_CHANNELS):
            try:
                folder_name = layer.get_name() or ""
            except Exception:
                folder_name = ""
            if folder_name != _LAST_FOLDER_PROBE_NAME:
                _LAST_FOLDER_PROBE_NAME = folder_name
                print(">>> sp_tools: 该文件夹不支持按通道混合模式/不透明度接口（控件已禁用）:",
                      folder_name)
    except Exception as exc:
        print(">>> sp_tools 同步图层值失败:", exc)


# ==========================================
# 事件与生命周期
# ==========================================
_LAST_SELECTED_UID = None
_STACK_PENDING = False
_PLUGIN_CLOSING = False
_SESSION_CLOSING = False


def _make_inert():
    """让插件进入会话关闭态：后续所有回调直接返回，不再触碰任何控件/API。"""
    global _SESSION_CLOSING
    _SESSION_CLOSING = True


def _early_teardown():
    """插件卸载/应用退出：进入插件关闭态并立即惰性化。"""
    global _PLUGIN_CLOSING
    _PLUGIN_CLOSING = True
    _make_inert()


def _channel_list_changed():
    """当前纹理集通道集合与面板已建通道不一致（新建/删除通道）时为 True。"""
    try:
        current = set(_build_channel_list())
        known = set(channel for channel, _label in _NATIVE_CHANNELS)
        return current != known
    except Exception:
        return False


_LAYERS_DOCK = None


def _layers_dock():
    """定位图层面板（缓存有效控件）。"""
    global _LAYERS_DOCK
    if _safe(_LAYERS_DOCK):
        return _LAYERS_DOCK
    app = QtWidgets.QApplication.instance()
    if not _safe(app):
        return None
    for widget in app.allWidgets():
        if not _safe(widget):
            continue
        if isinstance(widget, QtWidgets.QDockWidget):
            try:
                title = widget.windowTitle() or ""
            except Exception:
                continue
            if "图层" in title or "layers" in _normalize(title):
                _LAYERS_DOCK = widget
                return widget
    return None


def _on_stack_changed(_event):
    """图层栈变化（切换/数值改动）：去抖后按需重建，并同步数值。"""
    if _PLUGIN_CLOSING or _SESSION_CLOSING:
        return
    global _STACK_PENDING
    if _STACK_PENDING:
        return
    _STACK_PENDING = True
    QtCore.QTimer.singleShot(80, _stack_changed_debounced)


def _stack_change_event_class():
    """图层切换监听事件：新版优先 LayerStacksModelDataChanged；
    老版本（如 Painter 7.x）没有该事件时退回 TextureStateEvent 兜底。
    两个事件都缺失时返回 None（跳过绑定，功能降级但不报错）。"""
    return (
        getattr(sp.event, "LayerStacksModelDataChanged", None)
        or getattr(sp.event, "TextureStateEvent", None)
    )


def _stack_changed_debounced():
    """图层栈变化刷新：节点/通道集合变了才重建，数值变化只同步值。"""
    if _PLUGIN_CLOSING or _SESSION_CLOSING:
        return
    global _STACK_PENDING, _LAST_SELECTED_UID
    _STACK_PENDING = False
    dll = _load_native()
    if dll is None:
        return
    layer = _selected_layer()
    uid = None
    try:
        uid = layer.uid() if layer is not None else None
    except Exception:
        uid = None
    channel_changed = _channel_list_changed()
    if uid != _LAST_SELECTED_UID or channel_changed:
        _LAST_SELECTED_UID = uid
        _push_channels_to_native()
        dll.sp_tools_reinject()
    # 同一图层内混合模式/不透明度被原生面板改动时，也要回写自定义控件
    _sync_values_to_native()


def _on_texture_set_settings_changed():
    """纹理集设置面板刷新（C++ 触发）：通道集合变了才重建（新建/删除通道）。"""
    if _PLUGIN_CLOSING or _SESSION_CLOSING:
        return
    dll = _load_native()
    if dll is None:
        return
    if not _channel_list_changed():
        return
    _push_channels_to_native()
    dll.sp_tools_reinject()
    _sync_values_to_native()


def _on_texture_settings_refresh():
    """C++ 纹理集设置面板刷新回调入口。"""
    if _PLUGIN_CLOSING or _SESSION_CLOSING:
        return
    _on_texture_set_settings_changed()


def _on_view_changed():
    """C++ 3D/2D 视图进出回调入口：触发校准同步。"""
    if _PLUGIN_CLOSING or _SESSION_CLOSING:
        return
    _align_run_sync()


def _on_align_tick():
    """C++ 0.5s 校准定时器回调入口。"""
    if _PLUGIN_CLOSING or _SESSION_CLOSING:
        return
    _align_run_sync()


def _on_project_opened(_event):
    if _PLUGIN_CLOSING:
        return
    QtCore.QTimer.singleShot(200, _project_opened_debounced)


def _project_opened_debounced():
    global _LAST_SELECTED_UID, _SESSION_CLOSING
    if _PLUGIN_CLOSING:
        return
    _LAST_SELECTED_UID = None
    _SESSION_CLOSING = False
    dll = _load_native()
    if dll is None:
        return
    dll.sp_tools_set_enabled(1)
    dll.sp_tools_reinject()
    # 项目刚打开时若选中的就是文件夹，主动进入文件夹模式并注入控件
    QtCore.QTimer.singleShot(300, _sync_values_to_native)


def _on_project_closing(_event):
    if _PLUGIN_CLOSING or _SESSION_CLOSING:
        return
    _make_inert()
    dll = _load_native()
    if dll is not None:
        dll.sp_tools_set_enabled(0)


# ==========================================
# 映射校准助手（合并自 映射校准助手.py）
# ==========================================
TOOL_LOGIC_GROUPS = {
    "绘画": ["Paint", "Paint_Physics"],
    "橡皮": ["Eraser", "Eraser_Physics"],
    "映射": ["PaintProjective", "PaintProjective_Physics"],
    "沿路径绘制": ["Curve_Stroke_3D", "Curve_Ribbon", "Curve_Fill",
                  "Curve_Eraser_Stroke_3D", "Curve_Smudge_Stroke_3D"],
    "涂抹": ["Smudge"],
    "克隆": ["clone_relative", "clone_absolute"],
    "几何体填充": ["Geometry"],
    "材质选择器": ["materials_action"],
}

if not hasattr(QtCore, "_auto_align_cfg"):
    QtCore._auto_align_cfg = {
        "3A": 1, "3S": 0,
        "2A": 3, "2S": 2,
        "layer_tools_enabled": True,
        "enabled": True,
        "last_view": None,
        "last_tool": None,
        "active_groups": {
            "绘画": True,
            "橡皮": True,
            "映射": False,
            "几何体填充": False,
            "涂抹": True,
            "克隆": False,
            "沿路径绘制": False,
            "材质选择器": False,
        },
    }

ALIGN_ITEMS = ["镜头", "切线|Wrap包裹", "切线|平面", "UV"]
SPACE_ITEMS = ["物体", "视图", "纹理"]

_align_sync_error_logged = False
_align_tool_buttons = []
_align_toolbars = []
_align_ui = None
_align_action = None


def _align_get_current_tool_id():
    """读取左侧工具栏当前选中的工具 ID（排除插件自身/系统按钮）。"""
    main_win = sp.ui.get_main_window()
    if not _safe(main_win):
        return None
    toolbar = main_win.findChild(QtWidgets.QToolBar, "Toolbar")
    scope = toolbar if _safe(toolbar) else main_win
    for button in scope.findChildren(QtWidgets.QToolButton):
        if not _safe(button) or not button.isChecked():
            continue
        action = button.defaultAction()
        if action is None:
            continue
        action_id = action.objectName()
        if action_id and not action_id.startswith("qt_") and action_id != "enable":
            return action_id
    return None


def _align_run_sync():
    """同步入口（事件触发 + 500ms 兜底）：内部异常只记录一次，避免刷屏。"""
    if _PLUGIN_CLOSING or _SESSION_CLOSING:
        return
    global _align_sync_error_logged
    try:
        _align_do_sync()
        _align_sync_error_logged = False
    except Exception as exc:
        if not _align_sync_error_logged:
            _align_sync_error_logged = True
            sp_logging.warning("映射校准助手同步异常: %s" % exc)


def _align_invalidate_and_sync():
    """配置变动后使缓存失效，并在事件循环空闲时应用当前预设。"""
    cfg = QtCore._auto_align_cfg
    cfg["last_tool"] = None
    cfg["last_view"] = None
    if not _PLUGIN_CLOSING and not _SESSION_CLOSING:
        QtCore.QTimer.singleShot(0, _align_run_sync)


def _align_do_sync():
    if not sp.project.is_open():
        return
    cfg = QtCore._auto_align_cfg
    if not cfg["enabled"]:
        return
    current_id = _align_get_current_tool_id()
    matched_group = None
    for group_name, id_list in TOOL_LOGIC_GROUPS.items():
        if current_id in id_list:
            matched_group = group_name
            break
    if not matched_group or not cfg["active_groups"].get(matched_group, False):
        return

    pos = QtGui.QCursor.pos()
    widget = QtWidgets.QApplication.widgetAt(pos)
    view_type = None
    if _safe(widget):
        current = widget
        for _depth in range(8):
            if not _safe(current):
                break
            name = current.objectName()
            if name == "Viewer3D":
                view_type = "3D"
                break
            if name == "TextureViewer":
                view_type = "2D"
                break
            current = current.parentWidget()
    if current_id == cfg["last_tool"] and view_type == cfg["last_view"]:
        return
    if view_type:
        prefix = "3" if view_type == "3D" else "2"
        target_a = cfg[prefix + "A"]
        target_s = cfg[prefix + "S"]
        main_win = sp.ui.get_main_window()
        applied = False
        if _safe(main_win):
            tool_panel = main_win.findChild(QtWidgets.QWidget, "Tool")
            if _safe(tool_panel):
                for combo in tool_panel.findChildren(QtWidgets.QComboBox):
                    if not _safe(combo) or not combo.isVisible():
                        continue
                    obj_name = combo.objectName().lower()
                    if "alignment" in obj_name:
                        applied = True
                        if combo.currentIndex() != target_a:
                            combo.setCurrentIndex(target_a)
                            combo.activated.emit(target_a)
                    if "size_space" in obj_name:
                        applied = True
                        if combo.currentIndex() != target_s:
                            combo.setCurrentIndex(target_s)
                            combo.activated.emit(target_s)
                # 只有真正在可见面板上应用成功才记录状态，面板重开后会补上
                if applied:
                    cfg["last_tool"] = current_id
                    cfg["last_view"] = view_type
    else:
        cfg["last_tool"] = current_id
        cfg["last_view"] = view_type


def _align_on_tool_toggled(_checked=False):
    if _PLUGIN_CLOSING or _SESSION_CLOSING:
        return
    QtCore.QTimer.singleShot(0, _align_run_sync)


def _align_install_tool_buttons():
    """把工具栏工具按钮的 toggled 接到同步入口（幂等，可重复调用）。"""
    global _align_tool_buttons, _align_toolbars
    _align_toolbars = [toolbar for toolbar in _align_toolbars if _is_valid(toolbar)]
    _align_tool_buttons = [btn for btn in _align_tool_buttons if _is_valid(btn)]
    main_win = sp.ui.get_main_window()
    if not _safe(main_win):
        return
    toolbar = main_win.findChild(QtWidgets.QToolBar, "Toolbar")
    if _safe(toolbar) and toolbar not in _align_toolbars:
        try:
            toolbar.actionsChanged.connect(_align_on_toolbar_actions_changed)
            _align_toolbars.append(toolbar)
        except Exception:
            pass
    scope = toolbar if _safe(toolbar) else main_win
    for button in scope.findChildren(QtWidgets.QToolButton):
        if not _safe(button) or button in _align_tool_buttons:
            continue
        action = button.defaultAction()
        if action is None:
            continue
        action_id = action.objectName()
        if not action_id or action_id.startswith("qt_") or action_id == "enable":
            continue
        try:
            button.toggled.connect(_align_on_tool_toggled)
            _align_tool_buttons.append(button)
        except RuntimeError:
            pass


def _align_on_toolbar_actions_changed():
    """工具栏增删按钮后重新挂 toggled 连接（事件驱动，替代定时重挂）。"""
    if _PLUGIN_CLOSING or _SESSION_CLOSING:
        return
    QtCore.QTimer.singleShot(0, _align_install_tool_buttons)


def _apply_layer_tools_enabled():
    """按开关状态启用/禁用属性面板图层工具（注入控件 + 克隆原生菜单）。"""
    dll = _load_native()
    if dll is None:
        return
    enabled = (QtCore._auto_align_cfg.get("layer_tools_enabled", True)
               and _HAS_LAYERSTACK)
    dll.sp_tools_set_layer_tools_available(1 if enabled else 0)
    if enabled:
        dll.sp_tools_reinject()


class _AlignControl(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(sp.ui.get_main_window())
        self.setObjectName("MappingAlignHelperUI")
        self.setWindowTitle("Substance Painter工具")
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setMinimumWidth(380)
        self.cfg = QtCore._auto_align_cfg
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 10)

        credit = QtWidgets.QLabel(
            '<a href="https://space.bilibili.com/281243426" '
            'style="color: #66aaff;">本插件由 bilibili 神说要凑数 制作，'
            "点击可查看作者主页</a>"
            "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
            '<a href="https://github.com/iillya/sp_tools" '
            'style="color: #66aaff;">GitHub 仓库</a>',
            self,
        )
        credit.setOpenExternalLinks(True)
        credit.setToolTip("打开 bilibili 作者主页")
        layout.addWidget(credit)

        layer_group = QtWidgets.QGroupBox("属性面板图层工具")
        layer_layout = QtWidgets.QVBoxLayout(layer_group)
        self.layer_tools_check = QtWidgets.QCheckBox(
            "在属性面板中注入混合模式/不透明度控件")
        self.layer_tools_check.setChecked(
            self.cfg.get("layer_tools_enabled", True) and _HAS_LAYERSTACK)
        self.layer_tools_check.toggled.connect(self._toggle_layer_tools)
        layer_layout.addWidget(self.layer_tools_check)
        if not _HAS_LAYERSTACK:
            self.layer_tools_check.setEnabled(False)
            layer_hint = QtWidgets.QLabel(
                "当前 SP 版本缺少 sp.layerstack 接口，图层工具不可用")
            layer_hint.setStyleSheet("color: #b08d57;")
            layer_layout.addWidget(layer_hint)
        layout.addWidget(layer_group)

        tool_group = QtWidgets.QGroupBox("映射校准受影响的工具")
        grid_layout = QtWidgets.QGridLayout(tool_group)
        group_names = ["绘画", "几何体填充", "橡皮", "涂抹",
                       "沿路径绘制", "克隆", "映射", "材质选择器"]
        for index, name in enumerate(group_names):
            check = QtWidgets.QCheckBox(name)
            check.setChecked(self.cfg["active_groups"].get(name, False))
            check.toggled.connect(
                lambda state, n=name: self._set_active_group(n, state))
            grid_layout.addWidget(check, index // 2, index % 2)
        layout.addWidget(tool_group)

        def make_group(title, a_key, s_key):
            group = QtWidgets.QGroupBox(title)
            gl = QtWidgets.QGridLayout(group)
            gl.addWidget(QtWidgets.QLabel("校准"), 0, 0)
            combo_a = QtWidgets.QComboBox()
            combo_a.addItems(ALIGN_ITEMS)
            combo_a.setCurrentIndex(self.cfg[a_key])
            combo_a.activated.connect(lambda i: self._set_preset(a_key, i))
            gl.addWidget(combo_a, 0, 1)
            gl.addWidget(QtWidgets.QLabel("间距大小"), 1, 0)
            combo_s = QtWidgets.QComboBox()
            combo_s.addItems(SPACE_ITEMS)
            combo_s.setCurrentIndex(self.cfg[s_key])
            combo_s.activated.connect(lambda i: self._set_preset(s_key, i))
            gl.addWidget(combo_s, 1, 1)
            gl.setColumnStretch(1, 1)
            layout.addWidget(group)

        make_group("3D 视图预设", "3A", "3S")
        make_group("2D 视图预设", "2A", "2S")

        self.btn = QtWidgets.QPushButton()
        self.btn.setCheckable(True)
        self.btn.setChecked(self.cfg["enabled"])
        self.btn.setFixedHeight(38)
        self.btn.toggled.connect(self.toggle_sync)
        layout.addWidget(self.btn)
        self.update_style(self.cfg["enabled"])

    def update_style(self, on):
        self.btn.setText("自动校准运行中 (点击停止)" if on else "启用自动校准")
        self.btn.setStyleSheet(
            "background: #2D5A27; color: white; font-weight: bold; border-radius: 4px;"
            if on else "")

    def toggle_sync(self, checked):
        self.cfg["enabled"] = checked
        self.update_style(checked)
        if checked:
            _align_invalidate_and_sync()

    def _set_active_group(self, name, checked):
        self.cfg["active_groups"][name] = checked
        if checked:
            _align_invalidate_and_sync()

    def _set_preset(self, key, index):
        self.cfg[key] = index
        _align_invalidate_and_sync()

    def _toggle_layer_tools(self, checked):
        self.cfg["layer_tools_enabled"] = checked
        _apply_layer_tools_enabled()

    def closeEvent(self, event):
        global _align_ui
        _align_ui = None
        super().closeEvent(event)


def _align_show_ui():
    global _align_ui
    if _align_ui is not None and not _is_valid(_align_ui):
        _align_ui = None
    if _align_ui is None:
        _align_ui = _AlignControl()
    _align_ui.show()
    _align_ui.raise_()
    _align_ui.activateWindow()


def _align_start(main_window):
    """启动映射校准助手：菜单入口、监听与首次同步。"""
    global _align_action
    if not _safe(main_window):
        return
    _align_remove_menu(main_window)
    _align_install_tool_buttons()
    _align_action = main_window.menuBar().addAction("SP工具")
    _align_action.setObjectName("MappingHelperAction")
    _align_action.triggered.connect(_align_show_ui)
    # 启动时不会天然产生“切换工具 / 进入视图”的事件；延后两轮事件循环
    # 再同步一次，确保 Painter 的工具属性面板已经创建完成。
    QtCore.QTimer.singleShot(0, _align_run_sync)
    QtCore.QTimer.singleShot(250, _align_run_sync)
    sp_logging.info(">>> 映射校准助手已启用（C++ 触发 + 0.5s 兜底）")


def _align_remove_menu(main_window=None):
    """彻底清理菜单动作。"""
    global _align_action
    if not _safe(main_window):
        main_window = sp.ui.get_main_window()
    if not _safe(main_window):
        return
    for action in main_window.menuBar().actions():
        if action.objectName() == "MappingHelperAction" or \
                action.text() == "sp工具" or \
                action.text() == "Substance Painter工具" or \
                action.text() == "映射校准助手":
            main_window.menuBar().removeAction(action)
            try:
                action.deleteLater()
            except Exception:
                pass
    _align_action = None


def _align_stop():
    """安全、彻底地销毁映射校准助手资源。"""
    global _align_toolbars
    global _align_ui, _align_tool_buttons, _align_action
    for toolbar in _align_toolbars:
        try:
            if _is_valid(toolbar):
                toolbar.actionsChanged.disconnect(_align_on_toolbar_actions_changed)
        except (RuntimeError, TypeError):
            pass
    _align_toolbars = []
    for button in _align_tool_buttons:
        try:
            if _is_valid(button):
                button.toggled.disconnect(_align_on_tool_toggled)
        except (RuntimeError, TypeError):
            pass
    _align_tool_buttons = []
    if _align_ui is not None:
        try:
            if _is_valid(_align_ui):
                _align_ui.close()
                _align_ui.deleteLater()
        except Exception:
            pass
        _align_ui = None
    try:
        _align_remove_menu()
    except Exception:
        pass
    _align_action = None
    sp_logging.info(">>> 映射校准助手已关闭")


def start_plugin():
    global _PLUGIN_CLOSING, _SESSION_CLOSING
    global _value_callback_handle, _resolve_callback_handle
    global _value_request_handle, _folder_resolve_handle
    global _texture_settings_handle, _view_changed_handle, _align_tick_handle
    app = QtWidgets.QApplication.instance()
    main_window = sp.ui.get_main_window()
    if not _safe(app) or not _safe(main_window):
        return

    close_plugin()
    _PLUGIN_CLOSING = False
    # close_plugin() 会把会话标记为关闭。插件在已打开项目中加载/重载时
    # 不会收到 ProjectOpened 事件来复位它，必须在启动完成清理后立即恢复。
    _SESSION_CLOSING = False

    try:
        dll = _load_native()
        if dll is None:
            print(">>> sp_tools: 原生模块不可用，插件未启用")
        else:
            _value_callback_handle = _VALUE_CALLBACK_TYPE(_on_value_changed)
            dll.sp_tools_set_value_callback(_value_callback_handle)
            _resolve_callback_handle = _RESOLVE_CALLBACK_TYPE(
                _on_resolve_channels)
            dll.sp_tools_set_resolve_callback(_resolve_callback_handle)
            _value_request_handle = _VALUE_REQUEST_TYPE(_on_value_request)
            dll.sp_tools_set_value_request_callback(_value_request_handle)
            _folder_resolve_handle = _FOLDER_RESOLVE_CALLBACK_TYPE(
                _on_resolve_folder)
            dll.sp_tools_set_folder_resolve_callback(_folder_resolve_handle)
            _texture_settings_handle = _TEXTURE_SETTINGS_CALLBACK_TYPE(
                _on_texture_settings_refresh)
            dll.sp_tools_set_texture_settings_callback(_texture_settings_handle)
            _view_changed_handle = _VIEW_CHANGED_CALLBACK_TYPE(
                _on_view_changed)
            dll.sp_tools_set_view_changed_callback(_view_changed_handle)
            _align_tick_handle = _ALIGN_TICK_CALLBACK_TYPE(_on_align_tick)
            dll.sp_tools_set_align_tick_callback(_align_tick_handle)

            if _HAS_LAYERSTACK:
                _sync_blend_modes_to_native()
            else:
                print(">>> sp_tools: 当前 SP 无 sp.layerstack 接口，"
                      "图层混合模式 UI 已禁用（仅启用映射校准助手）")

            pointer = getCppPointer(app)[0]
            dll.sp_tools_install(ctypes.c_void_p(pointer))
            _apply_layer_tools_enabled()
            dll.sp_tools_set_enabled(1)
    except Exception as exc:
        print(">>> sp_tools 启动原生模块失败:", exc)

    for event_cls, callback in (
        (_stack_change_event_class(), _on_stack_changed),
        (getattr(sp.event, "ProjectOpened", None), _on_project_opened),
        (getattr(sp.event, "ProjectAboutToClose", None), _on_project_closing),
    ):
        if event_cls is None:
            continue
        try:
            # 老版本（如 Painter 7.x）可能没有 connect_strong，退回弱连接 connect
            connector = getattr(sp.event.DISPATCHER, "connect_strong", None) or \
                sp.event.DISPATCHER.connect
            connector(event_cls, callback)
        except Exception as exc:
            print(">>> sp_tools 事件绑定失败:", exc)

    try:
        app.aboutToQuit.connect(_early_teardown)
    except Exception:
        pass
    _align_start(main_window)

    print(">>> sp_tools 插件已启动（属性面板图层工具 + 映射校准助手）")


def close_plugin():
    _early_teardown()
    global _value_callback_handle, _resolve_callback_handle
    global _value_request_handle, _folder_resolve_handle
    global _texture_settings_handle, _view_changed_handle, _align_tick_handle
    app = QtWidgets.QApplication.instance()
    if _safe(app):
        try:
            app.aboutToQuit.disconnect(_early_teardown)
        except Exception:
            pass
    # 第一步就让 C++ 清空回调指针并移除面板，避免退出阶段调用已释放的 Python 回调
    dll = _load_native()
    if dll is not None:
        try:
            dll.sp_tools_shutdown()
        except Exception:
            pass
    _align_stop()
    for event_cls, callback in (
        (_stack_change_event_class(), _on_stack_changed),
        (getattr(sp.event, "ProjectOpened", None), _on_project_opened),
        (getattr(sp.event, "ProjectAboutToClose", None), _on_project_closing),
    ):
        if event_cls is None:
            continue
        try:
            sp.event.DISPATCHER.disconnect(event_cls, callback)
        except Exception:
            pass
    # C++ 侧回调已清空，这里释放 Python 回调句柄（CFUNCTYPE）
    _value_callback_handle = None
    _resolve_callback_handle = None
    _value_request_handle = None
    _folder_resolve_handle = None
    _texture_settings_handle = None
    _view_changed_handle = None
    _align_tick_handle = None
