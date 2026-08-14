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

    # Build our own model with a few test rows
    ours = QtGui.QStandardItemModel()
    ours.appendRow(QtGui.QStandardItem("Test Asset A"))
    ours.appendRow(QtGui.QStandardItem("Test Asset B"))

    # Swap out
    view.setModel(ours)
    app.processEvents()
    time.sleep(0.6)
    lines.append("after swap: view model=%s ours rows=%s orig rows=%s" % (
        cls(view.model()), ours.rowCount(), orig.rowCount()))

    # Simulate Chinese input while our model is active (SP would filter orig, but view shows ours)
    search.setText("\u91d1\u5c5e")
    app.processEvents()
    time.sleep(0.6)
    lines.append("after chinese input: view model=%s ours rows=%s orig rows=%s" % (
        cls(view.model()), ours.rowCount(), orig.rowCount()))

    # Swap back
    view.setModel(orig)
    app.processEvents()
    time.sleep(0.8)
    lines.append("after restore: view model=%s orig rows=%s" % (cls(view.model()), orig.rowCount()))

    # Now clear search and test native filtering still works
    search.setText("")
    app.processEvents()
    time.sleep(0.8)
    lines.append("after clear+restore: orig rows=%s" % orig.rowCount())
    search.setText("metal")
    app.processEvents()
    time.sleep(0.8)
    lines.append("after 'metal' (native path): orig rows=%s" % orig.rowCount())

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
