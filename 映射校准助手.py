import substance_painter.ui
import substance_painter.project
import substance_painter.logging as sp_logging
from PySide6 import QtCore, QtWidgets, QtGui
import shiboken6 as shiboken

# ==========================================
# 1. 全局配置 (持久化存储于 QtCore)
# ==========================================
if not hasattr(QtCore, '_auto_align_cfg'):
    QtCore._auto_align_cfg = {
        '3A': 1, '3S': 0, 
        '2A': 3, '2S': 2,
        'enabled': True,
        'last_view': None,
        'last_tool': None,
        'active_tools': {
            "Paint": True, 
            "Eraser": True, 
            "PaintProjective": False,
            "Geometry": False, 
            "Smudge": True, 
            "clone_relative": False,
            "Curve_Stroke_3D": False, 
            "materials_action": False
        }
    }

# 映射显示名称与内部 ID
ID_DISPLAY_MAP = {
    "Paint": "绘画",
    "Geometry": "几何体填充",  
    "Eraser": "橡皮",
    "Smudge": "涂抹",
    "Curve_Stroke_3D": "沿路径绘制",
    "clone_relative": "克隆",  
    "PaintProjective": "映射",
    "materials_action": "材质选择器"
}

ALIGN_ITEMS = ["镜头", "切线|Wrap包裹", "切线|平面", "UV"]
SPACE_ITEMS = ["物体", "视图", "纹理"]

# ==========================================
# 2. 核心逻辑函数
# ==========================================

def get_current_tool_id():
    """获取当前 Painter 选中的工具 ID"""
    main_win = substance_painter.ui.get_main_window()
    if not main_win: return None
    buttons = main_win.findChildren(QtWidgets.QToolButton)
    for btn in buttons:
        if btn.isChecked():
            action = btn.defaultAction()
            if action:
                action_id = action.objectName()
                if action_id and not action_id.startswith("qt_"):
                    return action_id
    return None

def run_sync():
    """性能优化版同步逻辑"""
    # 安全锁：无工程打开时不执行逻辑
    if not substance_painter.project.is_open():
        return

    cfg = QtCore._auto_align_cfg
    if not cfg['enabled']: return

    current_tool = get_current_tool_id()
    
    # 视窗感知：判断鼠标所在的视窗类型
    pos = QtGui.QCursor.pos()
    widget = QtWidgets.QApplication.widgetAt(pos)
    view_type = None
    
    if widget and shiboken.isValid(widget):
        curr = widget
        for _ in range(8): # 向上追溯 8 层父级
            if not curr: break
            name = curr.objectName()
            if name == "Viewer3D": view_type = "3D"; break
            if name == "TextureViewer": view_type = "2D"; break
            curr = curr.parentWidget()

    # 性能优化：仅在工具改变或视窗改变时继续
    if current_tool == cfg['last_tool'] and view_type == cfg['last_view']:
        return
    
    cfg['last_tool'] = current_tool
    cfg['last_view'] = view_type

    # 过滤：非勾选工具不执行同步
    if current_tool not in cfg['active_tools'] or not cfg['active_tools'][current_tool]:
        return

    if view_type:
        try:
            prefix = "3" if view_type == "3D" else "2"
            target_a = cfg[f'{prefix}A']
            target_s = cfg[f'{prefix}S']

            main_win = substance_painter.ui.get_main_window()
            tool_panel = main_win.findChild(QtWidgets.QWidget, "Tool")
            
            if tool_panel and shiboken.isValid(tool_panel):
                combos = tool_panel.findChildren(QtWidgets.QComboBox)
                for cb in combos:
                    if not shiboken.isValid(cb) or not cb.isVisible(): continue
                    obj_name = cb.objectName().lower()
                    
                    # 同步 Alignment (校准)
                    if "alignment" in obj_name and cb.currentIndex() != target_a:
                        cb.setCurrentIndex(target_a)
                        cb.activated.emit(target_a)
                        sp_logging.info(f"[助手] {view_type}同步成功: 校准 -> {ALIGN_ITEMS[target_a]}")
                    
                    # 同步 Size Space (间距)
                    if "size_space" in obj_name and cb.currentIndex() != target_s:
                        cb.setCurrentIndex(target_s)
                        cb.activated.emit(target_s)
                        sp_logging.info(f"[助手] {view_type}同步成功: 间距 -> {ALIGN_ITEMS[target_s]}")
        except Exception: pass

# ==========================================
# 3. 优化后的 UI 类
# ==========================================

