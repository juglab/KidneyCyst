"""KidneyCyst app: a local web page served by this process (http://127.0.0.1:<port>), opened in the default browser.
Nothing leaves the computer: the server only listens on 127.0.0.1 and every request must carry the session token.

    python -m kidneycyst.webapp      (the desktop icon / Start KidneyCyst does this)

Pages: /            choose folder -> run -> results          (static/index.html)
       /review      one image at a time, brush / lasso      (static/review.html)
       /report      the report page (rebuilt from the current results)
The server exits by itself a few minutes after the last browser tab is closed (no heartbeat) and nothing runs.
"""
from __future__ import annotations

import base64
import collections
import io
import json
import os
import platform
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import numpy as np

STATIC = Path(__file__).with_name("static")
TOKEN = os.environ.get("KIDNEYCYST_TOKEN") or secrets.token_urlsafe(16)   # fixed token: stable link for test sessions
IDLE_EXIT_S = int(os.environ.get("KIDNEYCYST_IDLE_EXIT", "300"))   # 0 = never stop by itself (remote test sessions)
REMOTE = os.environ.get("KIDNEYCYST_REMOTE") == "1"    # browser on another computer (SSH tunnel): no native dialogs,
                                                       # files are downloaded instead of opened on this machine
PROG_RE = re.compile(r"^\[(\d+)/(\d+)\]")


# ---------------------------------------------------------------- state
class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.phase = "idle"            # idle | loading | predicting | finishing | done | error
        self.i = self.n = 0
        self.t0 = self.t_img0 = 0.0
        self.log = collections.deque(maxlen=400)
        self.error = ""
        self.out = ""
        self.current = ""
        self.cancelled = False
        self.where = ""                # "" = this computer, else the other computer's name
        self.xfer = self.xfer_total = 0
        self.slurm_id = self.queue_reason = ""

    def snapshot(self):
        el = time.time() - self.t0 if self.t0 else 0
        left = None
        if self.phase == "predicting" and self.i:
            left = (time.time() - self.t_img0) / self.i * (self.n - self.i)
        from . import cli
        return dict(load=dict(cli.LOAD), running=self.running, phase=self.phase, i=self.i, n=self.n, elapsed=el, left=left,
                    error=self.error, out=self.out, current=self.current, cancelled=self.cancelled,
                    where=self.where, xfer=self.xfer, xfer_total=self.xfer_total, slurm_id=self.slurm_id,
                    queue_reason=self.queue_reason,
                    log=list(self.log)[-60:])


JOB = Job()
STATE = dict(folder="", out="", last_ping=time.time(), sessions={})


class _Tee(io.TextIOBase):
    """Captures what the pipeline prints (plain text, no colour) into the job log and progress."""

    def write(self, s):
        for line in s.splitlines():
            line = re.sub(r"\x1b\[[0-9;]*m", "", line).rstrip()
            if not line:
                continue
            JOB.log.append(line)
            m = PROG_RE.match(line)
            if m:
                if JOB.phase != "predicting":
                    JOB.phase, JOB.t_img0 = "predicting", time.time()
                JOB.i, JOB.n = int(m.group(1)), int(m.group(2))
                JOB.current = line.split("]", 1)[1].split(":", 1)[0].strip()
            elif line.startswith("Loading model"):
                JOB.phase = "loading"
            elif line.startswith("Detection cancelled"):
                JOB.cancelled = True
            elif line.startswith("Processing complete"):
                JOB.phase = "finishing"
        return len(s)

    def isatty(self):
        return False


def _count_tiffs(folder: Path) -> int:
    return sum(1 for p in folder.rglob("*") if p.suffix.lower() in (".tif", ".tiff") and p.is_file())


def _has_results(out) -> bool:
    from .library import has_results
    return has_results(Path(out))


def _out_for(folder: Path) -> Path:
    return folder.parent / f"{folder.name}_kidneycyst"


def _summary(out: Path) -> dict | None:
    if not _has_results(out):
        return None
    import pandas as pd
    from .report import tidy
    d = tidy(pd.read_csv(out / "results.csv", dtype={"well": str}))
    st = d.status.value_counts().to_dict()
    a = d.final_area_um2[d.final_area_um2 > 0]
    n_model = int(((d.status == "auto") & (d.final_area_um2 > 0)).sum())
    cal = {}
    try:
        st_ = json.loads((out / "run_settings.json").read_text(encoding="utf-8"))
        srcs = st_.get("pixel_size_sources", {})
        sizes = st_.get("pixel_sizes_used", {})
        assumed = any(str(k).startswith("default") for k in srcs)
        px = ", ".join(f"{float(k):.4g}" for k in sizes) or "?"
        manual = any(str(k) == "--pixel-size" for k in srcs)
        cal = dict(assumed=assumed, text=(
            f"Unverified calibration: {px} µm/pixel. TIFF metadata is missing; areas in µm² use this default." if assumed
            else f"Pixel size: {px} µm, entered manually. Areas are reported in µm²." if manual
            else f"Pixel size: {px} µm, from TIFF metadata. Areas are reported in µm²."))
    except Exception:
        pass
    run_info = {}
    try:
        run_info = dict(date=st_["date"][:16].replace("T", " "), seconds=st_.get("seconds"), cancelled=st_.get("cancelled", False))
    except Exception:
        pass
    return dict(calibration=cal, run=run_info, n=len(d), with_kidney=int((d.final_area_um2 > 0).sum()), reviewed=int((d.status != "auto").sum()),
                flagged_todo=int((d.flagged & (d.status == "auto")).sum()), median=float(a.median()) if len(a) else None,
                status={k: int(v) for k, v in st.items()}, out=str(out), median_includes_unchecked=n_model,
                has_qupath=any(out.glob("qupath*/project.qpproj")))


