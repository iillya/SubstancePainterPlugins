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
    print("[INTRO]", msg, flush=True)


def exec_python(code, timeout=120):
    payload = json.dumps({"python": base64.b64encode(code.encode("utf-8")).decode("utf-8")})
    conn = http.client.HTTPConnection("localhost", PORT, timeout=timeout)
    conn.request("POST", "/run.json", payload,
                 {"Content-type": "application/json", "Accept": "application/json"})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def main():
    proc = subprocess.Popen([PAINTER, "--enable-remote-scripting"], cwd=os.path.dirname(PAINTER))
    ready = False
    deadline = time.time() + 180
    while time.time() < deadline:
        if proc.poll() is not None:
            log("Painter exited early")
            return 1
        try:
            status, _ = exec_python('1+1', timeout=5)
            if status == 200:
                ready = True
                break
        except Exception:
            time.sleep(2)
    if not ready:
        log("not ready")
        proc.kill()
        return 1

    checks = [
        ("python modules", "import substance_painter; repr(sorted(m for m in dir(substance_painter) if not m.startswith('_')))"),
        ("python create doc", "import substance_painter.project as p; str(p.create.__doc__)"),
        ("js alg keys", "substance_painter.js.evaluate(\"JSON.stringify(Object.keys(alg).sort())\")"),
        ("js ui keys", "substance_painter.js.evaluate(\"JSON.stringify(Object.keys(alg.ui).sort())\")"),
        ("js resources", "substance_painter.js.evaluate(\"JSON.stringify(alg.resources.findResources('starter_assets','*.obj'))\")"),
    ]
    for name, code in checks:
        try:
            status, data = exec_python(code, timeout=60)
            log("%s -> %s %r" % (name, status, data[:1500]))
        except Exception as exc:
            log("%s -> EXC %r" % (name, exc))

    # close cleanly without saving anything
    log("closing app")
    time.sleep(3)
    proc.terminate()
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