class AlignControl(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(substance_painter.ui.get_main_window())
        self.setObjectName("MappingAlignHelperUI")
        self.setWindowTitle("映射校准助手")
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        
        # 优化 1：设置更宽的默认尺寸
        self.setMinimumWidth(380)
        
        self.cfg = QtCore._auto_align_cfg
        
        # 主布局：压缩间距，消除空行感
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 10)

        # --- 模块 A：受影响的工具 (双排网格) ---
        tool_group = QtWidgets.QGroupBox("受影响的工具")
        grid_layout = QtWidgets.QGridLayout(tool_group)
        grid_layout.setSpacing(4)
        grid_layout.setContentsMargins(12, 10, 12, 10)
        
        tools = list(ID_DISPLAY_MAP.items())
        for index, (tid, name) in enumerate(tools):
            row = index // 2
            col = index % 2
            cb = QtWidgets.QCheckBox(name)
            cb.setChecked(self.cfg['active_tools'].get(tid, False))
            cb.toggled.connect(lambda s, t=tid: self.cfg['active_tools'].update({t: s}))
            grid_layout.addWidget(cb, row, col)
        
        layout.addWidget(tool_group)

        # --- 模块 B：预设配置区 ---
        def make_group(title, a_key, s_key):
            group = QtWidgets.QGroupBox(title)
            group_layout = QtWidgets.QGridLayout(group)
            group_layout.setContentsMargins(12, 10, 12, 10)
            group_layout.setSpacing(8)
            
            group_layout.addWidget(QtWidgets.QLabel("校准"), 0, 0)
            ca = QtWidgets.QComboBox()
            ca.addItems(ALIGN_ITEMS)
            ca.setCurrentIndex(self.cfg[a_key])
            ca.activated.connect(lambda i: self.cfg.update({a_key: i}))
            group_layout.addWidget(ca, 0, 1)
            
            group_layout.addWidget(QtWidgets.QLabel("间距"), 1, 0)
            cs = QtWidgets.QComboBox()
            cs.addItems(SPACE_ITEMS)
            cs.setCurrentIndex(self.cfg[s_key])
            cs.activated.connect(lambda i: self.cfg.update({s_key: i}))
            group_layout.addWidget(cs, 1, 1)
            
            group_layout.setColumnStretch(1, 1) # 让下拉框填满宽度
            layout.addWidget(group)

        make_group("3D 视图预设", '3A', '3S')
        make_group("2D 视图预设", '2A', '2S')

        # --- 模块 C：状态开关 ---
        self.btn = QtWidgets.QPushButton()
        self.btn.setCheckable(True)
        self.btn.setChecked(self.cfg['enabled'])
        self.btn.setFixedHeight(38)
        self.btn.toggled.connect(self.toggle_sync)
        layout.addWidget(self.btn)
        self.update_style(self.cfg['enabled'])

    def update_style(self, on):
        self.btn.setText("自动校准运行中 (点击停止)" if on else "启用自动校准")
        self.btn.setStyleSheet("background: #2D5A27; color: white; font-weight: bold; border-radius: 4px;" if on else "font-weight: bold;")

    def toggle_sync(self, c):
        self.cfg['enabled'] = c
        self.update_style(c)

    def closeEvent(self, event):
        global _ui_inst
        _ui_inst = None
        super().closeEvent(event)

# ==========================================
# 4. 生命周期管理
# ==========================================

_timer = None
_ui_inst = None

def start_plugin():
    global _timer
    main_win = substance_painter.ui.get_main_window()
    if not main_win:
        QtCore.QTimer.singleShot(1000, start_plugin)
        return
    
    # 预防性清理菜单
    remove_menu()
    
    action = main_win.menuBar().addAction("映射校准助手")
    action.setObjectName("MappingHelperAction")
    action.triggered.connect(show_ui)
    
    # 初始化定时器
    _timer = QtCore.QTimer()
    _timer.timeout.connect(run_sync)
    _timer.start(200)
    sp_logging.info(">>> 映射校准助手已启用")

def remove_menu():
    main_win = substance_painter.ui.get_main_window()
    if not main_win: return
    for a in main_win.menuBar().actions():
        if a.objectName() == "MappingHelperAction" or a.text() == "映射校准助手":
            main_win.menuBar().removeAction(a)
            a.deleteLater()

def close_plugin():
    """彻底销毁资源，防止工程关闭或重载时崩溃"""
    global _timer, _ui_inst
    
    if _timer:
        _timer.stop()
        try: _timer.timeout.disconnect()
        except: pass
        _timer.deleteLater()
        _timer = None
    
    if _ui_inst and shiboken.isValid(_ui_inst):
        _ui_inst.close()
        _ui_inst.deleteLater()
    _ui_inst = None
    
    remove_menu()
    sp_logging.info(">>> 映射校准助手已关闭")

def show_ui():
    global _ui_inst
    if _ui_inst is not None and not shiboken.isValid(_ui_inst):
        _ui_inst = None
    if _ui_inst is None:
        _ui_inst = AlignControl()
    _ui_inst.show()
    _ui_inst.raise_()

if __name__ == "__main__":
    start_plugin()