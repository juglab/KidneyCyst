"""Saved runs: one library per install, plus report snapshots.

  <install>/library/library.json   list of runs this install knows: {"runs": [{id, name, out, created, last_opened}]}
  <results>/run.json               id, name, created, input folder: makes every results folder self-describing, so the
                                   library can be rebuilt by scanning folders if library.json is ever lost
  <results>/snapshots/             frozen copies of the report (+ Excel table): <date>_<time>_<kind>.html/.xlsx
                                   kind = detected (end of detection) | final (last image reviewed) | manual

Nothing here ever deletes results or images. "Remove from list" only forgets the entry.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import threading
import uuid
from pathlib import Path

_LOCK = threading.Lock()


def library_dir() -> Path:
    from .qupath_io import install_home
    h = install_home()
    d = (h / "library") if h is not None else (Path.home() / ".kidneycyst" / "library")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lib_path() -> Path:
    return library_dir() / "library.json"


def _read() -> dict:
    p = _lib_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            bad = p.with_suffix(f".broken-{_dt.datetime.now():%Y%m%d%H%M%S}.json")
            shutil.copy2(p, bad)            # keep the unreadable file for inspection, start a fresh list
    return {"runs": []}


def _write(lib: dict):
    p = _lib_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(lib, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- per-run identity
def auto_name(out: Path) -> str:
    """'Run2 Plate1' from the results, else the image folder's name."""
    out = Path(out)
    try:
        import pandas as pd
        d = pd.read_csv(out / "results.csv", usecols=lambda c: c in ("run", "plate"))
        runs = sorted({str(x) for x in d.get("run", []) if isinstance(x, str) and x})
        plates = sorted({int(x) for x in d.get("plate", []) if x == x})
        if runs:
            return " ".join([", ".join(runs)] + ([("Plate" if len(plates) == 1 else "Plates") + " "
                                                   + ", ".join(map(str, plates))] if plates else []))
    except Exception:
        pass
    n = out.name
    return n[:-len("_kidneycyst")] if n.endswith("_kidneycyst") else n


