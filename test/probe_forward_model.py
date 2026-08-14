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
    lines.append("orig rows=%s" % orig.rowCount())

    # Signal receivers on the view
    for sig in ("doubleClicked(QModelIndex)", "activated(QModelIndex)",
                "clicked(QModelIndex)", "customContextMenuRequested(QPoint)"):
        try:
            n = view.receivers(getattr(QtCore, "SIGNAL")(sig))
            lines.append("view receivers %s = %s" % (sig, n))
        except Exception as exc:
            lines.append("receivers %s err %s" % (sig, exc))

    # Mime/drag support of the source model
    idx = orig.index(0, 0)
    try:
        lines.append("orig dragActions=%s supportedActions=%s" % (
            orig.supportedDragActions(), orig.flags(idx)))
    except Exception as exc:
        lines.append("drag info err: %s" % exc)
    try:
        mime = orig.mimeData([idx])
        lines.append("mime formats=%s data len=%s" % (
            mime.formats() if mime else None,
            len(bytes(mime.data("application/x-substance-resource"))) if mime and mime.hasFormat("application/x-substance-resource") else 0))
    except Exception as exc:
        lines.append("mime err: %s" % exc)

    # Check what roles carry meaningful data (sample first 3 rows)
    for r in range(3):
        mi = orig.index(r, 0)
        roles = []
        for role in list(range(QtCore.Qt.UserRole + 1)) + [QtCore.Qt.DisplayRole,
                    QtCore.Qt.DecorationRole, QtCore.Qt.ToolTipRole,
                    QtCore.Qt.StatusTipRole, QtCore.Qt.AccessibleTextRole,
                    QtCore.Qt.UserRole, QtCore.Qt.UserRole + 1, QtCore.Qt.UserRole + 2,
                    QtCore.Qt.UserRole + 3, QtCore.Qt.UserRole + 4, QtCore.Qt.UserRole + 5]:
            try:
                v = orig.data(mi, role)
            except Exception:
                v = None
            if v is not None:
                roles.append((role, type(v).__name__, str(v)[:30]))
        lines.append("row %d roles: %s" % (r, roles))

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
