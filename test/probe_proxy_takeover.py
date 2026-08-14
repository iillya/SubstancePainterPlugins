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

    search = None
    view = None
    for w in app.allWidgets():
        if isinstance(w, QtWidgets.QLineEdit) and w.objectName() == "search_field":
            search = w
        if isinstance(w, QtWidgets.QAbstractItemView) and w.objectName() == "resources":
            view = w

    orig = view.model()
    for _ in range(30):
        if orig.rowCount() > 0:
            break
        app.processEvents()
        time.sleep(1)
    lines.append("orig initial rows=%s" % orig.rowCount())

    class Proxy(QtCore.QSortFilterProxyModel):
        def __init__(self):
            super().__init__()
            self.setDynamicSortFilter(True)
        def filterAcceptsRow(self, source_row, source_parent):
            return super().filterAcceptsRow(source_row, source_parent)

    proxy = Proxy()
    proxy.setSourceModel(orig)
    view.setModel(proxy)
    app.processEvents()
    time.sleep(0.6)
    lines.append("after proxy: view model=%s proxy rows=%s orig rows=%s" % (
        cls(view.model()), proxy.rowCount(), orig.rowCount()))

    # English input: does SP drive the proxy filter, or orig?
    search.setText("metal")
    app.processEvents()
    time.sleep(0.8)
    lines.append("after 'metal': proxy rows=%s orig rows=%s proxyRegex=%r" % (
        proxy.rowCount(), orig.rowCount(), proxy.filterRegularExpression().pattern()))

    # Chinese input
    search.setText("\u91d1\u5c5e")
    app.processEvents()
    time.sleep(0.8)
    lines.append("after '金属': proxy rows=%s orig rows=%s proxyRegex=%r" % (
        proxy.rowCount(), orig.rowCount(), proxy.filterRegularExpression().pattern()))

    # Clear
    search.setText("")
    app.processEvents()
    time.sleep(0.8)
    lines.append("after clear: proxy rows=%s orig rows=%s" % (proxy.rowCount(), orig.rowCount()))

    # Check displayed rows come from source (role passthrough)
    idx = proxy.index(0, 0)
    src = proxy.mapToSource(idx)
    lines.append("proxy[0] disp=%r deco=%s srcRow=%s" % (
        str(proxy.data(idx, QtCore.Qt.DisplayRole))[:50],
        type(proxy.data(idx, QtCore.Qt.DecorationRole)).__name__,
        src.row()))

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
    time.sleep(3)
    status, data = exec_py(PROBE_CODE, timeout=90)
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
