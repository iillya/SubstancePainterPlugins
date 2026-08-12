import base64
import http.client
import json
import os
import subprocess
import sys
import time

PAINTER = r"D:\Steam\steamapps\common\Substance Painter 2021\Adobe Substance 3D Painter.exe"
PORTS = (60041, 6400)


def log(msg):
    print("[2021]", msg, flush=True)


def http_json(port, body, timeout=60):
    payload = json.dumps(body)
    conn = http.client.HTTPConnection("localhost", port, timeout=timeout)
    conn.request("POST", "/run.json", payload,
                 {"Content-type": "application/json", "Accept": "application/json"})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def exec_py(port, code, timeout=60):
    return http_json(port, {"python": base64.b64encode(code.encode("utf-8")).decode("utf-8")}, timeout)


def exec_js(port, code, timeout=60):
    return http_json(port, {"js": base64.b64encode(code.encode("utf-8")).decode("utf-8")}, timeout)


def probe(label, result):
    print("[2021] %s -> %s %s" % (label, result[0], result[1][:600].decode("utf-8", errors="replace")), flush=True)


def main():
    proc = subprocess.Popen([PAINTER, "--enable-remote-scripting"], cwd=os.path.dirname(PAINTER))
    log("pid=%d" % proc.pid)

    port = None
    deadline = time.time() + 240
    while time.time() < deadline:
        if proc.poll() is not None:
            log("exited early code=%s" % proc.returncode)
            return 1
        for candidate in PORTS:
            try:
                status, data = exec_js(candidate, "alg.version.painter", timeout=3)
                if status == 200:
                    port = candidate
                    log("remote ready on port %d: %r" % (candidate, data[:100]))
                    break
            except Exception:
                pass
        if port:
            break
        time.sleep(2)
    if not port:
        log("no remote port found")
        proc.terminate()
        return 1

    probes = [
        ("sp modules", "import substance_painter as sp; raise RuntimeError('MODS:' + repr(sorted(m for m in dir(sp) if not m.startswith('_'))))"),
        ("has layerstack", "import substance_painter as sp; raise RuntimeError('HAS_LS:' + str(hasattr(sp, 'layerstack')))"),
        ("event classes", "import substance_painter.event as e; raise RuntimeError('EV:' + repr(sorted(m for m in dir(e) if m[0].isupper()))))"),
        ("pyside version", "import PySide2; raise RuntimeError('PYSIDE:' + PySide2.__version__)"),
        ("qt version", "import PySide2.QtCore as q; raise RuntimeError('QT:' + q.qVersion())"),
    ]
    for label, code in probes:
        probe(label, exec_py(port, code, timeout=60))

    # Keep the app alive for follow-up tests; tell caller the port/pid
    print("[2021] READY pid=%d port=%d" % (proc.pid, port), flush=True)
    with open(os.path.join(os.environ.get("TEMP", "."), "sp2021_test.txt"), "w") as fh:
        fh.write("%d %d" % (proc.pid, port))
    # wait until the app exits by itself or is closed
    try:
        proc.wait(timeout=600)
    except subprocess.TimeoutExpired:
        proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
