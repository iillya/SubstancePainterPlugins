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
    from PySide6 import QtWidgets, QtCore
    app = QtWidgets.QApplication.instance()
    lines = []

    targets = {}
    for w in app.allWidgets():
        c = w.metaObject().className()
        if c in ("Alg::NewShelf", "Alg::ResourceListView", "Alg::QueryItemWidget",
                 "Alg::Breadcrumb", "Alg::IconFiltersView"):
            targets.setdefault(c, w)

    for cname, w in targets.items():
        lines.append("== %s (%s) ==" % (cname, w.objectName()))
        mo = w.metaObject()
        sigs = []
        for i in range(mo.methodCount()):
            try:
                sigs.append(str(mo.method(i).methodSignature()))
            except Exception:
                pass
        keep = [s for s in sigs if any(k in s.lower() for k in
                ("filter", "search", "query", "match", "select", "apply", "set",
                 "clear", "text", "update", "refresh", "crawl", "load"))]
        lines.append("meta methods (%d):" % len(keep))
        for s in keep:
            lines.append("  " + s)
        props = []
        for i in range(mo.propertyCount()):
            try:
                props.append(str(mo.property(i).name()))
            except Exception:
                pass
        lines.append("properties: %s" % sorted(props))

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