def ensure_run_json(out: Path) -> dict:
    out = Path(out)
    p = out / "run.json"
    info = {}
    if p.exists():
        try:
            info = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            info = {}
    if not info.get("id"):
        st = {}
        try:
            st = json.loads((out / "run_settings.json").read_text(encoding="utf-8"))
        except Exception:
            pass
        info = dict(id=uuid.uuid4().hex[:12], name=auto_name(out), created=st.get("date") or _now(),
                    input_folder=st.get("input_folder", ""))
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(info, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    return info


# ---------------------------------------------------------------- library
def has_results(out: Path) -> bool:
    """results.csv exists and holds a table (a detection stopped before its first image used to leave an empty file)."""
    f = Path(out) / "results.csv"
    try:
        with open(f, encoding="utf-8", errors="replace") as h:
            return "image_id" in h.readline()
    except OSError:
        return False


def register(out: Path, opened: bool = True) -> dict:
    """Add (or refresh) a results folder in the library. Returns its entry."""
    out = Path(out).resolve()
    info = ensure_run_json(out)
    with _LOCK:
        lib = _read()
        e = next((r for r in lib["runs"] if r["id"] == info["id"]), None)
        if e is None:
            e = next((r for r in lib["runs"] if r.get("out") == str(out)), None)
        if e is None:
            e = dict(id=info["id"], name=info.get("name") or auto_name(out), out=str(out),
                     created=info.get("created") or _now())
            lib["runs"].append(e)
        e["out"] = str(out)
        e["id"] = info["id"]
        if opened:
            e["last_opened"] = _now()
        _write(lib)
    return e


def rename(run_id: str, name: str):
    name = " ".join(str(name).split())[:80]
    with _LOCK:
        lib = _read()
        for e in lib["runs"]:
            if e["id"] == run_id:
                e["name"] = name
                try:
                    p = Path(e["out"]) / "run.json"
                    info = json.loads(p.read_text(encoding="utf-8"))
                    info["name"] = name
                    p.write_text(json.dumps(info, indent=1), encoding="utf-8")
                except Exception:
                    pass
        _write(lib)


def remove(run_id: str):
    """Forget a run. Its files are not touched."""
    with _LOCK:
        lib = _read()
        lib["runs"] = [e for e in lib["runs"] if e["id"] != run_id]
        _write(lib)


def locate(run_id: str, new_out: Path) -> bool:
    new_out = Path(new_out).resolve()
    if not has_results(new_out):
        return False
    with _LOCK:
        lib = _read()
        for e in lib["runs"]:
            if e["id"] == run_id:
                e["out"] = str(new_out)
        _write(lib)
    return True


def scan(folder: Path, max_depth: int = 4) -> int:
    """Add every results folder found under `folder` (rebuild the library after a reinstall)."""
    n = 0
    folder = Path(folder)
    for p in folder.rglob("results.csv"):
        if len(p.relative_to(folder).parts) > max_depth + 1 or "replaced_" in str(p.parent.name):
            continue
        if (p.parent / "run_settings.json").exists() and has_results(p.parent):
            register(p.parent, opened=False)
            n += 1
    return n


def _summary(out: Path) -> dict:
    import pandas as pd
    from .report import final_area
    d = pd.read_csv(out / "results.csv", usecols=lambda c: c in ("status", "area_um2", "reviewed_area_um2", "flagged"))
    if "status" not in d:
        d["status"] = "auto"
    d["status"] = d.status.fillna("auto")
    n = len(d)
    rev = int((d.status != "auto").sum())
    areas = [final_area(r) for _, r in d.iterrows()]
    a = [x for x in areas if x == x and x > 0]
    med = float(pd.Series(a).median()) if a else None
    st = {}
    try:
        st = json.loads((out / "run_settings.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    status = "cancelled" if st.get("cancelled") else ("final" if n and rev == n else ("in review" if rev else "detected"))
    return dict(n=n, reviewed=rev, median=med, status=status, model=st.get("model_name", ""),
                input_folder=st.get("input_folder", ""))


def list_runs() -> list[dict]:
    lib = _read()
    rows = []
    for e in lib["runs"]:
        out = Path(e["out"])
        r = dict(e, exists=(out / "results.csv").exists())
        if r["exists"] and not has_results(out):        # detection never finished an image: nothing to show yet
            r.update(n=0, reviewed=0, median=None, status="new")
        elif r["exists"]:
            try:
                r.update(_summary(out))
            except Exception as ex:
                r.update(error=str(ex))
            r["snapshots"] = snapshots(out)
            r["older_runs"] = sorted(p.name for p in out.glob("replaced_*_review"))
        rows.append(r)
    rows.sort(key=lambda r: r.get("last_opened") or r.get("created") or "", reverse=True)
    return rows


# ---------------------------------------------------------------- snapshots
def snapshots(out: Path) -> list[dict]:
    d = Path(out) / "snapshots"
    if not d.exists():
        return []
    res = []
    for f in sorted(d.glob("*.html"), reverse=True):
        stem = f.stem                           # 2026-11-25_1436_final
        parts = stem.split("_")
        kind = parts[-1] if len(parts) >= 3 else "manual"
        try:
            when = _dt.datetime.strptime("_".join(parts[:2]), "%Y-%m-%d_%H%M%S").strftime("%Y-%m-%d %H:%M")
        except ValueError:
            when = stem
        res.append(dict(file=f.name, kind=kind, when=when, xlsx=f.with_suffix(".xlsx").name if f.with_suffix(".xlsx").exists() else ""))
    return res


def snapshot(out: Path, kind: str = "manual") -> dict:
    """Freeze the current report (and Excel table) into <results>/snapshots/."""
    from .report import build_report
    out = Path(out)
    d = out / "snapshots"
    d.mkdir(exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    name = f"{stamp}_{kind}"
    build_report(out, snapshot=dict(kind=kind, when=_dt.datetime.now().strftime("%Y-%m-%d %H:%M")),
                 target=d / f"{name}.html")
    if (out / "results.xlsx").exists():
        shutil.copy2(out / "results.xlsx", d / f"{name}.xlsx")
    return dict(file=f"{name}.html", kind=kind)
