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
    from PySide6 import QtWidgets, QtCore
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
    mo = orig.metaObject()
    methods = []
    for i in range(mo.methodCount()):
        try:
            methods.append(str(mo.method(i).methodSignature()))
        except Exception:
            pass
    lines.append("NewResourceListModel methods (%d):" % len(methods))
    for mname in methods:
        if any(k in mname.lower() for k in ("filter", "search", "query", "match", "pattern", "text")):
            lines.append("  " + mname)

    mo2 = search.metaObject()
    methods2 = []
    for i in range(mo2.methodCount()):
        try:
            methods2.append(str(mo2.method(i).methodSignature()))
        except Exception:
            pass
    lines.append("SearchFieldLineEdit methods:")
    for mname in methods2:
        if any(k in mname.lower() for k in ("filter", "search", "query", "match", "pattern", "text", "clear")):
            lines.append("  " + mname)

    # Now swap in a Python proxy model and observe whether SP still filters the source
    class Proxy(QtCore.QSortFilterProxyModel):
        def __init__(self):
            super().__init__()
            self.setDynamicSortFilter(True)
        def filterAcceptsRow(self, source_row, source_parent):
            return True

    proxy = Proxy()
    proxy.setSourceModel(orig)
    view.setModel(proxy)
    app.processEvents()
    time.sleep(0.5)
    lines.append("after swap: proxy rows=%s orig rows=%s" % (proxy.rowCount(), orig.rowCount()))

    search.setText("metal")
    app.processEvents()
    time.sleep(0.8)
    lines.append("after 'metal': proxy rows=%s orig rows=%s proxyFilter=%r" % (
        proxy.rowCount(), orig.rowCount(), proxy.filterRegularExpression().pattern()))

    search.setText("\u91d1\u5c5e")
    app.processEvents()
    time.sleep(0.8)
    lines.append("after '金属': proxy rows=%s orig rows=%s proxyFilter=%r" % (
        proxy.rowCount(), orig.rowCount(), proxy.filterRegularExpression().pattern()))

    search.setText("")
    app.processEvents()
    time.sleep(0.8)
    lines.append("after clear: proxy rows=%s orig rows=%s" % (proxy.rowCount(), orig.rowCount()))

    # restore
    view.setModel(orig)
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
    time.sleep(3)
    status, data = exec_py(PROBE_CODE, timeout=90)
    log("probe status=%s data=%r" % (status, data[:400]))
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
