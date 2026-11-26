"""Second half of the local installer (called by `Install KidneyCyst.bat` / `install_linux.sh`).

  python -m kidneycyst.setup_local            (KIDNEYCYST_HOME = the install folder)

1. find QuPath 0.6.0 on this computer (Nikita's labs already have it), else download it into <home>/tools/
2. write <home>/config.json
3. self-test: predict the bundled sample image and compare with the area measured when the package was built,
   then build a one-image QuPath project (proves Java/QuPath work)
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

QUPATH_VERSION = "0.6.0"
URLS = {
    "Windows": f"https://github.com/qupath/qupath/releases/download/v{QUPATH_VERSION}/QuPath-v{QUPATH_VERSION}-Windows.zip",
    "Linux": f"https://github.com/qupath/qupath/releases/download/v{QUPATH_VERSION}/QuPath-v{QUPATH_VERSION}-Linux.tar.xz",
}


def _is_qupath_dir(d: Path) -> bool:
    if not d.is_dir():
        return False
    exes = [d / f"QuPath-{QUPATH_VERSION}.exe", d / "QuPath.exe", d / "bin" / "QuPath",
            d / "Contents" / "MacOS" / "QuPath"]
    if not any(e.exists() for e in exes):
        return False
    cfgs = list(d.glob("app/QuPath*.cfg")) + list(d.glob("lib/app/QuPath*.cfg")) + list(d.glob("Contents/app/QuPath*.cfg"))
    txt = " ".join(c.read_text(errors="ignore") for c in cfgs)
    return QUPATH_VERSION in txt or QUPATH_VERSION in d.name


def find_qupath() -> Path | None:
    c = []
    if os.environ.get("PAQUO_QUPATH_DIR"):
        c.append(Path(os.environ["PAQUO_QUPATH_DIR"]))
    sysname = platform.system()
    if sysname == "Windows":
        for base in [os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                     str(Path.home() / "AppData/Local/Programs")]:
            if base:
                c += sorted(Path(base).glob("QuPath*"))
    elif sysname == "Darwin":
        c += sorted(Path("/Applications").glob("QuPath*.app")) + sorted((Path.home() / "Applications").glob("QuPath*.app"))
    else:
        c += sorted(Path.home().glob("QuPath*")) + sorted(Path("/opt").glob("QuPath*"))
    for d in c:
        for cand in [d, *d.glob("QuPath*")]:
            if _is_qupath_dir(cand):
                return cand
    return None


def _download(url: str, dest: Path):
    if dest.exists():
        return
    print(f"downloading QuPath {QUPATH_VERSION} (~260 MB) …", flush=True)
    tmp = dest.with_suffix(".part")

    def hook(n, bs, tot):
        if tot > 0 and n % 400 == 0:
            print(f"  {min(100, n * bs * 100 // tot)}%", flush=True)
    urllib.request.urlretrieve(url, tmp, hook)
    tmp.rename(dest)


def download_qupath_mac(home: Path) -> Path:
    """The Mac release is a .pkg: unpack it (no installation, no admin password) and use the QuPath.app inside."""
    import subprocess
    arch = "arm64" if platform.machine() == "arm64" else "x64"
    url = f"https://github.com/qupath/qupath/releases/download/v{QUPATH_VERSION}/QuPath-v{QUPATH_VERSION}-Mac-{arch}.pkg"
    tools = home / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    pkg = tools / url.rsplit("/", 1)[1]
    _download(url, pkg)
    print("unpacking QuPath …", flush=True)
    dest = tools / "QuPath"
    shutil.rmtree(dest, ignore_errors=True)
    subprocess.run(["pkgutil", "--expand-full", str(pkg), str(dest)], check=True)
    for app in sorted(dest.rglob("QuPath*.app")):
        if _is_qupath_dir(app):
            pkg.unlink(missing_ok=True)
            return app
    raise SystemExit(f"QuPath unpacked into {dest} but QuPath.app was not found")


def download_qupath(home: Path) -> Path:
    sysname = platform.system()
    if sysname == "Darwin":
        return download_qupath_mac(home)
    if sysname not in URLS:
        raise SystemExit("Please install QuPath 0.6.0 from https://qupath.github.io and run the installer again.")
    tools = home / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    url = URLS[sysname]
    arc = tools / url.rsplit("/", 1)[1]
    _download(url, arc)
    print("unpacking QuPath …", flush=True)
    dest = tools / "QuPath"
    shutil.rmtree(dest, ignore_errors=True)
    if arc.suffix == ".zip":
        with zipfile.ZipFile(arc) as z:
            z.extractall(dest)
    else:
        with tarfile.open(arc) as t:
            t.extractall(dest, filter="data")
    for cand in [dest, *dest.rglob("*")]:
        if cand.is_dir() and _is_qupath_dir(cand):
            arc.unlink(missing_ok=True)
            return cand
    raise SystemExit(f"QuPath unpacked into {dest} but its program was not found")


def self_test(home: Path) -> dict:
    import pandas as pd
    from . import cli, qupath_io as Q
    sample = home / "sample"
    exp = json.loads((sample / "expected.json").read_text(encoding="utf-8"))
    out = home / "tools" / "selftest_kidneycyst"
    shutil.rmtree(out, ignore_errors=True)
    cli.main(["run", str(sample / "images"), "--out", str(out), "--force", "--plate", "1", "--run", "Run2"])
    df = pd.read_csv(out / "results.csv")
    got = float(df.area_um2.iloc[0])
    rel = abs(got - exp["area_um2"]) / exp["area_um2"]
    qa = None
    if Q.has_paquo() and (Q.local_config().get("qupath_dir") or os.environ.get("PAQUO_QUPATH_DIR")):
        Q.build_project(out, overwrite=True)
        qa = Q.java_area_um2(out / "qupath", df.image_id.iloc[0])
    settings = json.loads((out / "run_settings.json").read_text(encoding="utf-8"))
    return dict(area=got, expected=exp["area_um2"], rel=rel, qupath_area=qa, device=settings["device"],
                ok=rel < 0.01 and (qa is None or abs(qa - got) / got < 0.01))


def set_qupath(home: Path, qp: Path):
    cfgp = home / "config.json"
    cfg = json.loads(cfgp.read_text(encoding="utf-8")) if cfgp.exists() else {}
    cfg["qupath_dir"] = str(qp)
    cfgp.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    os.environ["PAQUO_QUPATH_DIR"] = str(qp)


def main():
    if os.name == "nt":
        os.system("")                 # colour codes in the Windows console
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(errors="replace")
        except Exception:
            pass
    home = Path(os.environ.get("KIDNEYCYST_HOME") or (sys.argv[1] if len(sys.argv) > 1 else ".")).resolve()
    os.environ["KIDNEYCYST_HOME"] = str(home)
    qp = find_qupath()       # optional: only used by "Open in QuPath"; the app can download it later on request
    print(f"Optional integration: QuPath {QUPATH_VERSION} found at {qp}" if qp else
          "QuPath is not installed. Built-in review is available.")
    cfg = dict(qupath_dir=str(qp) if qp else "", installed_from=str(home), python=sys.executable)
    (home / "config.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    if qp:
        os.environ["PAQUO_QUPATH_DIR"] = str(qp)

    r = self_test(home)
    gpu = {"cuda": "NVIDIA GPU", "mps": "Apple GPU"}.get(r["device"], "CPU")
    qtxt = f" QuPath: {r['qupath_area']:,.0f}." if r["qupath_area"] is not None else ""
    from .cli import c
    col = "green" if r["ok"] else "red"
    tl, tr, bl, br, hz, vt = ("┏", "┓", "┗", "┛", "━", "┃") if os.name != "nt" else ("+", "+", "+", "+", "=", "|")
    lines = [("Sample-image test passed." if r["ok"] else
              "Sample-image test failed. Send the error details to aman.kukde@fht.org."),
             f"Sample area: {r['area']:,.0f} µm². Reference: {r['expected']:,.0f}.{qtxt}",
             f"Processing device: {gpu}"]
    w = max(len(x) for x in lines) + 4
    print()
    print(c("  " + tl + hz * w + tr, col))
    for x in lines:
        print(c("  " + vt + "  " + x.ljust(w - 2) + vt, col))
    print(c("  " + bl + hz * w + br, col))
    print()
    if not r["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
