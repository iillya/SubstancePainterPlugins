import base64
import http.client
import json
import os
import subprocess
import sys
import time

PAINTER = r"C:\Program Files\Adobe\Adobe Substance 3D Painter\Adobe Substance 3D Painter.exe"
PORT = 60041
OUT = r"C:\Users\liuwenbo\AppData\Local\Temp\sp_probe_out.txt"
SAMPLE = "file:///C:/Users/liuwenbo/AppData/Local/Temp/sp_exit_test/PreviewSphere.spp"


def log(msg):
    print("[PROBE]", msg, flush=True)


def exec_py(code, timeout=120):
    payload = json.dumps({"python": base64.b64encode(code.encode("utf-8")).decode("utf-8")})
    conn = http.client.HTTPConnection("localhost", PORT, timeout=timeout)
    conn.request("POST", "/run.json", payload,
                 {"Content-type": "application/json", "Accept": "application/json"})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def exec_js(code, timeout=120):
    payload = json.dumps({"js": base64.b64encode(code.encode("utf-8")).decode("utf-8")})
    conn = http.client.HTTPConnection("localhost", PORT, timeout=timeout)
    conn.request("POST", "/run.json", payload,
                 {"Content-type": "application/json", "Accept": "application/json"})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


PROBE_CODE = r'''
def main():
    import time
    from PySide6 import QtWidgets, QtCore, QtGui
    app = QtWidgets.QApplication.instance()
    lines = []

    def cls(w):
        try:
            return w.metaObject().className()
        except Exception:
            return "?"

    # Ensure assets dock is visible
    dock = None
    search = None
    view = None
    for w in app.allWidgets():
        if isinstance(w, QtWidgets.QDockWidget) and w.objectName() == "NewShelf":
            dock = w
        if isinstance(w, QtWidgets.QLineEdit) and w.objectName() == "search_field":
            search = w
        if isinstance(w, QtWidgets.QAbstractItemView) and w.objectName() == "resources":
            view = w
    if dock is not None:
        dock.show()
        dock.raise_()
    app.processEvents()

    orig = view.model()
    for _ in range(30):
        if orig.rowCount() > 0:
            break
        app.processEvents()
        time.sleep(1)
    lines.append("orig rows=%s view visible=%s" % (orig.rowCount(), view.isVisible()))

    def layer_count():
        import substance_painter.layerstack as ls
        import substance_painter.textureset as ts
        try:
            stack = ts.get_active_stack()
            return len(ls.get_root_layer_nodes(stack))
        except Exception as exc:
            return -1

    def layer_state(tag):
        import substance_painter.layerstack as ls
        import substance_painter.textureset as ts
        try:
            stack = ts.get_active_stack()
            nodes = ls.get_root_layer_nodes(stack)
            return "%s: %d layers -> %s" % (tag, len(nodes),
                [str(n.get_type()).split('.')[-1] for n in nodes])
        except Exception as exc:
            return "%s: ERR %s" % (tag, exc)

    undo_view = None
    for w in app.allWidgets():
        if isinstance(w, QtWidgets.QUndoView) or w.objectName() == "history":
            undo_view = w
            break
    def undo_rows(tag):
        if undo_view is None:
            return "%s: no undo view" % tag
        try:
            m = undo_view.model()
            return "%s: undo rows=%s" % (tag, m.rowCount())
        except Exception as exc:
            return "%s: undo ERR %s" % (tag, exc)

    # Install an event spy on the viewport to confirm synthetic clicks arrive
    seen = []
    class Spy(QtCore.QObject):
        def eventFilter(self, obj, ev):
            if ev.type() in (QtCore.QEvent.Type.MouseButtonPress,
                             QtCore.QEvent.Type.MouseButtonRelease,
                             QtCore.QEvent.Type.MouseButtonDblClick):
                seen.append((ev.type().name, obj.__class__.__name__))
            return False
    spy = Spy()
    view.viewport().installEventFilter(spy)

    # Select a PAINT layer so double-clicking a material creates a new layer
    import substance_painter.layerstack as ls
    import substance_painter.textureset as ts
    stack = ts.get_active_stack()
    roots = ls.get_root_layer_nodes(stack)
    target = None
    for n in roots:
        try:
            if isinstance(n, ls.PaintLayerNode):
                target = n
                break
        except Exception:
            pass
    if target is None:
        # fall back to first node but report
        target = roots[0] if roots else None
    lines.append("selected layer: %s (%s)" % (
        target.get_name() if target else "None",
        target.get_type() if target else "-"))
    if target is not None:
        ls.set_selected_nodes([target])
    app.processEvents()
    time.sleep(0.5)

    lines.append(layer_state("initial"))
    lines.append(undo_rows("initial"))

    def dclick(index, tag):
        rect = view.visualRect(index)
        if rect.width() <= 0:
            lines.append("%s: bad rect %s" % (tag, rect))
            return
        seen.clear()
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent, QPointF
        pos = rect.center()
        def ev(t, buttons, button):
            return QMouseEvent(t, QPointF(pos), button, buttons, QtCore.Qt.NoModifier)
        vp = view.viewport()
        QtCore.QCoreApplication.sendEvent(
            vp, ev(QEvent.Type.MouseButtonPress, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton))
        QtCore.QCoreApplication.sendEvent(
            vp, ev(QEvent.Type.MouseButtonRelease, QtCore.Qt.NoButton, QtCore.Qt.LeftButton))
        QtCore.QCoreApplication.sendEvent(
            vp, ev(QEvent.Type.MouseButtonDblClick, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton))
        QtCore.QCoreApplication.sendEvent(
            vp, ev(QEvent.Type.MouseButtonPress, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton))
        QtCore.QCoreApplication.sendEvent(
            vp, ev(QEvent.Type.MouseButtonRelease, QtCore.Qt.NoButton, QtCore.Qt.LeftButton))
        app.processEvents()
        time.sleep(1.5)
        app.processEvents()
        lines.append("%s: events=%s | %s | %s" % (tag, seen, layer_state("after"), undo_rows("after")))
        try:
            lines.append("%s: currentIndex row=%s" % (tag, view.currentIndex().row()))
        except Exception:
            pass

    # Native baseline: type "metal", double click first result
    search.setText("metal")
    app.processEvents()
    time.sleep(0.8)
    lines.append("native metal rows=%s first=%r" % (
        orig.rowCount(), str(orig.data(orig.index(0, 0), QtCore.Qt.DisplayRole))))
    dclick(orig.index(0, 0), "native dclick")
    search.setText("")
    app.processEvents()
    time.sleep(0.8)
    lines.append(layer_state("after clear"))

    # Forwarding model: keep search empty so orig stays 258
    class ForwardModel(QtCore.QAbstractListModel):
        def __init__(self, source, rows):
            super().__init__()
            self.src = source
            self.rows = rows
        def rowCount(self, parent=QtCore.QModelIndex()):
            return 0 if parent.isValid() else len(self.rows)
        def _src_index(self, row):
            return self.src.index(self.rows[row], 0)
        def data(self, index, role=QtCore.Qt.DisplayRole):
            if not index.isValid() or index.row() >= len(self.rows):
                return None
            return self.src.data(self._src_index(index.row()), role)
        def flags(self, index):
            return self.src.flags(self._src_index(index.row()))
        def supportedDragActions(self):
            return self.src.supportedDragActions()
        def mimeData(self, indexes):
            src_indexes = [self._src_index(i.row()) for i in indexes if i.isValid()]
            return self.src.mimeData(src_indexes)
        def mimeTypes(self):
            return self.src.mimeTypes()

    fwd = ForwardModel(orig, [1])  # only "Metal Brushed" (orig row 1)
    view.setModel(fwd)
    app.processEvents()
    time.sleep(0.6)
    lines.append("fwd rows=%s orig rows=%s disp=%r" % (
        fwd.rowCount(), orig.rowCount(),
        str(fwd.data(fwd.index(0, 0), QtCore.Qt.DisplayRole))))
    dclick(fwd.index(0, 0), "fwd dclick (Metal Brushed)")

    # restore
    view.setModel(orig)
    search.setText("")
    app.processEvents()
    time.sleep(0.8)
    lines.append("restored rows=%s | %s" % (orig.rowCount(), layer_state("restored")))

    with open(r"C:\Users\liuwenbo\AppData\Local\Temp\sp_probe_out.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

main()
'''


def main():
    proc = subprocess.Popen([PAINTER, "--enable-remote-scripting"], cwd=os.path.dirname(PAINTER))
    log("pid=%d" % proc.pid)
    ready = False
    deadline = time.time() + 180
    while time.time() < deadline:
        if proc.poll() is not None:
            log("exited early code=%s" % proc.returncode)
            return 1
        try:
            status, data = exec_js("alg.version.painter", timeout=5)
            if status == 200 and b"error" not in data:
                ready = True
                break
        except Exception:
            time.sleep(2)
    if not ready:
        log("not ready")
        proc.terminate()
        return 1
    log("ready")

    status, data = exec_js("alg.project.open('%s')" % SAMPLE, timeout=300)
    log("open project: %s %r" % (status, data[:150]))
    time.sleep(15)

    status, data = exec_py(PROBE_CODE, timeout=180)
    log("probe status=%s data=%r" % (status, data[:300]))
    if os.path.exists(OUT):
        with open(OUT, "r", encoding="utf-8") as fh:
            print(fh.read(), flush=True)
    else:
        log("no output file")

    proc.terminate()
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
