import base64
import ctypes
import http.client
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

PAINTER = r"C:\Program Files\Adobe\Adobe Substance 3D Painter\Adobe Substance 3D Painter.exe"
CRASH_DIR = r"C:\Users\liuwenbo\AppData\Local\CrashDumps"
PORT = 60041
SAMPLE = "file:///C:/Users/liuwenbo/AppData/Local/Temp/sp_exit_test/PreviewSphere.spp"
UIA_DIR = r"C:\Users\liuwenbo\AppData\Local\Temp\sp_ui"

user32 = ctypes.windll.user32
WM_CLOSE = 0x0010


def log(msg):
    print("[TEST]", msg, flush=True)


def http_json(body, timeout=300):
    payload = json.dumps(body)
    conn = http.client.HTTPConnection("localhost", PORT, timeout=timeout)
    conn.request("POST", "/run.json", payload,
                 {"Content-type": "application/json", "Accept": "application/json"})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def exec_js(script, timeout=300):
    return http_json({"js": base64.b64encode(script.encode("utf-8")).decode("utf-8")}, timeout)


def windows_of_pid(pid):
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found


def window_text(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def run_ps1(name, *args):
    ps1 = os.path.join(UIA_DIR, name)
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1] + list(args)
    subprocess.run(cmd, capture_output=True, timeout=120)


def dump_files():
    if not os.path.isdir(CRASH_DIR):
        return set()
    return set(f for f in os.listdir(CRASH_DIR) if f.startswith("Adobe Substance 3D Painter"))


def main():
    baseline = dump_files()
    log("baseline dumps: %d" % len(baseline))

    log("launching Painter with --enable-remote-scripting")
    proc = subprocess.Popen(
        [PAINTER, "--enable-remote-scripting"],
        cwd=os.path.dirname(PAINTER),
    )
    pid = proc.pid
    log("pid=%d" % pid)

    ready = False
    deadline = time.time() + 180
    while time.time() < deadline:
        if proc.poll() is not None:
            log("Painter exited early with code %s" % proc.returncode)
            return 1
        try:
            status, data = exec_js("alg.version.painter", timeout=5)
            if status == 200 and b"error" not in data:
                ready = True
                log("remote API ready: %r" % data[:100])
                break
        except Exception:
            time.sleep(2)
    if not ready:
        log("remote API not ready in time")
        proc.kill()
        return 1

    status, data = exec_js("alg.project.open('%s')" % SAMPLE, timeout=300)
    log("open project: %s %r" % (status, data[:200]))

    # Wait for the main window title to include the project name
    opened = False
    deadline = time.time() + 60
    while time.time() < deadline:
        for w in windows_of_pid(pid):
            if user32.IsWindowVisible(w) and "PreviewSphere" in window_text(w):
                opened = True
                break
        if opened:
            break
        time.sleep(1)
    log("project window opened: %s" % opened)
    time.sleep(5)

    log("sending WM_CLOSE")
    wins = [w for w in windows_of_pid(pid) if user32.IsWindowVisible(w)]
    for w in wins:
        log("visible window: %r" % window_text(w))
    if wins:
        user32.PostMessageW(wins[0], WM_CLOSE, 0, 0)

    # Wait for either app exit or the save dialog
    dialog_seen = False
    deadline = time.time() + 40
    while time.time() < deadline and proc.poll() is None:
        titles = [window_text(w) for w in windows_of_pid(pid) if user32.IsWindowVisible(w)]
        if len(titles) >= 2 or any(t == "Adobe Substance 3D Painter" for t in titles):
            dialog_seen = True
            break
        time.sleep(0.5)
    log("dialog seen: %s" % dialog_seen)

    if dialog_seen:
        run_ps1("uia_dump.ps1", "-TargetPid", str(pid))
        dump_path = os.path.join(UIA_DIR, "uia_dump_out.txt")
        if os.path.exists(dump_path):
            with open(dump_path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
            log("UIA dump lines: %d" % len(lines))
            interesting = [ln for ln in lines if "Button" in ln or "放弃" in ln or "保存" in ln or "取消" in ln]
            for ln in interesting[:40]:
                log("UIA: %s" % ln)
            if not interesting:
                for ln in lines[:30]:
                    log("UIA: %s" % ln)
        run_ps1("uia_click.ps1", "-TargetPid", str(pid), "-ButtonName", "放弃")
        click_path = os.path.join(UIA_DIR, "uia_click_out.txt")
        if os.path.exists(click_path):
            with open(click_path, "r", encoding="utf-8", errors="replace") as fh:
                log("click result: %s" % fh.read().strip())

    exit_code = None
    deadline = time.time() + 90
    while time.time() < deadline:
        if proc.poll() is not None:
            exit_code = proc.returncode
            break
        time.sleep(1)
    if exit_code is None:
        log("Painter did not exit in time; killing")
        proc.kill()
        return 1

    log("Painter exited with code %s" % exit_code)
    time.sleep(3)

    new_dumps = dump_files() - baseline
    if new_dumps:
        log("FAIL: new crash dumps detected: %s" % sorted(new_dumps))
        return 2
    log("PASS: clean exit, no new crash dump")
    return 0


if __name__ == "__main__":
    sys.exit(main())
