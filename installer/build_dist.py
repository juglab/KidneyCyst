"""Assemble the folder we hand to a lab (then zip it):

  KidneyCyst/
    Install KidneyCyst.bat   KidneyCyst.bat          (Windows: double-click the first one, once)
    install_linux.sh         kidneycyst.sh           (Linux)
    HOW TO USE.html                                  (the user guide)
    app/   kidneycyst wheel + requirements.txt
    model/ nnU-Net model folder, checkpoints slimmed to inference weights only
    sample/images/<one TIFF> + expected.json         (installer self-test)
    tools/ uv.exe (Windows), uv (Linux)

usage (nnU-Net env; light I/O only, the one-image reference prediction is a few seconds on a GPU):
  python installer/build_dist.py <dest> [--checkpoint DIR] [--folds 0,1,2] [--sample TIF] [--zip]
"""
import argparse
import io
import os
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent
sys.path.insert(0, str(PROJ / "src"))
from kidneycyst import cli  # noqa: E402

UV_VERSION = "0.9.5"
UV = {"uv.exe": f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-pc-windows-msvc.zip",
      "uv": f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz",
      "uv-mac-arm64": f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-aarch64-apple-darwin.tar.gz"}
KEEP = ("network_weights", "init_args", "trainer_name", "inference_allowed_mirroring_axes", "current_epoch")
DEFAULT_SAMPLE = ("/group/jug/aman/Datasets/Zebrafish_KidneyCyst/raw/Data/Run2/181225_ONO-AE3-208_Toxicity data_Merged_TIFF_Quantified/"
                  "181225_ONO-AE3-208_Toxicity data_Merged_TIFF/181225_Plate1Zproj/Index.idx.xml - Well B03, Field 2.tif")


def export_model(src: Path, dst: Path, folds):
    dst.mkdir(parents=True, exist_ok=True)
    for f in ("plans.json", "dataset.json", "dataset_fingerprint.json"):
        if (src / f).exists():
            shutil.copy2(src / f, dst / f)
    for k in folds:
        c = torch.load(src / f"fold_{k}" / "checkpoint_final.pth", map_location="cpu", weights_only=False)
        (dst / f"fold_{k}").mkdir(exist_ok=True)
        torch.save({k2: c[k2] for k2 in KEEP if k2 in c}, dst / f"fold_{k}" / "checkpoint_final.pth")
        print(f"fold {k}: {(dst / f'fold_{k}' / 'checkpoint_final.pth').stat().st_size / 1e6:.0f} MB")
    (dst / "MODEL.txt").write_text(f"source: {src}\nfolds: {folds}\ncheckpoint_final.pth slimmed to {KEEP}\n")


def fetch_uv(tools: Path):
    tools.mkdir(parents=True, exist_ok=True)
    for name, url in UV.items():
        if (tools / name).exists():
            continue
        data = urllib.request.urlopen(url).read()
        if url.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                m = [n for n in z.namelist() if n.endswith("/" + name) or n == name][0]
                (tools / name).write_bytes(z.read(m))
        else:
            with tarfile.open(fileobj=io.BytesIO(data)) as t:
                m = [x for x in t.getmembers() if x.name.endswith("/uv")][0]
                (tools / name).write_bytes(t.extractfile(m).read())
        (tools / name).chmod(0o755)
        print(f"uv: {name}")


def write_notices(path: Path):
    """Name, version and license of every Python package shipped (from the build environment, which is pinned
    to the same versions as app/requirements.txt), plus the license file text where the package includes one."""
    from importlib.metadata import distributions
    sys.path.insert(0, str(PROJ / "src"))
    from kidneycyst.webapp import _license_of
    out = ["KidneyCyst third-party notices",
           "KidneyCyst installs the following open-source packages. Each keeps its own license.",
           "paquo (GPL-3.0) and JPype1 (Apache-2.0) are installed only if a user turns on QuPath support.", ""]
    texts = []
    for dist in sorted(distributions(), key=lambda x: (x.metadata.get("Name") or "").lower()):
        n = dist.metadata.get("Name")
        if not n or n.lower() == "kidneycyst":
            continue
        out.append(f"{n} {dist.version}: {_license_of(dist)}")
        for f in dist.files or []:
            if any(k in f.name.upper() for k in ("LICENSE", "LICENCE", "COPYING")) and f.suffix in ("", ".txt", ".md", ".rst"):
                try:
                    texts.append(f"\n===== {n} {dist.version}: {f.name} =====\n"
                                 + Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace"))
                except Exception:
                    pass
                break
    out += ["", "QuPath (optional, downloaded only on request): GPL-3.0, https://qupath.github.io", "",
            "Full license texts follow."] + texts
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"notices: {path} ({len(texts)} license texts)")


PLATFORMS = {   # name: (installer file in installer/<name>/, tools to ship as (source in staging, name in files/tools))
    "Mac": ("Install KidneyCyst.command", [("uv-mac-arm64", "uv"), ("KidneyCyst.icns", "KidneyCyst.icns"), ("icon.png", "icon.png")]),
    "Windows": ("Install KidneyCyst.bat", [("uv.exe", "uv.exe"), ("KidneyCyst.ico", "KidneyCyst.ico")]),
    "Linux": ("Install KidneyCyst.sh", [("uv", "uv"), ("icon.png", "icon.png")]),
}


def _link_tree(src: Path, dst: Path):
    """Copy a folder using hard links where possible (same disk: no extra space, fast)."""
    def cp(a, b):
        try:
            os.link(a, b)
        except OSError:
            shutil.copy2(a, b)
    shutil.copytree(src, dst, copy_function=cp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dest", help="output folder; gets KidneyCyst-Mac.zip, KidneyCyst-Windows.zip, KidneyCyst-Linux.zip")
    ap.add_argument("--checkpoint", default=cli.SERVER_CHECKPOINT)
    ap.add_argument("--folds", default="0,1,2")
    ap.add_argument("--sample", default=DEFAULT_SAMPLE)
    ap.add_argument("--zip", action="store_true")
    a = ap.parse_args()
    dest = Path(a.dest).resolve()
    stage = dest / "_staging"
    if stage.exists():
        sys.exit(f"{stage} exists; remove it first")
    folds = [int(x) for x in a.folds.split(",")]
    f = stage / "files"
    (f / "app").mkdir(parents=True)
    shutil.copy2(HERE / "requirements.txt", f / "app" / "requirements.txt")
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(f / "app"), str(PROJ)], check=True)
    for w in (f / "app").glob(".gitignore"):
        w.unlink()
    export_model(Path(a.checkpoint), f / "model", folds)
    tools = stage / "alltools"
    fetch_uv(tools)
    for src, dst in (("KidneyCyst.ico", "KidneyCyst.ico"), ("KidneyCyst.icns", "KidneyCyst.icns"), ("icon_source.png", "icon.png")):
        shutil.copy2(HERE / src, tools / dst)
    # sample image + its reference area, predicted with exactly the shipped model (default: all folds)
    si = f / "sample" / "images"
    si.mkdir(parents=True)
    shutil.copy2(a.sample, si / Path(a.sample).name)
    ref = f / "sample" / "_ref"
    cli.main(["run", str(si), "--out", str(ref), "--checkpoint", str(f / "model"), "--run", "Run2", "--plate", "1"])
    import pandas as pd
    r = pd.read_csv(ref / "results.csv").iloc[0]
    (f / "sample" / "expected.json").write_text(json.dumps(
        dict(image=r.image, area_um2=float(r.area_um2), area_px=int(r.area_px), model=r.model_version), indent=1))
    shutil.rmtree(ref)
    write_notices(f / "THIRD_PARTY_NOTICES.txt")
    guide = PROJ / "docs" / "USER_GUIDE.md"
    try:
        import markdown  # optional
        body = markdown.markdown(guide.read_text(encoding="utf-8"), extensions=["tables"])
    except ImportError:
        body = "<pre>" + guide.read_text(encoding="utf-8").replace("&", "&amp;").replace("<", "&lt;") + "</pre>"
    readme = ("<!doctype html><meta charset='utf-8'><title>KidneyCyst</title><style>body{font-family:-apple-system,'Segoe UI',"
              "system-ui,sans-serif;max-width:820px;margin:24px auto;padding:0 16px;line-height:1.5;background:#F3F7FB;"
              "color:#17324D}table{border-collapse:collapse;background:#fff}td,th{border:1px solid #CAD5E2;padding:6px 10px}"
              "code{background:#EAF2FA;padding:1px 4px;border-radius:4px}</style>" + body)
    for plat, (installer, ptools) in PLATFORMS.items():
        top = dest / f"KidneyCyst-{plat}" / "KidneyCyst"
        if top.parent.exists():
            shutil.rmtree(top.parent)
        top.mkdir(parents=True)
        _link_tree(f, top / "files")
        (top / "files" / "tools").mkdir()
        for src, name in ptools:
            shutil.copy2(tools / src, top / "files" / "tools" / name)
            if name in ("uv", "uv.exe"):
                (top / "files" / "tools" / name).chmod(0o755)
        shutil.copy2(HERE / plat.lower() / installer, top / installer)
        if installer.endswith(".bat"):          # Windows wants CRLF line endings in .bat files
            p = top / installer
            p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        (top / "Read me.html").write_text(readme, encoding="utf-8")
        print(f"built {top}")
        if a.zip:
            z = shutil.make_archive(str(dest / f"KidneyCyst-{plat}"), "zip", top.parent, "KidneyCyst")
            print(f"zip: {z} ({Path(z).stat().st_size / 1e6:.0f} MB)")
    shutil.rmtree(stage)


if __name__ == "__main__":
    main()
