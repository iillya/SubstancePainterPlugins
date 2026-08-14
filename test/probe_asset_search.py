import base64
import http.client
import json
import os
import subprocess
import sys
import time

PAINTER = r"C:\Program Files\Adobe\Adobe Substance 3D Painter\Adobe Substance 3D Painter.exe"
PORT = 60041


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
    time.sleep(5)

    code = r'''
from PySide6 import QtWidgets, QtCore
app = QtWidgets.QApplication.instance()
lines = []
for w in app.allWidgets():
    cls = w.metaObject().className()
    name = w.objectName()
    if isinstance(w, QtWidgets.QLineEdit) or "search" in cls.lower() or "search" in name.lower() or "filter" in cls.lower() or "filter" in name.lower():
        parent_chain = []
        p = w.parent()
        depth = 0
        while p is not None and depth < 8:
            parent_chain.append("%s(%s)" % (p.metaObject().className(), p.objectName()))
            p = p.parent()
            depth += 1
        lines.append("W %s | obj=%s | text=%r | parents: %s" % (cls, name, getattr(w, "text", lambda: "")()[:40], " <- ".join(parent_chain)))
lines.append("--- QQuickWidget count ---")
qcw = [w for w in app.allWidgets() if "Quick" in w.metaObject().className()]
lines.append(str(len(qcw)))
for w in qcw[:20]:
    lines.append("QW %s | obj=%s" % (w.metaObject().className(), w.objectName()))
raise RuntimeError("PROBE:" + "\n".join(lines))
'''
    # Use a tiny helper so exceptions surface as strings
    status, data = exec_py(code, timeout=60)
    text = data.decode("utf-8", errors="replace")
    log("status=%s" % status)
    start = text.find("PROBE:")
    if start >= 0:
        print(text[start + 6:], flush=True)
    else:
        print(text[:2000], flush=True)

    proc.terminate()
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
