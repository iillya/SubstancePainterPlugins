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

    import substance_painter.layerstack as ls
    import substance_painter.textureset as ts
    stack = ts.get_active_stack()

    # Find or create a fill layer
    fill = None
    def walk(nodes):
        nonlocal fill
        for n in nodes:
            if fill is not None:
                return
            if isinstance(n, ls.FillLayerNode):
                fill = n
                return
            try:
                walk(n.children() if hasattr(n, "children") else [])
            except Exception:
                pass
    walk(ls.get_root_layer_nodes(stack))
    if fill is None:
        try:
            fill = ls.insert_fill(stack, ls.InsertPosition.Above, parent=None)
            lines.append("created fill layer")
        except Exception as exc:
            lines.append("create fill ERR: %s" % exc)
    if fill is None:
        with open(r"C:\Users\liuwenbo\AppData\Local\Temp\sp_probe_out.txt", "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        return
    ls.set_selected_nodes([fill])
    app.processEvents()
    time.sleep(0.8)
    lines.append("selected fill: %s" % fill.get_name())

    def snapshot(tag):
        try:
            effs = fill.get_effects()
            params = []
            for e in effs:
                try:
                    params.append((type(e).__name__, e.get_parameters()))
                except Exception as exc:
                    params.append((type(e).__name__, "ERR %s" % exc))
            lines.append("%s: effects=%s" % (tag, params))
        except Exception as exc:
            lines.append("%s: snap ERR %s" % (tag, exc))

    snapshot("before")

    def dclick(index, tag):
        rect = view.visualRect(index)
        if rect.width() <= 0:
            lines.append("%s: bad rect" % tag)
            return
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent, QPointF
        pos = rect.center()
        def ev(t, buttons, button):
            return QMouseEvent(t, QPointF(pos), button, buttons, QtCore.Qt.NoModifier)
        vp = view.viewport()
        QtCore.QCoreApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonPress, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton))
        QtCore.QCoreApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonRelease, QtCore.Qt.NoButton, QtCore.Qt.LeftButton))
        QtCore.QCoreApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonDblClick, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton))
        QtCore.QCoreApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonPress, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton))
        QtCore.QCoreApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonRelease, QtCore.Qt.NoButton, QtCore.Qt.LeftButton))
        app.processEvents()
        time.sleep(2.0)
        app.processEvents()
        lines.append("%s dclicked %r" % (tag, str(orig.data(index, QtCore.Qt.DisplayRole))))
        snapshot("after " + tag)

    # Native baseline
    search.setText("metal")
    app.processEvents()
    time.sleep(0.8)
    lines.append("native rows=%s" % orig.rowCount())
    dclick(orig.index(0, 0), "native")
    search.setText("")
    app.processEvents()
    time.sleep(1.0)

    # Forwarding model
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
            return self.src.mimeData([self._src_index(i.row()) for i in indexes if i.isValid()])
        def mimeTypes(self):
            return self.src.mimeTypes()

    fwd = ForwardModel(orig, [1])  # orig row 1
    view.setModel(fwd)
    app.processEvents()
    time.sleep(0.5)
    dclick(fwd.index(0, 0), "fwd")
    view.setModel(orig)
    search.setText("")
    app.processEvents()

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
    log("open: %s %r" % (status, data[:100]))
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
