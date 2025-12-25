import substance_painter.ui
import substance_painter.logging as sp_logging
from PySide6 import QtCore, QtWidgets, QtGui
import shiboken6 as shiboken

# --- 1. 全局配置存储 ---
if not hasattr(QtCore, '_auto_align_cfg'):
    QtCore._auto_align_cfg = {
        '3A': 1, '3S': 0, 
        '2A': 3, '2S': 2,
        'enabled': True,  # 修改点 1：默认设置为 True
        'last_view': None 
    }

# UI 显示文本与 Painter 内部索引对应关系
ALIGN_ITEMS = ["镜头", "切线|Wrap包裹", "切线|平面", "UV"]
SPACE_ITEMS = ["物体", "视图", "纹理"]

# --- 2. 核心校准逻辑 (限定视窗范围) ---
def run_sync():
    cfg = QtCore._auto_align_cfg
    if not cfg['enabled']: return
    
    try:
        # A. 获取鼠标当前下方的控件
        pos = QtGui.QCursor.pos()
        widget = QtWidgets.QApplication.widgetAt(pos)
        
        # 安全检查：控件是否存在且未被销毁
        if not widget or not shiboken.isValid(widget):
            return
        
        view_type = None
        curr = widget
        # 向上溯源寻找 Painter 特有的视窗容器名称
        # Viewer3D: 3D视窗 | TextureViewer: 2D视窗
        for _ in range(8):
            if not curr: break
            name = curr.objectName()
            if name == "Viewer3D": 
                view_type = "3D"
                break
            if name == "TextureViewer": 
                view_type = "2D"
                break
            curr = curr.parentWidget()
        
        # B. 逻辑判定：【只有】在 3D 或 2D 窗口内才执行校准
        if view_type:
            prefix = "3" if view_type == "3D" else "2"
            target_a = cfg[f'{prefix}A']
            target_s = cfg[f'{prefix}S']

            main_win = substance_painter.ui.get_main_window()
            tool_panel = main_win.findChild(QtWidgets.QWidget, "Tool")
            
            if tool_panel and shiboken.isValid(tool_panel):
                combos = tool_panel.findChildren(QtWidgets.QComboBox)
                
                for cb in combos:
                    if not shiboken.isValid(cb) or not cb.isVisible(): 
                        continue
                    
                    obj_name = cb.objectName().lower()
                    
                    # --- 同步校准 (Alignment) ---
                    if "alignment" in obj_name:
                        if cb.currentIndex() != target_a:
                            old_idx = cb.currentIndex()
                            cb.setCurrentIndex(target_a)
                            cb.activated.emit(target_a) # 发送信号通知 Painter 引擎刷新
                            sp_logging.info(f"[助手] {view_type}视窗校准修正: {old_idx} -> {target_a}")
                        continue

                    # --- 同步间距 (Size Space) ---
                    if "size_space" in obj_name:
                        if cb.currentIndex() != target_s:
                            old_idx = cb.currentIndex()
                            cb.setCurrentIndex(target_s)
                            cb.activated.emit(target_s)
                            sp_logging.info(f"[助手] {view_type}视窗间距修正: {old_idx} -> {target_s}")
                
                cfg['last_view'] = view_type
    except Exception:
        pass

