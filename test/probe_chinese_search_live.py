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
    lines.append("search=%s view=%s" % (search is not None, view is not None))
    if search is None or view is None:
        with open(r"C:\Users\liuwenbo\AppData\Local\Temp\sp_probe_out.txt", "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        return

    # Is our ChineseAssetSearch attached?
    kids = view.findChildren(QtCore.QObject, "sp_chinese_asset_search")
    lines.append("chinese search attached: %s" % len(kids))
    for k in kids:
        lines.append("  child: %s parent=%s" % (cls(k), cls(k.parent())))

    # Check plugin menu presence (translation plugin loaded?)
    main_win = None
    for w in app.allWidgets():
        if isinstance(w, QtWidgets.QMainWindow):
            main_win = w
            break
    menus = []
    if main_win is not None and main_win.menuBar() is not None:
        for a in main_win.menuBar().actions():
            menus.append(a.text())
    lines.append("menus: %s" % menus)

    orig = view.model()
    lines.append("orig rows=%s model=%s" % (orig.rowCount(), cls(orig)))

    def snapshot(tag):
        m = view.model()
        try:
            rows = m.rowCount()
        except Exception:
            rows = -1
        lines.append("%s -> model=%s rows=%s text=%r" % (tag, cls(m), rows, search.text()))
        if rows > 0 and rows <= 10:
            for r in range(rows):
                idx = m.index(r, 0)
                lines.append("    %d: %r" % (r, str(m.data(idx, QtCore.Qt.DisplayRole))[:50]))

    search.setText("\u91d1\u5c5e")
    app.processEvents()
    time.sleep(1.2)
    snapshot("after '金属'")

    search.setText("\u62c9\u4e1d\u91d1\u5c5e")
    app.processEvents()
    time.sleep(1.2)
    snapshot("after '拉丝金属'")

    search.setText("")
    app.processEvents()
    time.sleep(1.0)
    snapshot("after clear")

    search.setText("metal")
    app.processEvents()
    time.sleep(1.0)
    snapshot("after 'metal'")
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
    time.sleep(6)

    status, data = exec_py(PROBE_CODE, timeout=120)
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
