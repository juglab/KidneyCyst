"""Updates the KidneyCyst program code from GitHub releases, without a new download of the whole installation.

A release (tag vX.Y.Z on github.com/juglab/KidneyCyst) carries two files, made by .github/workflows/release.yml:
  kidneycyst-X.Y.Z-py3-none-any.whl   the program code (a few hundred KB)
  version.json                        {"version", "wheel", "base", "notes"}
"base" is the installation generation: Python packages, PyTorch and the model. It is BASE below. A release whose base
is newer than the installed one cannot be applied here ("download the new installation" instead).

Update steps (only for a real installation, never for a dev copy or a test server):
  1. download the wheel into <install>/app/  (the previous wheel moves to <install>/app/previous/)
  2. install it with the bundled uv, --no-deps (PyTorch and the rest stay as they are)
  3. check in a fresh Python that the new version imports; if not, put the previous wheel back
  4. restart the app on the same port and token; the open page reloads by itself
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from . import __version__

BASE = 1                     # bump in a release that needs new Python packages, PyTorch or model (= a new download)
REPO = "juglab/KidneyCyst"
MANIFEST_URL = os.environ.get("KIDNEYCYST_UPDATE_URL") or f"https://github.com/{REPO}/releases/latest/download/version.json"
CHECK_EVERY_S = 24 * 3600

STATE = dict(running=False, done=False, ok=False, step="", error="", version="")


def _vt(v: str) -> tuple:
    out = []
    for p in v.lstrip("v").split("."):
        n = "".join(c for c in p if c.isdigit())
        out.append(int(n) if n else 0)
    return tuple(out + [0] * (3 - len(out)))


def install_folder() -> Path | None:
    """<install>/ when this Python is the installation's own env AND the kidneycyst package comes from it
    (a dev copy runs with PYTHONPATH pointing elsewhere: never update that)."""
    f = Path(sys.prefix).resolve().parent
    pkg = Path(__file__).resolve()
    if not (f / "app").is_dir() or not _uv(f):
        return None
    try:
        pkg.relative_to(Path(sys.prefix).resolve())
    except ValueError:
        return None
    return f


def _uv(f: Path) -> Path | None:
    for n in ("uv.exe", "uv"):
        if (f / "tools" / n).exists():
            return f / "tools" / n
    return None


def _cache_file() -> Path:
    d = Path.home() / ".kidneycyst"
    d.mkdir(exist_ok=True)
    return d / "update_check.json"


def _fetch_manifest(timeout: float = 4.0) -> dict:
    req = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": f"KidneyCyst/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        m = json.loads(r.read().decode("utf-8"))
    if not isinstance(m, dict) or "version" not in m or "wheel" not in m:
        raise ValueError("version.json is incomplete")
    return m


def check(force: bool = False) -> dict:
    """What the app shows. Never raises; offline = nothing to show. Asks GitHub at most once a day."""
    res = dict(current=__version__, managed=install_folder() is not None, latest="", available=False,
               needs_download=False, notes="", error="")
    m = None
    cf = _cache_file()
    try:
        c = json.loads(cf.read_text(encoding="utf-8"))
        if not force and time.time() - c.get("t", 0) < CHECK_EVERY_S and c.get("url") == MANIFEST_URL:
            m = c.get("m")
    except Exception:
        pass
    if m is None:
        try:
            m = _fetch_manifest()
            cf.write_text(json.dumps(dict(t=time.time(), url=MANIFEST_URL, m=m)), encoding="utf-8")
        except Exception as e:                      # offline, firewall, no release yet: say nothing
            res["error"] = f"Could not check for updates ({type(e).__name__})."
            return res
    res["latest"], res["notes"] = str(m["version"]), str(m.get("notes", ""))[:2000]
    if _vt(res["latest"]) > _vt(__version__):
        res["available"] = True
        res["needs_download"] = int(m.get("base", BASE)) > BASE
    return res


def _wheel_url(m: dict) -> str:
    if m.get("wheel_url"):
        return m["wheel_url"]
    base = MANIFEST_URL.rsplit("/", 1)[0]
    if "/releases/latest/download" in base:           # a pinned file of that exact release
        base = f"https://github.com/{REPO}/releases/download/v{m['version']}"
    return f"{base}/{m['wheel']}"


def _installed_version(py: str) -> str:
    r = subprocess.run([py, "-c", "import kidneycyst.webapp, kidneycyst.cli, kidneycyst; print(kidneycyst.__version__)"],
                       capture_output=True, text=True, timeout=180, **_quiet())
    if r.returncode != 0:
        raise RuntimeError(((r.stderr or r.stdout).strip().splitlines() or ["import failed"])[-1])
    return r.stdout.strip().splitlines()[-1]


def _quiet() -> dict:
    return dict(creationflags=0x08000000) if os.name == "nt" else {}     # CREATE_NO_WINDOW: no console flashing


def _pip(f: Path, wheel: Path):
    env = dict(os.environ, UV_CACHE_DIR=str(Path(tempfile.gettempdir()) / "kidneycyst-uv-cache"))
    r = subprocess.run([str(_uv(f)), "pip", "install", "--python", sys.executable, "--no-deps", "--reinstall",
                        "--compile-bytecode", str(wheel)], capture_output=True, text=True, env=env, timeout=600, **_quiet())
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[-400:])


def start(job_running: bool) -> dict:
    if STATE["running"]:
        return dict(ok=True)
    if job_running:
        return dict(error="A detection is running. Update after it has finished.")
    f = install_folder()
    if f is None:
        return dict(error="This copy of KidneyCyst was not started from an installation, so it cannot update itself.")
    STATE.update(running=True, done=False, ok=False, step="Checking the newest version…", error="", version="")
    threading.Thread(target=_update, args=(f,), daemon=True).start()
    return dict(ok=True)


def _update(f: Path):
    app, prev = f / "app", f / "app" / "previous"
    old = sorted(app.glob("kidneycyst-*.whl"))
    try:
        m = _fetch_manifest(timeout=15)
        if int(m.get("base", BASE)) > BASE:
            raise RuntimeError("This version needs a new download of the installation.")
        if _vt(str(m["version"])) <= _vt(__version__):
            raise RuntimeError(f"KidneyCyst {__version__} is already the newest version.")
        STATE["step"] = f"Downloading KidneyCyst {m['version']}…"
        tmp = app / (m["wheel"] + ".part")
        req = urllib.request.Request(_wheel_url(m), headers={"User-Agent": f"KidneyCyst/{__version__}"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as o:
            shutil.copyfileobj(r, o)
        new = app / m["wheel"]
        STATE["step"] = "Installing…"
        prev.mkdir(exist_ok=True)
        for w in prev.glob("*.whl"):
            w.unlink()
        for w in old:
            if w.name != new.name:
                shutil.move(str(w), str(prev / w.name))
        os.replace(tmp, new)
        try:
            _pip(f, new)
            STATE["step"] = "Checking the new version…"
            got = _installed_version(sys.executable)
            if _vt(got) != _vt(str(m["version"])):
                raise RuntimeError(f"installed version reports {got}")
        except Exception as e:                       # roll back to the wheel that was working
            STATE["step"] = "The new version did not work. Putting the previous version back…"
            back = sorted(prev.glob("*.whl"))
            if back:
                _pip(f, back[-1])
                new.unlink(missing_ok=True)
                shutil.move(str(back[-1]), str(app / back[-1].name))
            raise RuntimeError(f"The update to {m['version']} failed and was undone ({e}). KidneyCyst {__version__} "
                               f"is still installed.") from e
        STATE.update(ok=True, version=str(m["version"]), step=f"KidneyCyst {m['version']} installed. Restarting…")
    except Exception as e:
        for t in app.glob("*.part"):
            t.unlink(missing_ok=True)
        msg = str(e) if isinstance(e, RuntimeError) else f"The update could not be downloaded ({type(e).__name__}: {e})."
        STATE.update(ok=False, error=msg, step="")
    finally:
        STATE.update(running=False, done=True)


def restart(port: int, token: str, close_server, remember=None):
    """Start the updated app on the same port/token (the open page reconnects), then end this process."""
    def go():
        time.sleep(0.8)                              # let the last status answer reach the page
        if remember:
            try:
                remember()
            except Exception:
                pass
        try:
            close_server()
        except Exception:
            pass
        env = dict(os.environ, KIDNEYCYST_PORT=str(port), KIDNEYCYST_TOKEN=token, KIDNEYCYST_NO_BROWSER="1",
                   KIDNEYCYST_RESUME="1", KIDNEYCYST_RESTARTED="1")
        kw = dict(close_fds=True, env=env, stdin=subprocess.DEVNULL)
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000   # detached, new group, no window
        else:
            kw["start_new_session"] = True
        out = sys.stdout if hasattr(sys.stdout, "fileno") else None
        try:
            kw["stdout"] = kw["stderr"] = out.fileno() if out else subprocess.DEVNULL
        except Exception:
            kw["stdout"] = kw["stderr"] = subprocess.DEVNULL
        subprocess.Popen([sys.executable, "-m", "kidneycyst.gui"], **kw)
        os._exit(0)
    threading.Thread(target=go, daemon=True).start()