def _device_text():
    try:
        import torch
        if torch.cuda.is_available():
            return f"Processing device: NVIDIA GPU ({torch.cuda.get_device_name(0)})."
        if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            return "Processing device: Apple GPU."
    except Exception:
        pass
    return "Processing device: CPU. Processing may be slower than on a supported GPU."


# ---------------------------------------------------------------- native folder picker
def pick_folder() -> str | None:
    sysname = platform.system()
    try:
        if sysname == "Darwin":
            r = subprocess.run(["osascript", "-e", 'POSIX path of (choose folder with prompt "Folder with your TIFF images")'],
                               capture_output=True, text=True, timeout=600)
            return r.stdout.strip() or None
        if sysname == "Windows":
            ps = ("Add-Type -AssemblyName System.Windows.Forms;$d=New-Object System.Windows.Forms.FolderBrowserDialog;"
                  "$d.Description='Folder with your TIFF images';$d.ShowNewFolderButton=$false;"
                  "$f=New-Object System.Windows.Forms.Form;$f.TopMost=$true;"
                  "if($d.ShowDialog($f) -eq 'OK'){Write-Output $d.SelectedPath}")
            r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, text=True,
                               timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return r.stdout.strip() or None
        for cmd in (["zenity", "--file-selection", "--directory"], ["kdialog", "--getexistingdirectory"]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                return r.stdout.strip() or None
            except FileNotFoundError:
                continue
    except Exception:
        pass
    return None


def open_path(p: Path):
    p = str(p)
    if sys.platform.startswith("win"):
        os.startfile(p)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


# ---------------------------------------------------------------- review data
def _current_out() -> str:
    """The open run, named by its results folder (also before detection, when it does not exist yet)."""
    if STATE["out"]:
        return STATE["out"]
    return str(_out_for(Path(STATE["folder"]))) if STATE["folder"] else ""


def _open_run(rid: str) -> bool:
    from . import library as LIB
    e = next((r for r in LIB.list_runs() if r["id"] == rid), None)
    if not e or not e.get("exists"):
        return False
    STATE["out"] = e["out"]
    STATE["sessions"].pop(e["out"], None)
    _gray_png.cache_clear()
    inp = e.get("input_folder", "")
    STATE["folder"] = inp if inp and Path(inp).is_dir() else ""
    LIB.register(Path(e["out"]))
    return True


def _provisional_name(folder: str, out: Path) -> str:
    """Same naming rule as saved runs ('Run3 Plate 1'), before any results exist."""
    if folder:
        from . import cli
        m = cli.parse_name(Path("x.tif"), root=Path(folder))
        if m["run"]:
            return m["run"] + (f" Plate {int(m['plate'])}" if m["plate"] == m["plate"] else "")
        return Path(folder).name
    return out.name.removesuffix("_kidneycyst")


def _run_info() -> dict:
    """Everything the run page header shows."""
    out, folder = _current_out(), STATE["folder"]
    if not out:
        return dict(open=False)
    o = Path(out)
    info = dict(open=True, out=out, folder=folder, n_tiffs=_count_tiffs(Path(folder)) if folder else 0,
                id="", name=_provisional_name(folder, o), status="new",
                summary=_summary(o), job_here=JOB.running and JOB.out == out, job_elsewhere=JOB.running and JOB.out != out)
    if _has_results(o):
        from . import library as LIB
        try:
            e = LIB.register(o, opened=False)
            r = next((x for x in LIB.list_runs() if x["id"] == e["id"]), {})
            info.update(id=e["id"], name=r.get("name", e.get("name", "")), status=r.get("status", "detected"),
                        n=r.get("n"), reviewed=r.get("reviewed"), created=r.get("created", ""), model=r.get("model", ""))
            st = json.loads((o / "run_settings.json").read_text(encoding="utf-8"))
            info["ran_on"] = (st.get("remote", {}).get("host") or "") and \
                f"{st['remote']['host']} ({st['remote'].get('remote_device', '')})".replace(" ()", "")
            info["device"] = {"cuda": "NVIDIA GPU", "mps": "Apple GPU", "cpu": "CPU"}.get(st.get("device", ""), st.get("device", ""))
            info["seconds"] = st.get("seconds")
        except Exception as ex:
            info["warning"] = f"{type(ex).__name__}: {ex}"
    return info


RUN_SCOPED = {"/api/run", "/api/decide", "/api/measure", "/api/grade", "/api/open", "/api/qupath", "/api/snapshot", "/api/layout", "/api/cancel"}


class NoFolder(Exception):
    pass


def _session(out: str):
    if not out:
        raise NoFolder("No results folder is open (KidneyCyst was restarted). Go back to the start page and open the folder again. "
                       "Decisions saved before this are kept.")
    from .review import ReviewSession
    s = STATE["sessions"].get(out)
    if s is None:
        s = STATE["sessions"][out] = ReviewSession(Path(out))
    return s


@lru_cache(maxsize=24)
def _gray_png(out: str, iid: str) -> bytes:
    from PIL import Image
    from .cli import _display, read_gfp
    s = _session(out)
    r = s.df.loc[iid]
    g = _display(read_gfp(s.in_root / r["image"], int(s.settings.get("channel", 0))))
    b = io.BytesIO()
    Image.fromarray(g).save(b, format="PNG", compress_level=1)
    return b.getvalue()


def _mask_png(m: np.ndarray) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.fromarray((m.astype(np.uint8) * 255)).save(b, format="PNG")
    return b.getvalue()


def _num(x):
    return None if x is None or x != x else float(x)


def _beta_fields(r) -> dict:
    """Beta grade/elbow (model) and the human measurements, for the review page."""
    f = lambda k: _num(r[k]) if k in r and r[k] == r[k] and r[k] != "" else None
    s_ = lambda k: str(r[k]) if k in r and isinstance(r[k], str) else ""
    return dict(grade_beta=s_("grade_beta"), p_normal=f("p_normal"), p_unfused=f("p_unfused"), p_cyst=f("p_cyst"),
                grade_confident=str(r.get("grade_confident", "")).lower() == "true",
                elbow_straight=f("elbow_straight_um_beta"), elbow_midline=f("elbow_midline_um_beta"),
                elbow_line=s_("elbow_line_px"), elbow_points=s_("elbow_points_px"),
                elbow_meas_straight=f("elbow_measured_straight_um"), elbow_meas_path=f("elbow_measured_path_um"),
                elbow_meas_by=s_("elbow_measured_by"), grade_human=s_("grade_human"))


def _view_png(out: str, iid: str, kind: str) -> bytes:
    """Crop around the outline (with context) at the image's own resolution; 'out' draws the current outline
    (orange = model's, blue = corrected), as on the review screen."""
    from PIL import Image
    from . import cli
    from .report import CANDIDATE, MINE
    raw, auto, cur = _session(out).load(iid)
    gray = cli._display(raw)
    ys, xs = cli.crop_box(auto | cur if (auto | cur).any() else auto, 480)
    g = gray[ys, xs]
    if kind == "out":
        rgb = np.repeat(g[..., None], 3, 2)
        rgb[cli._outline(cur[ys, xs], 2)] = CANDIDATE if np.array_equal(cur, auto) else MINE
        g = rgb
    b = io.BytesIO()
    Image.fromarray(g).save(b, "PNG")
    return b.getvalue()


def _images(out: str) -> list[dict]:
    from .report import final_area, plain_flags
    s = _session(out)
    rows = []
    for iid in s.order("all"):
        r = s.df.loc[iid]
        rows.append(dict(id=iid, well=str(r["well"]) if isinstance(r["well"], str) else "",
                         field=None if r["field"] != r["field"] else int(r["field"]), status=r["status"],
                         flagged=bool(r["flagged"]), flags=plain_flags(r["flags"]),
                         model=float(r["area_um2"]), area=_num(final_area(r)), px=float(r["px_um"]),
                         px_src=str(r.get("px_source", "")), **_beta_fields(r)))
    return rows


# ---------------------------------------------------------------- about / licenses
def _license_of(dist) -> str:
    md = dist.metadata
    lic = md.get("License-Expression") or ""
    if not lic:
        cls = [c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
        lic = "; ".join(c for c in cls if c not in ("OSI Approved",))
    if not lic:
        lic = (md.get("License") or "").strip().splitlines()[0][:60] if md.get("License") else ""
    return lic or "see package"


@lru_cache(maxsize=1)
def packages() -> list[dict]:
    from importlib.metadata import distributions
    seen = {}
    for d in distributions():
        n = d.metadata.get("Name")
        if n and n.lower() not in seen:
            seen[n.lower()] = dict(name=n, version=d.version, license=_license_of(d))
    return sorted(seen.values(), key=lambda x: x["name"].lower())


def about() -> dict:
    from . import cli
    from . import qupath_io as Q
    from importlib.metadata import version
    v = {}
    for m in ("torch", "nnunetv2", "numpy"):
        try:
            v[m] = version(m)
        except Exception:
            v[m] = "not installed"
    model = cli.DEFAULT_MODEL_NAME
    if STATE.get("out"):
        try:
            model = json.loads((Path(STATE["out"]) / "run_settings.json").read_text(encoding="utf-8"))["model_version"]
        except Exception:
            pass
    home = Q.install_home()
    diag = {"KidneyCyst": cli.TOOL_VERSION, "Model": model, "Computer": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "Python": platform.python_version(), "PyTorch": v["torch"], "nnU-Net": v["nnunetv2"],
            "Processing on": _device_text(), "Install folder": str(home or Path(__file__).parent),
            "Results folder": STATE.get("out") or "(none open)"}
    return dict(version=cli.TOOL_VERSION, model=model, python=platform.python_version(), torch=v["torch"],
                nnunet=v["nnunetv2"], diagnostics=diag, packages=packages())


# ---------------------------------------------------------------- run
def models_here() -> list[dict]:
    """Model choices for the run page; the all-data model only where its weights exist."""
    from . import cli
    out = []
    for key, m in cli.MODELS.items():
        ok = True
        if m["folds"]:
            f = f"fold_{m['folds'][0]}"
            ok = any((Path(c) / f / "checkpoint_final.pth").exists() for c in (cli.default_checkpoint(), cli.SERVER_CHECKPOINT))
        out.append(dict(id=key, name=m["name"], note=m["note"], available_here=ok))
    return out


def start_run(folder: Path, fast: bool, force: bool, pixel_size: float | None = None, local: bool = False,
              model: str = "kc009"):
    from . import cli
    from . import remote_gpu as RG
    out = _out_for(folder)
    rs = RG.load_settings()
    remote = rs["enabled"] and not local
    with JOB.lock:
        if JOB.running:
            return False
        JOB.running, JOB.phase, JOB.i, JOB.n, JOB.error = True, "loading", 0, _count_tiffs(folder), ""
        JOB.current, JOB.cancelled = "", False
        JOB.t0, JOB.out = time.time(), str(out)
        JOB.where, JOB.xfer, JOB.xfer_total = (rs["host"] if remote else ""), 0, 0
        JOB.slurm_id = JOB.queue_reason = ""
        JOB.log.clear()
    STATE["sessions"].pop(str(out), None)
    _gray_png.cache_clear()

    def work():
        old = sys.stdout, sys.stderr
        tee = _Tee()
        sys.stdout = sys.stderr = tee
        try:
            out.mkdir(parents=True, exist_ok=True)
            if remote:
                cli.CANCEL.clear()
                cli.prepare_output(out, force)           # earlier decisions set aside here, before anything is replaced
                meta = cli.parse_name(Path("x.tif"), root=folder)   # run/plate from this computer's folder names
                extra = (["--folds", "0"] if fast and model == "kc009" else []) + (["--model", model] if model != "kc009" else []) \
                    + (["--pixel-size", str(pixel_size)] if pixel_size else []) \
                    + (["--run", meta["run"]] if meta["run"] else []) \
                    + (["--plate", str(int(meta["plate"]))] if meta["plate"] == meta["plate"] else [])
                RG.run_remote(JOB, folder, out, extra, tee, cli.CANCEL)
                JOB.phase = "done"
                return
            args = ["run", str(folder)] + (["--force"] if force else []) + (["--folds", "0"] if fast and model == "kc009" else []) \
                + (["--model", model] if model != "kc009" else []) \
                + (["--pixel-size", str(pixel_size)] if pixel_size else [])
            cli.main(args)
            JOB.phase = "done"
        except SystemExit as e:
            JOB.phase, JOB.error = "error", str(e)
        except (RG.RemoteError, RG.Cancelled) as e:
            if isinstance(e, RG.Cancelled):
                JOB.phase, JOB.cancelled, JOB.error = "error", True, str(e) or "Detection cancelled."
            else:
                JOB.phase, JOB.error = "error", str(e)
            print(JOB.error, file=tee)
        except BaseException as e:
            traceback.print_exc(file=tee)
            JOB.phase, JOB.error = "error", f"{type(e).__name__}: {e}"
        finally:
            sys.stdout, sys.stderr = old
            try:
                (out / "kidneycyst_log.txt").open("a", encoding="utf-8").write("\n".join(JOB.log) + "\n")
            except Exception:
                pass
            JOB.running = False
    threading.Thread(target=work, daemon=True).start()
    return True


# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    server_version = "KidneyCyst"

    def log_message(self, fmt, *a):
        if REMOTE:                                   # remote test sessions: show who connects (token not logged)
            print(f"{self.client_address[0]} {self.command} {self.path.split('?')[0]}", flush=True)

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _other_run(self) -> bool:
        """True when this page belongs to a run other than the open one (another tab switched runs)."""
        want = unquote(self.headers.get("X-Run") or "")          # sent URL-encoded: headers are Latin-1 only
        return bool(want) and want != _current_out()

    def _other_run_answer(self):
        i = _run_info()
        return self._json(dict(error="other_run", other_run=True, current_name=i.get("name", ""), current_id=i.get("id", "")), 409)

    def _json(self, obj, code=200):
        _remember()
        self._send(code, json.dumps(obj, default=str).encode(), "application/json")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _authed(self, q) -> bool:
        return self.headers.get("X-Token") == TOKEN or q.get("t", [""])[0] == TOKEN

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path
        STATE["last_ping"] = time.time()
        try:
            if p in ("/", "/run", "/review", "/help", "/library"):
                if not self._authed(q):
                    return self._send(403, "Launch KidneyCyst using the application icon.".encode(), "text/plain")
                if p == "/library":                       # the saved-runs list is now the start page
                    return self._send(302, b"", "text/plain", {"Location": f"/?t={TOKEN}"})
                rid = q.get("id", [""])[0]
                if p in ("/run", "/review") and rid and not JOB.running:
                    _open_run(rid)                        # explicit: the user clicked Open on this run
                html = (STATIC / {"/": "index.html", "/run": "run.html", "/review": "review.html",
                                  "/help": "help.html"}[p]).read_text(encoding="utf-8")
                return self._send(200, html.replace("__TOKEN__", TOKEN).encode(), "text/html; charset=utf-8")
            if p.startswith("/static/"):
                f = (STATIC / p[len("/static/"):]).resolve()
                if STATIC.resolve() not in f.parents or not f.exists():
                    return self._send(404, b"", "text/plain")
                ct = {".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml",
                      ".ico": "image/x-icon"}.get(f.suffix, "application/octet-stream")
                return self._send(200, f.read_bytes(), ct)
            if not self._authed(q):
                return self._send(403, b"", "text/plain")
            if (p in ("/api/images", "/api/run-info") or p.startswith("/api/img/")) and self._other_run():
                return self._other_run_answer()
            if p == "/api/state":
                folder = STATE["folder"]
                out = STATE["out"]
                return self._json(dict(folder=folder, n_tiffs=_count_tiffs(Path(folder)) if folder else 0,
                                       out=out, summary=_summary(Path(out)) if out else None,
                                       device=_device_text(), job=JOB.snapshot()))
            if p == "/api/run-info":
                return self._json(_run_info())
            if p == "/api/about":
                return self._json(about())
            if p == "/api/library":
                from . import library as LIB
                return self._json(dict(runs=LIB.list_runs(), current=STATE.get("out", ""), where=str(LIB.library_dir())))
            if p in ("/snapshot", "/snapfile"):
                from . import library as LIB
                e = next((r for r in LIB.list_runs() if r["id"] == q.get("id", [""])[0]), None)
                name = q.get("f", [""])[0]
                if e is None or "/" in name or "\\" in name or not re.fullmatch(r"[\w.-]+\.(html|xlsx)", name):
                    return self._send(404, b"", "text/plain")
                f = Path(e["out"]) / "snapshots" / name
                if not f.exists():
                    return self._send(404, b"", "text/plain")
                if f.suffix == ".xlsx":
                    return self._send(200, f.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                      {"Content-Disposition": 'attachment; filename="' + re.sub(r"[^A-Za-z0-9 ._-]", "_", f"{e['name']} {name}") + '"'})
                return self._send(200, f.read_bytes(), "text/html; charset=utf-8")
            if p == "/api/layout":
                from .report import load_layout
                return self._json(dict(layout=load_layout(Path(STATE["out"]))))
            if p == "/api/version":           # changes whenever results.csv is rewritten (any decision, any tab)
                f = Path(STATE["out"]) / "results.csv" if STATE.get("out") else None
                return self._json(dict(v=f.stat().st_mtime_ns if f and f.exists() else 0))
            if p == "/api/job":
                return self._json(JOB.snapshot())
            if p == "/api/images":
                return self._json(_images(STATE["out"]))
            m = re.match(r"^/api/view/([^/]+)/(in|out)\.png$", p)
            if m:                                  # report viewer: sharp crop at native resolution, current outline
                return self._send(200, _view_png(STATE["out"], unquote(m.group(1)), m.group(2)), "image/png",
                                  {"Cache-Control": "no-store"})
            m = re.match(r"^/api/img/([^/]+)/(gray|auto|cur)\.png$", p)
            if m:
                iid, kind = unquote(m.group(1)), m.group(2)
                if kind == "gray":
                    return self._send(200, _gray_png(STATE["out"], iid), "image/png")
                _, auto, cur = _session(STATE["out"]).load(iid) if kind == "cur" else (None, None, None)
                if kind == "auto":
                    from .review import _png_read
                    auto = _png_read(Path(STATE["out"]) / "masks" / f"{iid}.png")
                return self._send(200, _mask_png(auto if kind == "auto" else cur), "image/png")
            if p == "/download" and q.get("what", [""])[0] == "table":
                out = Path(STATE["out"] or ".")
                f = next((x for x in (out / "results.xlsx", out / "results.csv") if STATE["out"] and x.exists()), None)
                if f is None:
                    return self._json(dict(error="No results yet."), 404)
                ctype = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if f.suffix == ".xlsx" else "text/csv")
                return self._send(200, f.read_bytes(), ctype, {"Content-Disposition": 'attachment; filename="'
                                  + re.sub(r"[^A-Za-z0-9._-]", "_", out.name) + "_results" + f.suffix + '"'})
            if p == "/api/remote":
                return self._json(dict(remote=REMOTE))
            if p == "/report":
                from .report import build_report
                f = build_report(Path(STATE["out"]))
                return self._send(200, f.read_bytes(), "text/html; charset=utf-8")
            return self._send(404, b"", "text/plain")
        except Exception as e:
            traceback.print_exc()
            return self._json(dict(error=str(e) if isinstance(e, NoFolder) else f"{type(e).__name__}: {e}"), 500)

    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        STATE["last_ping"] = time.time()
        if self.headers.get("X-Token") != TOKEN:
            return self._send(403, b"", "text/plain")
        if p in RUN_SCOPED and self._other_run():
            return self._other_run_answer()
        try:
            b = self._body()
            if p == "/api/layout":
                from .report import build_report, save_layout, write_tables
                import pandas as pd
                out = Path(STATE["out"])
                lay = b.get("layout") or {}
                lay = dict(mode=lay.get("mode", "column") if lay.get("mode") in ("column", "row", "well") else "column",
                           labels={str(k): str(v)[:60] for k, v in (lay.get("labels") or {}).items() if str(v).strip()},
                           order=[str(x)[:60] for x in (lay.get("order") or [])])
                save_layout(out, lay)
                write_tables(out, pd.read_csv(out / "results.csv", dtype={"well": str}))
                build_report(out)
                return self._json(dict(ok=True))
            if p == "/api/snapshot":
                from . import library as LIB
                return self._json(dict(ok=True, **LIB.snapshot(Path(STATE["out"]), "manual")))
            if p == "/api/library":
                from . import library as LIB
                act, rid = b.get("action"), b.get("id", "")
                if act == "open":
                    if JOB.running:
                        return self._json(dict(error="A detection is running. Open other runs after it finishes."))
                    if not _open_run(rid):
                        return self._json(dict(error="This results folder was not found. Use Locate to point to its new place."))
                    return self._json(dict(ok=True, id=rid))
                if act == "rename":
                    LIB.rename(rid, b.get("name", ""))
                    return self._json(dict(ok=True))
                if act == "remove":
                    LIB.remove(rid)
                    return self._json(dict(ok=True))
                if act in ("locate", "add", "scan"):
                    f = b.get("path") or (None if REMOTE else pick_folder())
                    if not f:
                        return self._json(dict(cancelled=True))
                    f = Path(f)
                    if act == "scan":
                        return self._json(dict(ok=True, found=LIB.scan(f)))
                    if not _has_results(f):
                        return self._json(dict(error="No KidneyCyst results found. Select a results folder ending in _kidneycyst."))
                    if act == "locate":
                        LIB.locate(rid, f)
                    else:
                        LIB.register(f, opened=False)
                    return self._json(dict(ok=True))
                return self._json(dict(error="unknown action"), 400)
            if p == "/api/gpu-settings":
                from . import remote_gpu as RG
                if b:
                    try:
                        RG.save_settings(**b)
                    except RG.RemoteError as e:
                        return self._json(dict(RG.load_settings(), error=str(e), here=_device_text(), ssh=bool(RG.ssh_exe())))
                return self._json(dict(RG.load_settings(), here=_device_text(), ssh=bool(RG.ssh_exe()), models=models_here()))
            if p == "/api/gpu-test":
                from . import remote_gpu as RG
                r = RG.probe(b.get("host", ""), b.get("command", ""))
                if r["ok"]:
                    RG.save_settings(host=b.get("host", ""), command=r["command"], info=r["info"], slurm=r["slurm"],
                                     partitions=r["partitions"])
                return self._json(r)
            if p == "/api/gpu-install":
                from . import remote_gpu as RG
                if b.get("start"):
                    try:
                        return self._json(RG.start_install(b.get("host", "")))
                    except RG.RemoteError as e:
                        return self._json(dict(ok=False, error=str(e)))
                return self._json(RG.INSTALL_STATE)
            if p == "/api/gpu-key":
                from . import remote_gpu as RG
                try:
                    return self._json(RG.open_key_setup(b.get("host", "")))
                except RG.RemoteError as e:
                    return self._json(dict(ok=False, error=str(e)))
            if p == "/api/measure":
                s = _session(STATE["out"])
                v = s.measure_elbow(b["id"], b.get("points") or [])
                return self._json(dict(ok=True, export_ok=getattr(s, "last_export_ok", True), **v))
            if p == "/api/grade":
                s = _session(STATE["out"])
                try:
                    v = s.set_grade(b["id"], b.get("grade", ""))
                except ValueError as e:
                    return self._json(dict(error=str(e)), 400)
                return self._json(dict(ok=True, export_ok=getattr(s, "last_export_ok", True), **v))
            if p == "/api/cancel":
                from .cli import CANCEL
                CANCEL.set()
                return self._json(dict(ok=True))
            if p == "/api/ping":
                return self._json(dict(ok=True))
            if p in ("/api/pick", "/api/folder", "/api/open-results") and JOB.running:
                return self._json(dict(error="A detection is running. Choose another folder after it finishes, or cancel it on its run page."))
            if p == "/api/pick":
                if REMOTE:
                    return self._json(dict(error="Remote test mode: type or paste the folder path (as seen on the server) and click Open folder."))
                f = pick_folder()
                return self._json(self._set_folder(f) if f else dict(cancelled=True))
            if p == "/api/folder":
                return self._json(self._set_folder(b.get("path", "")))
            if p == "/api/open-results":
                out = Path(b.get("path", ""))
                if not _has_results(out):
                    return self._json(dict(error="No KidneyCyst results found. Select a results folder ending in _kidneycyst."))
                return self._json(self._set_folder(str(out)))
            if p == "/api/run":
                folder = Path(STATE["folder"])
                out = _out_for(folder)
                has_rev = out.exists() and ((out / "review").exists() or any(out.glob("qupath*/project.qpproj")))
                if has_rev and not b.get("force"):
                    return self._json(dict(needs_confirm=True))
                px = b.get("pixel_size")
                from . import remote_gpu as RG
                m = next((x for x in models_here() if x["id"] == b.get("model")), None)
                if m and not m["available_here"] and not (RG.load_settings()["enabled"] and not b.get("local")):
                    return self._json(dict(ok=False, error=f"The model {m['name']} is not included in this installation. "
                                           f"Choose KC009, or run detection on the HPC (Change where detection runs), "
                                           f"where this model is available."))
                ok = start_run(folder, bool(b.get("fast")), has_rev or _has_results(out),
                               float(px) if px else None, local=bool(b.get("local")),
                               model=b.get("model") if b.get("model") in __import__("kidneycyst.cli", fromlist=["MODELS"]).MODELS else "kc009")
                STATE["out"] = str(out)
                return self._json(dict(ok=ok))
            if p == "/api/decide":
                from PIL import Image
                s = _session(STATE["out"])
                mask = None
                if b.get("mask"):
                    raw = base64.b64decode(b["mask"].split(",", 1)[1])
                    im = np.array(Image.open(io.BytesIO(raw)).convert("L")) > 127
                    mask = im
                st = s.decide(b["id"], b["action"], mask)
                r = s.df.loc[b["id"]]
                from .report import final_area
                return self._json(dict(status=st, area=_num(final_area(r)), export_ok=getattr(s, "last_export_ok", True)))
            if p == "/api/open":
                out = Path(STATE["out"])
                what = b.get("what")
                from . import qupath_io as Q
                home = Q.install_home() or Path(__file__).parent
                target = {"table": out / "results.xlsx", "folder": out, "report": out / "report.html", "install": home}.get(what)
                if what == "table" and not target.exists():
                    target = out / "results.csv"
                if what == "report":
                    from .report import build_report
                    build_report(out)
                if REMOTE:
                    if what == "table":
                        return self._json(dict(download=f"/download?what=table&t={TOKEN}"))
                    return self._json(dict(error=f"Remote test mode: the results folder is on the server at {out}"))
                open_path(target)
                return self._json(dict(ok=True))
            if p == "/api/qupath":
                return self._json(self._qupath(b.get("action", "open")))
            if p == "/api/quit":
                threading.Thread(target=lambda: (time.sleep(0.3), os._exit(0)), daemon=True).start()
                return self._json(dict(ok=True))
            return self._send(404, b"", "text/plain")
        except Exception as e:
            traceback.print_exc()
            return self._json(dict(error=str(e) if isinstance(e, NoFolder) else f"{type(e).__name__}: {e}"), 500)

    def _set_folder(self, f: str) -> dict:
        folder = Path(f).expanduser()
        if not folder.is_dir():
            return dict(error=f"The path is not a folder: {f}")
        if _has_results(folder) and (folder / "run_settings.json").exists():   # a results folder itself
            from . import library as LIB
            e = LIB.register(folder)
            _open_run(e["id"])                    # also points the image folder at the run's own input folder
            return dict(ok=True, results_only=True, id=e["id"], summary=_summary(folder))
        n = _count_tiffs(folder)
        STATE["folder"] = str(folder)
        out = _out_for(folder)
        STATE["out"] = str(out) if _has_results(out) else ""
        STATE["sessions"].pop(str(out), None)
        _gray_png.cache_clear()
        rid = ""
        if STATE["out"]:
            from . import library as LIB
            rid = LIB.register(out)["id"]
        return dict(ok=True, folder=str(folder), n_tiffs=n, id=rid, summary=_summary(out))

    def _qupath(self, action: str) -> dict:
        from . import qupath_io as Q
        out = Path(STATE["out"])
        if not Q.has_paquo():
            if action != "install_support":
                return dict(needs_support=True, qupath_found=_qupath_found())
            Q.install_paquo()
            return dict(ok=True, installed=True)
        try:
            Q.qupath_executable()
        except FileNotFoundError:
            if action != "download":
                return dict(needs_qupath=True)
            from . import setup_local
            home = Q.install_home()
            if home is None:
                return dict(error="QuPath 0.6.0 was not found. Install it from qupath.github.io.")
            setup_local.set_qupath(home, setup_local.download_qupath(home))
        if action == "sync":
            df = Q.sync(out)
            STATE["sessions"].pop(str(out), None)
            return dict(ok=True, status=df.status.value_counts().to_dict())
        p = out / "qupath" / "project.qpproj"
        log = out / "review" / "review_log.csv"
        stale = p.exists() and log.exists() and log.stat().st_mtime > (p.parent / Q.PROJECT_MANIFEST).stat().st_mtime
        if p.exists() and stale:
            Q.sync(out)
        if not p.exists() or stale:
            Q.build_project(out, overwrite=True)
        Q.open_project(p)
        return dict(ok=True)


def _qupath_found() -> bool:
    from . import qupath_io as Q
    try:
        Q.qupath_executable()
        return True
    except FileNotFoundError:
        return False


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


RESUME = os.environ.get("KIDNEYCYST_RESUME") == "1" or os.environ.get("KIDNEYCYST_IDLE_EXIT") == "0"   # test sessions restart by themselves
_LAST_SAVED = [None]


def _session_file() -> Path:
    return Path(os.environ.get("KIDNEYCYST_HOME") or Path.home()) / "kidneycyst_last_session.json"


def _remember():
    cur = (STATE["folder"], STATE["out"])
    if RESUME and cur != _LAST_SAVED[0]:
        try:
            _session_file().write_text(json.dumps(dict(folder=cur[0], out=cur[1])), encoding="utf-8")
            _LAST_SAVED[0] = cur
        except Exception:
            pass


def _restore():
    try:
        d = json.loads(_session_file().read_text(encoding="utf-8"))
    except Exception:
        return
    if d.get("folder") and Path(d["folder"]).is_dir():
        STATE["folder"] = d["folder"]
    if d.get("out") and _has_results(d["out"]):
        STATE["out"] = d["out"]
    _LAST_SAVED[0] = (STATE["folder"], STATE["out"])


def _watchdog():
    while True:
        time.sleep(30)
        if IDLE_EXIT_S and not JOB.running and time.time() - STATE["last_ping"] > IDLE_EXIT_S:
            os._exit(0)


def main():
    if sys.stdout is None or sys.stderr is None:      # started without a console (Windows pythonw, macOS app)
        home = Path(os.environ.get("KIDNEYCYST_HOME") or Path.home())
        f = open(home / "kidneycyst_app_log.txt", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(errors="replace")
        except Exception:
            pass
    port = int(os.environ.get("KIDNEYCYST_PORT") or _free_port())
    host = os.environ.get("KIDNEYCYST_HOST", "127.0.0.1")   # 0.0.0.0 only for remote test sessions (token still required)
    srv = ThreadingHTTPServer((host, port), H)
    shown = socket.gethostbyname(socket.gethostname()) if host == "0.0.0.0" else host
    url = f"http://{shown}:{port}/?t={TOKEN}"
    print(f"KidneyCyst is available at {url}\n" + (f"The server stops {IDLE_EXIT_S // 60} minutes after the last application tab is closed."
                                                       if IDLE_EXIT_S else "The server keeps running until it is stopped."), flush=True)
    if RESUME:
        _restore()
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_dir():        # optional: start with a folder
        H._set_folder(None, sys.argv[1])
    threading.Thread(target=_watchdog, daemon=True).start()
    from . import cli as _cli
    threading.Thread(target=_cli.preload_model, daemon=True).start()   # model ready before the user clicks Run
    if not os.environ.get("KIDNEYCYST_NO_BROWSER"):
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
