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

    lines.append("search=%s (%s)" % (search is not None, cls(search) if search else "-"))
    lines.append("view=%s (%s)" % (view is not None, cls(view) if view else "-"))
    if search is None or view is None:
        with open(r"C:\Users\liuwenbo\AppData\Local\Temp\sp_probe_out.txt", "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        return

    model = view.model()
    lines.append("initial model=%s rows=%s" % (cls(model), model.rowCount()))

    # Enumerate filter/search related methods on the model
    interesting = [m for m in dir(model) if any(k in m.lower() for k in
                   ("filter", "search", "query", "match", "settext", "pattern", "regex"))]
    lines.append("model filter-ish methods: %s" % sorted(interesting))

    interesting2 = [m for m in dir(search) if any(k in m.lower() for k in
                    ("filter", "search", "query", "match", "pattern", "regex", "clear"))]
    lines.append("search field methods: %s" % sorted(interesting2))

    def snapshot(tag):
        m = view.model()
        rows = -1
        try:
            rows = m.rowCount()
        except Exception:
            pass
        lines.append("%s -> model=%s rows=%s text=%r" % (tag, cls(m), rows, search.text()))

    # 1) English substring
    search.setText("metal")
    app.processEvents()
    time.sleep(0.8)
    snapshot("after 'metal'")
    # sample some rows
    m = view.model()
    sample = []
    for r in range(min(5, m.rowCount())):
        idx = m.index(r, 0)
        sample.append(str(m.data(idx, QtCore.Qt.DisplayRole))[:40])
    lines.append("sample rows: %s" % sample)

    # 2) Chinese
    search.setText("\u91d1\u5c5e")
    app.processEvents()
    time.sleep(0.8)
    snapshot("after '金属'")

    # 3) empty -> restore
    search.setText("")
    app.processEvents()
    time.sleep(0.8)
    snapshot("after clear")

    # 4) uppercase
    search.setText("METAL")
    app.processEvents()
    time.sleep(0.8)
    snapshot("after 'METAL'")
    search.setText("")
    app.processEvents()
    time.sleep(0.8)
    snapshot("final clear")

    # Check proxy chain
    m = view.model()
    chain = []
    cur = m
    for _ in range(6):
        if cur is None:
            break
        chain.append(cls(cur))
        if hasattr(cur, "sourceModel"):
            try:
                cur = cur.sourceModel()
            except Exception:
                break
        else:
            break
    lines.append("view model chain: %s" % " -> ".join(chain))

    # FilterProxyModel tree behavior
    ftv = None
    for w in app.allWidgets():
        if isinstance(w, QtWidgets.QTreeView) and w.objectName() == "filtered_tree_view":
            ftv = w
            break
    if ftv is not None:
        fm = ftv.model()
        lines.append("filtered_tree model=%s rows=%s" % (cls(fm), fm.rowCount()))
        for mname in ("setFilterRegularExpression", "setFilterWildcard", "setFilterFixedString"):
            if hasattr(fm, mname):
                lines.append("  has %s" % mname)

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