# --- 3. 插件 UI 面板类 ---
class AlignControl(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(substance_painter.ui.get_main_window())
        self.setWindowTitle("映射校准助手")
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool)
        self.setMinimumWidth(280)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)

        self.cfg = QtCore._auto_align_cfg
        layout = QtWidgets.QVBoxLayout(self)

        def make_group(title, a_key, s_key):
            layout.addWidget(QtWidgets.QLabel(f"<b>{title}</b>"))
            row1 = QtWidgets.QHBoxLayout()
            row1.addWidget(QtWidgets.QLabel("校准"))
            cb_a = QtWidgets.QComboBox()
            cb_a.addItems(ALIGN_ITEMS)
            cb_a.setCurrentIndex(self.cfg[a_key])
            cb_a.activated.connect(lambda i: self.cfg.update({a_key: i}))
            row1.addWidget(cb_a, 1)
            layout.addLayout(row1)

            row2 = QtWidgets.QHBoxLayout()
            row2.addWidget(QtWidgets.QLabel("间距大小"))
            cb_s = QtWidgets.QComboBox()
            cb_s.addItems(SPACE_ITEMS)
            cb_s.setCurrentIndex(self.cfg[s_key])
            cb_s.activated.connect(lambda i: self.cfg.update({s_key: i}))
            row2.addWidget(cb_s, 1)
            layout.addLayout(row2)
            layout.addSpacing(10)

        make_group("[ 3D 视图预设 ]", '3A', '3S')
        make_group("[ 2D 视图预设 ]", '2A', '2S')

        self.btn = QtWidgets.QPushButton()
        self.btn.setCheckable(True)
        self.btn.setChecked(self.cfg['enabled'])
        self.btn.setFixedHeight(35)
        self.btn.toggled.connect(self.toggle_sync)
        layout.addWidget(self.btn)
        self.update_btn_style(self.cfg['enabled'])

    def update_btn_style(self, on):
        if on:
            self.btn.setText("自动校准中 (点击停止)")
            self.btn.setStyleSheet("background-color: #2D5A27; color: white; font-weight: bold; border-radius: 4px;")
        else:
            self.btn.setText("启用自动校准")
            self.btn.setStyleSheet("border-radius: 4px;")

    def toggle_sync(self, checked):
        self.cfg['enabled'] = checked
        self.cfg['last_view'] = None 
        self.update_btn_style(checked)
        start_timer() if checked else stop_timer()

# --- 4. 生命周期管理 ---
_timer = None
_ui_inst = None
PLUGIN_NAME = "映射校准助手"

def start_timer():
    global _timer
    if _timer is None:
        _timer = QtCore.QTimer()
        _timer.timeout.connect(run_sync)
    if not _timer.isActive():
        _timer.start(200)
    sp_logging.info("[助手] 校准引擎已启用")

def stop_timer():
    global _timer
    if _timer:
        _timer.stop()
    sp_logging.info("[助手] 校准引擎已停止")

def show_ui():
    global _ui_inst
    if _ui_inst and not shiboken.isValid(_ui_inst):
        _ui_inst = None
    if _ui_inst is None:
        _ui_inst = AlignControl()
    _ui_inst.show()
    _ui_inst.raise_()

def start_plugin():
    main_win = substance_painter.ui.get_main_window()
    if not main_win:
        QtCore.QTimer.singleShot(1000, start_plugin)
        return
    
    menu_bar = main_win.menuBar()
    for action in menu_bar.actions():
        if action.text() == PLUGIN_NAME:
            menu_bar.removeAction(action)
    
    action = menu_bar.addAction(PLUGIN_NAME)
    action.triggered.connect(show_ui)
    
    # 修改点 2：强制开启逻辑，确保软件启用即激活监测
    QtCore._auto_align_cfg['enabled'] = True
    start_timer()
        
    sp_logging.info(f">>> {PLUGIN_NAME}已加载并默认开启")

def close_plugin():
    global _timer, _ui_inst
    stop_timer()
    if _timer:
        try: _timer.timeout.disconnect()
        except: pass
        _timer = None

    if _ui_inst and shiboken.isValid(_ui_inst):
        _ui_inst.close()
        _ui_inst = None
    
    main_win = substance_painter.ui.get_main_window()
    if main_win:
        menu_bar = main_win.menuBar()
        for action in menu_bar.actions():
            if action.text() == PLUGIN_NAME:
                menu_bar.removeAction(action)
                action.deleteLater() # 彻底清理
    
    sp_logging.info(f">>> {PLUGIN_NAME}已彻底关闭并销毁")

if __name__ == "__main__":
    start_plugin()