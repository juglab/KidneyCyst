"""`kidneycyst` command line: point it at a folder of TIFFs, get outlines, areas, QC flags, a report and a QuPath project.

    kidneycyst run <folder> [--checkpoint DIR] [--folds 0,1,2] [--device auto|cuda|cpu] [--out DIR]
    kidneycyst qupath build <out> [--images ID ... | --images-file F] [--project-dir D] [--overwrite]
    kidneycyst sync <out> [--project P ...] [--reviewer NAME]
    kidneycyst open <out> <image_id>          # opens QuPath on that image

What `run` does per image (same as the KC007 evaluation): channel 0 (GFP) -> norm_gfp (global constants, no clipping)
-> nnU-Net 2D sliding window with mirroring TTA -> raw mask (NO largest-component clean-up) -> polygon
(find_contours) -> area = mask pixels * px² / RASTER_BIAS (kidneycyst.metrics.px_to_um2, rescaled if the pixel size
is not the training one).
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import hashlib
import io
import json
import os
import platform
import re
import sys
import time
from pathlib import Path

import numpy as np

from . import data as D
from . import metrics as M
from . import qupath_io as Q

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
from . import __version__ as TOOL_VERSION
SERVER_CHECKPOINT = ("/group/jug/aman/ZebrafishKidneyCyst_Runs/nnunet/results_18gb/Dataset501_KidneyCystGFP/"
                     "nnUNetTrainer_250epochs__nnUNetPlans_p512__2d")   # KC009 (25 Nov); KC007 was ..._100epochs_...


def default_checkpoint() -> str:
    """Local install (KIDNEYCYST_HOME/model) first, then the server model."""
    h = Q.install_home()
    if h is not None and (h / "model" / "plans.json").exists():
        return str(h / "model")
    return SERVER_CHECKPOINT


DEFAULT_MODEL_NAME = "KC009-p512-250ep-gfp"
# opt-in models (--model). The default is the KC009 leave-one-run-out ensemble (folds 0-2), which has held-out scores.
MODELS = {
    "kc009": dict(name=DEFAULT_MODEL_NAME, folds=None, note=""),
    "kc014-all": dict(name="KC014-p512-250ep-gfp-alldata-v1", folds=["all"],
                      note="trained on all 686 data-v1 images (Run2-4, Nov 2026 outlines); no held-out score exists; "
                           "use KC009 folds for measured accuracy"),
}
# QC thresholds (recorded in run_settings.json)
QC = dict(
    no_gfp_signal_p999_minus_median=190.0,   # same rule as eda/image_stats (gfp_empty): p99.9 - median < 190 ...
    no_gfp_signal_sigfrac=0.001,             # ... and < 0.1% of pixels above median + 5 MAD
    area_outlier_mad=3.0,                    # |area - median| > 3 * 1.4826 * MAD over the images of this run
    area_outlier_min_n=8,
    low_confidence_mean_prob=0.80,           # mean foreground softmax inside the predicted mask below this
    low_confidence_uncertain_frac=0.35,      # or (pixels with 0.2 < p < 0.8) / mask pixels above this
)
FLAG_TEXT = {
    "no_gfp_signal": "no GFP signal",
    "no_kidney_found": "no outline found",
    "touches_border": "outline reaches image boundary",
    "multi_component": "multiple disconnected regions",
    "area_outlier": "atypical area for this plate",
    "low_confidence": "model uncertainty",
}
WELL_RE = re.compile(r"Well\s*([A-Za-z])\s*0*(\d{1,2})\D+?Field\s*0*(\d+)", re.I)
WELL_RE2 = re.compile(r"(?:^|[_\-\s])([A-P])(\d{2})(?:[_\-\s]|$).*?F(?:ield)?\s*0*(\d+)", re.I)
RUN_RE = re.compile(r"Run\s*_?(\d+)", re.I)
PLATE_RE = re.compile(r"Plate\s*_?(\d+)", re.I)
TIF_EXT = {".tif", ".tiff"}


# ---------------------------------------------------------------- friendly output
_COL = {"green": "32", "yellow": "33", "red": "31", "cyan": "36", "bold": "1", "dim": "2"}


def c(text: str, color: str, stream=None) -> str:
    """Colour only on a real terminal (the window's log box gets plain text)."""
    try:
        tty = (stream or sys.stdout).isatty() and not os.environ.get("NO_COLOR")
    except Exception:
        tty = False
    return f"\033[{_COL[color]}m{text}\033[0m" if tty else text


class Heartbeat:
    """Prints '... still working (45 s)' every `every` seconds while a slow step runs, so nobody thinks it hangs."""

    def __init__(self, what: str, every: float = 15.0):
        import threading
        self.what, self.every, self.stop = what, every, threading.Event()
        self.out = sys.stdout                 # the real output, even if a later step silences stdout
        self.t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        t0 = time.time()
        while not self.stop.wait(self.every):
            print(c(f"   Processing: {self.what}. Elapsed: {time.time() - t0:.0f} s.", "dim", self.out),
                  file=self.out, flush=True)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()


class _Quiet:
    """Swallow nnU-Net's technical chatter (printed to stdout) during model loading."""

    def __enter__(self):
        self.old = sys.stdout
        sys.stdout = io.StringIO()

    def __exit__(self, *exc):
        sys.stdout = self.old


import threading as _threading
CANCEL = _threading.Event()      # set by the app's Cancel button: stop after the current image, keep what is done

DEVICE_TEXT = {"cuda": "NVIDIA GPU", "mps": "Apple GPU", "cpu": "CPU"}


# ---------------------------------------------------------------- input discovery
def parse_name(rel: Path, run_override=None, plate_override=None, root: Path | None = None) -> dict:
    """run/plate from the folder names (best effort, nearest folder first, including the input folder itself and its
    parents), well/field from the file name (Opera/Harmony export)."""
    out = dict(run="", plate=np.nan, well="", field=np.nan)
    m = WELL_RE.search(rel.name) or WELL_RE2.search(rel.stem)
    if m:
        out["well"] = f"{m.group(1).upper()}{int(m.group(2)):02d}"
        out["field"] = int(m.group(3))
    parts = (list(root.parts) if root is not None else []) + list(rel.parts[:-1])
    for part in reversed(parts):
        if not out["run"] and (mm := RUN_RE.search(part)):
            out["run"] = f"Run{int(mm.group(1))}"
        if np.isnan(out["plate"]) and (mm := PLATE_RE.search(part)):
            out["plate"] = int(mm.group(1))
    if run_override:
        out["run"] = run_override if str(run_override).lower().startswith("run") else f"Run{run_override}"
    if plate_override is not None:
        out["plate"] = int(plate_override)
    return out


def image_id(meta: dict, rel: Path) -> str:
    if meta["run"] and not np.isnan(meta["plate"]) and meta["well"] and not np.isnan(meta["field"]):
        return f"{meta['run']}_P{int(meta['plate'])}_{meta['well']}_F{int(meta['field'])}"
    s = "_".join(rel.with_suffix("").parts)
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")


def find_tiffs(folder: Path, out: Path) -> list[Path]:
    fs = []
    for p in sorted(folder.rglob("*")):
        if p.suffix.lower() in TIF_EXT and p.is_file() and out not in p.parents and not p.name.startswith("."):
            fs.append(p)
    return fs


def read_pixel_size(path: Path) -> tuple[float | None, str]:
    """µm per pixel from the TIFF (ImageJ 'unit=micron' + XResolution, OME PhysicalSizeX, or resolution unit cm)."""
    import tifffile
    try:
        with tifffile.TiffFile(path) as tf:
            if tf.ome_metadata:
                m = re.search(r'PhysicalSizeX="([0-9.eE+-]+)"', tf.ome_metadata)
                u = re.search(r'PhysicalSizeXUnit="([^"]+)"', tf.ome_metadata)
                if m and (not u or u.group(1) in ("µm", "um", "micron")):
                    v = float(m.group(1))
                    if 0.05 <= v <= 50:
                        return v, "tiff:ome"
            tags = tf.pages[0].tags
            xr = tags.get("XResolution")
            if xr is not None:
                num, den = xr.value
                ppu = num / den if den else 0
                ij = tf.imagej_metadata or {}
                unit = str(ij.get("unit", "")).lower()
                ru = int(tags["ResolutionUnit"].value) if "ResolutionUnit" in tags else 1
                v = None
                if ppu > 0 and unit in ("micron", "um", "µm", "\\u00b5m", "microns"):
                    v = 1.0 / ppu
                elif ppu > 0 and ru == 3:
                    v = 1e4 / ppu
                if v is not None and 0.05 <= v <= 50:
                    return v, "tiff:resolution"
    except Exception as e:  # unreadable metadata: fall back, but say so
        return None, f"unreadable ({type(e).__name__})"
    return None, "absent"


def read_gfp(path: Path, channel: int = 0) -> np.ndarray:
    import tifffile
    a = tifffile.imread(path)
    if a.ndim == 2:
        if channel != 0:
            raise ValueError(f"{path.name}: cannot select channel {channel} from a single-channel image.")
        return a
    if a.ndim == 3:
        if a.shape[0] <= 8:
            return a[channel]
        if a.shape[-1] <= 8:
            return a[..., channel]
    raise ValueError(f"{path.name}: unsupported image shape {a.shape}. For a z-stack, create a 2-D maximum-intensity "
                     f"projection before import.")


def gfp_stats(raw: np.ndarray) -> dict:
    a = raw.astype(np.float32)[::2, ::2]
    p50, p999 = np.percentile(a, [50, 99.9])
    mad = 1.4826 * np.median(np.abs(a - p50))
    sigfrac = float((a > p50 + 5 * max(mad, 1e-3)).mean())
    return dict(gfp_p50=float(p50), gfp_p999=float(p999), gfp_sigfrac=sigfrac)


# ---------------------------------------------------------------- model
def sha256_file(p: Path, cache: dict | None = None) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


# Model loading is slow (mostly starting PyTorch and nnU-Net), so: (1) progress is published in LOAD for the app's
# progress bar and printed as "Loading model (k/n): ..." lines; (2) a loaded model is cached for the life of the
# process, and the app starts loading it in the background as soon as it opens (preload_model).
LOAD = dict(k=0, n=0, text="", done=False, error="")
_MODEL_CACHE: dict = {}
_MODEL_LOCK = _threading.Lock()


def _stage(k: int, n: int, text: str, out=None):
    LOAD.update(k=k, n=n, text=text, done=False)
    stream = out or sys.stdout
    try:
        print(f"Loading model ({k}/{n}): {text}", file=stream, flush=True)
    except Exception:
        pass


def get_model(checkpoint, folds, checkpoint_name, device, tile_step, mirroring, out=None) -> "Model":
    """Cached Model; loads it (with progress) the first time. folds=None means every fold found."""
    key = (str(checkpoint), tuple(folds) if folds else None, checkpoint_name, device, tile_step, mirroring)
    with _MODEL_LOCK:
        m = _MODEL_CACHE.get(key)
        if m is None:
            try:
                m = Model(Path(checkpoint), folds, checkpoint_name, device, tile_step, mirroring, out=out)
            except BaseException as e:
                LOAD.update(error=f"{type(e).__name__}: {e}")
                raise
            _MODEL_CACHE[key] = m
        LOAD.update(done=True, k=LOAD.get("n", 0), text="Model ready")
        return m


def preload_model():
    """Called by the app at start-up: load the default model while the user is still choosing a folder."""
    try:      # no _Quiet here: it swaps the process-wide stdout, which a run in another thread may be using
        get_model(default_checkpoint(), None, "checkpoint_final.pth", "auto", 0.5, True)
    except Exception:
        pass


class Model:
    def __init__(self, checkpoint: Path, folds, checkpoint_name: str, device: str, tile_step: float, mirroring: bool,
                 out=None):
        nfold = len(folds) if folds else len([f for f in Path(checkpoint).glob(f"fold_*/{checkpoint_name}")
                                              if f.parent.name[5:].isdigit()])      # fold_all is not part of the ensemble
        n = 2 + max(nfold, 1)
        self._progress = (out, n)
        _stage(1, n, "starting PyTorch", out)
        import torch
        _stage(2, n, "starting nnU-Net", out)
        from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor
        if device == "auto":
            if torch.cuda.is_available():
                device = "cuda"
            elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
                device = "mps"                       # Apple Silicon GPU
            else:
                device = "cpu"
        if folds in (None, "all", ""):
            # numbered leave-one-run-out folds only: a fold_all (all-data model, e.g. KC014) in the same folder is NOT
            # silently mixed into the average; ask for it explicitly if wanted
            folds = [f for f in nnUNetPredictor.auto_detect_available_folds(str(checkpoint), checkpoint_name)
                     if str(f).isdigit()]
        self.folds = tuple(f if str(f) == "all" else int(f) for f in folds)   # "all" = the all-data model (opt-in)
        self._args = (str(checkpoint), checkpoint_name, tile_step, mirroring)
        self._build(device)
        self.ckpts = [Path(checkpoint) / f"fold_{f}" / checkpoint_name for f in self.folds]

    def _build(self, device: str):
        import torch
        from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor
        checkpoint, checkpoint_name, tile_step, mirroring = self._args
        if device == "cpu":
            n = int(os.environ.get("SLURM_CPUS_PER_TASK") or os.cpu_count() or 1)
            torch.set_num_threads(n)
        self.device = device
        self.pred = nnUNetPredictor(tile_step_size=tile_step, use_gaussian=True, use_mirroring=mirroring,
                                    perform_everything_on_device=(device == "cuda"), device=torch.device(device),
                                    verbose=False, verbose_preprocessing=False, allow_tqdm=False)
        out, n = getattr(self, "_progress", (None, 2 + len(self.folds)))
        real_load = torch.load
        count = [0]

        def load_with_progress(*args, **kw):      # nnU-Net calls torch.load once per fold model
            count[0] += 1
            _stage(2 + min(count[0], len(self.folds)), n, f"model {min(count[0], len(self.folds))} of {len(self.folds)}", out)
            return real_load(*args, **kw)
        torch.load = load_with_progress
        try:
            self.pred.initialize_from_trained_model_folder(checkpoint, use_folds=self.folds,
                                                           checkpoint_name=checkpoint_name)
        finally:
            torch.load = real_load

    def __call__(self, x: np.ndarray, px_um: float):
        """x: normalised GFP (H, W) float32 -> (bool mask, foreground probability map)."""
        img = x[None, None].astype(np.float32)                # (C=1, Z=1, H, W), as SimpleITKIO gives a 2-D image
        props = {"spacing": [999.0 * px_um, px_um, px_um]}
        try:
            seg, prob = self.pred.predict_single_npy_array(img, props, None, None, True)
        except (RuntimeError, NotImplementedError, TypeError) as e:
            if self.device != "mps":
                raise
            print(c(f"Apple GPU processing failed: {type(e).__name__}. Continuing on CPU; processing may be slower.",
                    "yellow"), flush=True)
            self._build("cpu")
            seg, prob = self.pred.predict_single_npy_array(img, props, None, None, True)
        seg = np.asarray(seg).reshape(x.shape)
        prob = np.asarray(prob)
        fg = prob[1].reshape(x.shape) if prob.shape[0] >= 2 else prob.reshape(x.shape)
        return seg == 1, fg.astype(np.float32)


# ---------------------------------------------------------------- pictures
def _display(raw: np.ndarray) -> np.ndarray:
    """Display scaling only (never used for the model): per-image 0.5..99.95 percentile stretch -> uint8."""
    a = raw.astype(np.float32)
    lo, hi = np.percentile(a[::2, ::2], [0.5, 99.95])
    return (np.clip((a - lo) / max(hi - lo, 1.0), 0, 1) * 255).astype(np.uint8)


def _outline(mask: np.ndarray, width: int = 2) -> np.ndarray:
    from scipy.ndimage import binary_dilation, binary_erosion
    edge = mask & ~binary_erosion(mask)
    return binary_dilation(edge, iterations=max(width - 1, 0)) if width > 1 else edge


def overlay_rgb(gray: np.ndarray, mask: np.ndarray) -> np.ndarray:
    rgb = np.repeat(gray[..., None], 3, axis=2)
    e = _outline(mask, 2)
    rgb[e] = (255, 133, 0)          # detection orange: a model candidate
    return rgb


def crop_box(mask: np.ndarray, size: int = 320):
    h, w = mask.shape
    if mask.any():
        ys, xs = np.nonzero(mask)
        cy, cx = (ys.min() + ys.max()) // 2, (xs.min() + xs.max()) // 2
        size = int(min(max(size, 1.3 * max(np.ptp(ys), np.ptp(xs))), min(h, w)))
    else:
        cy, cx = h // 2, w // 2
        size = min(h, w)
    y0 = int(np.clip(cy - size // 2, 0, h - size))
    x0 = int(np.clip(cx - size // 2, 0, w - size))
    return slice(y0, y0 + size), slice(x0, x0 + size)


def jpeg_b64(a: np.ndarray, px: int = 200) -> str:
    from PIL import Image
    im = Image.fromarray(a)
    im = im.resize((px, px), Image.BILINEAR)
    b = io.BytesIO()
    im.save(b, format="JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def save_png(path: Path, a: np.ndarray):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(a).save(path, optimize=True)


# ---------------------------------------------------------------- run
class _Skip(Exception):
    pass


BETA_FLAGS = ("flag_grade_uncertain",)
BETA_NOTE = "beta, not yet validated against Nikita's own grades and measurements"


def grade_model_version() -> str:
    from . import morphometry as MO
    p = MO.GRADE_MODEL_PATH
    if not p.exists():
        return "none (grade_model_v1.json not installed: grade columns are empty)"
    try:
        g = json.loads(p.read_text())
        return f"{g.get('name', p.stem)} {g.get('version', '')} sha={hashlib.sha256(p.read_bytes()).hexdigest()[:12]}".strip()
    except Exception as e:
        return f"unreadable ({type(e).__name__})"


def beta_measures(gnorm, mask, px: float, area_um2: float) -> dict:
    """BETA: elbow-to-elbow length (two definitions) and the 3-class grade, from the predicted outline."""
    from . import morphometry as MO
    out = dict(elbow_straight_um_beta=np.nan, elbow_midline_um_beta=np.nan, elbow_line_px="", grade_beta="",
               p_normal=np.nan, p_unfused=np.nan, p_cyst=np.nan, grade_confident=False, flag_grade_uncertain=False)
    if not mask.any():
        return out
    try:
        e = MO.elbow(mask, px)
        out.update(elbow_straight_um_beta=e["elbow_straight_um"], elbow_midline_um_beta=e["elbow_midline_um"])
        if e["elbow_p1"] is not None:                 # (row, col) -> "x1,y1,x2,y2" in image pixels, for drawing
            (r1, c1), (r2, c2) = e["elbow_p1"], e["elbow_p2"]
            out["elbow_line_px"] = f"{c1},{r1},{c2},{r2}"
        g = MO.grade(MO.grade_features(gnorm, mask, px, area_um2))
        out.update(grade_beta=g["grade_beta"], p_normal=g["p_normal"], p_unfused=g["p_unfused"], p_cyst=g["p_cyst"],
                   grade_confident=bool(g["grade_confident"]),
                   flag_grade_uncertain=bool(g["grade_beta"]) and not g["grade_confident"])
    except Exception as ex:                           # a beta measure must never stop a run
        print(f"note: beta measures not computed ({type(ex).__name__}: {ex})", flush=True)
    return out


def prepare_output(out: Path, force: bool):
    """Refuse to overwrite reviewed results unless force; with force, set earlier human decisions aside (never deleted)."""
    reviewed = [p for p in out.glob("qupath*/project.qpproj")] + ([out / "review"] if (out / "review").exists() else [])
    from .library import has_results
    if has_results(out) and not reviewed:
        import pandas as pd
        st = pd.read_csv(out / "results.csv", usecols=lambda c: c == "status")
        if "status" in st and (st.status.fillna("auto") != "auto").any():
            reviewed.append(out / "results.csv")
    if reviewed and not force:
        sys.exit(f"{out} contains an existing QuPath project or reviewed results. To run again, use --force: the "
                 f"existing results are archived in a replaced_… folder (nothing is deleted). Or use --out <new folder>.")
    if force and out.exists():
        # never mix old human decisions with new predictions: set them aside, nothing is deleted
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        for old in [out / "review", out / "retrain_pool", *out.glob("qupath*")]:
            if old.is_dir() and not old.name.startswith("replaced_"):
                old.rename(out / f"replaced_{stamp}_{old.name}")
                print(f"note: earlier {old.name}/ moved to replaced_{stamp}_{old.name}/")


def cmd_run(a) -> Path:
    import pandas as pd
    from skimage.measure import label

    folder = Path(a.folder).resolve()
    CANCEL.clear()
    if not folder.is_dir():
        sys.exit(f"The path is not a folder: {folder}")
    out = Path(a.out).resolve() if a.out else folder.parent / f"{folder.name}_kidneycyst"
    prepare_output(out, a.force)
    out.mkdir(parents=True, exist_ok=True)
    files = find_tiffs(folder, out)
    if a.limit:
        files = files[: a.limit]
    if not files:
        sys.exit("No TIFF images found in this folder or its subfolders. Select a folder containing .tif or .tiff images.")
    print(c(f"TIFF images found: {len(files)}. Input: {folder}", "bold"), flush=True)
    print(f"Output folder: {out}", flush=True)

    t0 = time.time()
    a.checkpoint = a.checkpoint or default_checkpoint()
    spec = MODELS[a.model]
    if a.model != "kc009":
        if a.model_name == DEFAULT_MODEL_NAME:
            a.model_name = spec["name"]
        if spec["folds"] and not (Path(a.checkpoint) / f"fold_{spec['folds'][0]}" / a.checkpoint_name).exists():
            alt = Path(SERVER_CHECKPOINT) / f"fold_{spec['folds'][0]}" / a.checkpoint_name
            if not alt.exists():
                sys.exit(f"The model {spec['name']} is not included in this installation ({a.checkpoint}).")
            a.checkpoint = SERVER_CHECKPOINT
        print(c(f"NOTE: using {spec['name']}: {spec['note']}.", "yellow"), flush=True)
    print(c("Loading model…", "cyan"), flush=True)
    real_out = sys.stdout
    with Heartbeat("loading the model"), _Quiet():
        folds_req = MODELS[a.model]["folds"] or ([int(f) for f in a.folds.split(",")] if a.folds not in (None, "all") else None)
        model = get_model(a.checkpoint, folds_req,
                          a.checkpoint_name, a.device, a.tile_step, not a.no_mirroring, out=real_out)
        ck_sha = {str(p): sha256_file(p) for p in model.ckpts}
    combo = hashlib.sha256("".join(ck_sha[str(p)] for p in model.ckpts).encode()).hexdigest()[:12]
    model_version = f"{a.model_name} folds={','.join(map(str, model.folds))} {a.checkpoint_name} sha={combo}"
    print(c(f"Model loaded in {time.time() - t0:.0f} s. Device: {DEVICE_TEXT.get(model.device, model.device)}.", "green"),
          flush=True)
    print(f"(model: {model_version})", flush=True)
    print(c(f"Processing {len(files)} images. The first image may take longer.", "cyan"), flush=True)
    t_img0 = time.time()

    for sub in ("overlays", "masks", "geojson"):
        (out / sub).mkdir(exist_ok=True)
    rows, thumbs, errors = [], {}, []
    used_ids = set()
    cancelled = False
    for i, f in enumerate(files):
        if CANCEL.is_set() or (a.cancel_file and Path(a.cancel_file).exists()):
            cancelled = True
            print(c(f"Detection cancelled. Results retained for {i} of {len(files)} images.", "yellow"), flush=True)
            break
        rel = f.relative_to(folder)
        meta = parse_name(rel, a.run, a.plate, folder)
        iid = image_id(meta, rel)
        if iid in used_ids:                       # never let two files share an output name
            iid = f"{iid}__{re.sub(r'[^A-Za-z0-9]+', '_', str(rel.parent))}"
        used_ids.add(iid)
        t1 = time.time()
        try:
            raw = read_gfp(f, a.channel)
        except Exception as e:
            errors.append(dict(image=str(rel), error=str(e)))
            print(f"[{i + 1}/{len(files)}] {rel}: skipped — {e}", flush=True)
            continue
        px, src = read_pixel_size(f)
        if px is None or a.pixel_size:
            px, src = (a.pixel_size, "--pixel-size") if a.pixel_size else (D.UM_PER_PX, f"default ({src})")
        st = gfp_stats(raw)
        gnorm = D.norm_gfp(raw)
        with Heartbeat(f"image {i + 1} of {len(files)}"):
            mask, fg = model(gnorm, px)
        lab = label(mask, connectivity=2)
        n_comp = int(lab.max())
        n_px = int(mask.sum())
        area = float(M.px_to_um2(n_px) * (px / D.UM_PER_PX) ** 2)     # px_to_um2 assumes the training pixel size
        geom = Q.mask_to_geometry(mask, target_area_px=n_px / M.RASTER_BIAS)
        sha = Q.mask_sha(mask)
        mean_p = float(fg[mask].mean()) if n_px else np.nan
        unc = float(((fg > 0.2) & (fg < 0.8)).sum() / max(n_px, 1)) if n_px else np.nan
        border = bool(mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any())
        no_gfp = (st["gfp_p999"] - st["gfp_p50"] < QC["no_gfp_signal_p999_minus_median"]) and \
                 (st["gfp_sigfrac"] < QC["no_gfp_signal_sigfrac"])
        poly_area = float(geom.area * px * px) if geom is not None else 0.0
        r = dict(image_id=iid, image=str(rel), **meta, area_um2=area if n_px else 0.0, area_px=n_px,
                 polygon_area_um2=poly_area, n_components=n_comp, mean_fg_prob=mean_p, uncertain_frac=unc,
                 flag_no_gfp_signal=bool(no_gfp), flag_no_kidney_found=n_px == 0, flag_touches_border=border,
                 flag_multi_component=n_comp > 1, flag_area_outlier=False,
                 flag_low_confidence=bool(n_px and (mean_p < QC["low_confidence_mean_prob"] or
                                                    unc > QC["low_confidence_uncertain_frac"])),
                 px_um=px, px_source=src, height=mask.shape[0], width=mask.shape[1], pred_sha=sha,
                 model_version=model_version, **st)
        r.update(beta_measures(gnorm, mask, px, r["area_um2"]))
        rows.append(r)
        save_png(out / "masks" / f"{iid}.png", (mask * 255).astype(np.uint8))
        gray = _display(raw)
        ov = overlay_rgb(gray, mask)
        save_png(out / "overlays" / f"{iid}.png", ov)
        from . import report as RP
        RP.save_thumbs(out, iid, gray, mask)
        feats = [Q.make_feature(geom, iid, Q.AUTO_CLASS, {Q.AREA_MEASUREMENT: poly_area},
                                {"source": "nnunet", "model": model_version, "pred_sha": sha, "kidneycyst_id": iid})] \
            if geom is not None else []
        Q.write_geojson(out / "geojson" / f"{iid}.geojson", feats,
                        extra=dict(image=str(rel), px_um=px, area_um2=r["area_um2"], area_px=n_px, pred_sha=sha,
                                   model=model_version))
        done_n = i + 1
        left = (time.time() - t_img0) / done_n * (len(files) - done_n)
        eta = f"; estimated remaining: {left / 60:.0f} min" if left >= 90 else (f"; estimated remaining: {left:.0f} s" if left > 0 else "")
        res = (f"{r['area_um2']:,.0f} µm²" + (f", {n_comp} disconnected regions" if n_comp > 1 else "")) if n_px else "no outline detected"
        print(f"[{done_n}/{len(files)}] {iid}: " + c(res, "yellow" if (n_comp != 1) else "green")
              + c(f" ({time.time() - t1:.0f} s{eta})", "dim"), flush=True)

    df = pd.DataFrame(rows)
    if len(df):
        # area outlier: robust z within each run/plate group (or all images when names carry no plate)
        grp = df["run"].astype(str) + "_" + df["plate"].astype(str)
        for g, idx in df.groupby(grp).groups.items():
            a_ = df.loc[idx, "area_um2"]
            a_ = a_[a_ > 0]
            if len(a_) >= QC["area_outlier_min_n"]:
                med = a_.median()
                mad = 1.4826 * (a_ - med).abs().median()
                if mad > 0:
                    df.loc[a_.index, "flag_area_outlier"] = (a_ - med).abs() > QC["area_outlier_mad"] * mad
        fl = [c for c in df.columns if c.startswith("flag_") and c not in BETA_FLAGS]   # beta flags: not in review triage
        df["flags"] = df[fl].apply(lambda s: "; ".join(FLAG_TEXT[c[5:]] for c in fl if s[c]), axis=1)
        df["flagged"] = df[fl].any(axis=1)
        df["status"] = "auto"
        df["edited_by_human"] = False
        df["iou_vs_auto"] = np.nan
        df["reviewed_area_um2"] = np.nan
        lead = ["image_id", "image", "run", "plate", "well", "field", "area_um2", "area_px", "polygon_area_um2",
                "n_components", "flagged", "flags", "status", "edited_by_human", "iou_vs_auto", "reviewed_area_um2",
                "mean_fg_prob", "uncertain_frac"]
        df = df[lead + [c for c in df.columns if c not in lead]]
        df = df.sort_values(["flagged", "run", "plate", "well", "field", "image_id"],
                            ascending=[False, True, True, True, True, True]).reset_index(drop=True)
    pd.DataFrame(errors).to_csv(out / "skipped.csv", index=False) if errors else None
    if not len(df):                       # nothing finished: keep any earlier results as they are, write no empty table
        sys.exit("Detection was cancelled before the first image finished. Nothing was saved." if cancelled else
                 "No image could be processed. Nothing was saved." + (" See skipped.csv for the reason." if errors else ""))
    settings = dict(
        tool="kidneycyst", tool_version=TOOL_VERSION, command=" ".join(sys.argv),
        date=_dt.datetime.now().isoformat(timespec="seconds"), host=Q.host_info(), input_folder=str(folder),
        output_folder=str(out), n_images=len(df), n_skipped=len(errors), cancelled=cancelled,
        model_name=a.model_name, model_version=model_version, model_choice=a.model,
        beta_measures=dict(note=BETA_NOTE, grade_model=grade_model_version(),
                           elbow="elbow_straight_um_beta = longest straight line across the outline (max Feret); "
                                 "elbow_midline_um_beta = longest path along the outline's skeleton"),
        training_data=spec["note"] or "KC009 leave-one-run-out folds 0-2 (data v1); held-out scores in Help > Model & validation", checkpoint_dir=str(Path(a.checkpoint).resolve()),
        checkpoint_name=a.checkpoint_name, folds=list(model.folds), checkpoint_sha256=ck_sha, device=model.device,
        tile_step_size=a.tile_step, mirroring=not a.no_mirroring, channel=a.channel,
        normalisation=dict(rule="(x - 163) / 13700, no clipping", GFP_BG=D.GFP_BG, GFP_SCALE=D.GFP_SCALE),
        pixel_size_default_um=D.UM_PER_PX, pixel_size_override_um=a.pixel_size,
        pixel_sizes_used=({f"{k:.6f}": int(v) for k, v in df.px_um.value_counts().items()} if len(df) else {}),
        pixel_size_sources=(df.px_source.value_counts().to_dict() if len(df) else {}),
        area_rule="area_um2 = mask_px * px_um^2 / RASTER_BIAS (calibrated to QuPath polygon areas); "
                  "polygon_area_um2 = area of the exported outline (what QuPath shows)",
        raster_bias=M.RASTER_BIAS, mask_postprocessing="none (raw nnU-Net mask, no largest-component step)",
        polygon=dict(method="skimage find_contours level 0.5, even-odd holes", simplify_px=Q.SIMPLIFY_PX),
        qc_thresholds=QC, versions=_versions(), seconds=round(time.time() - t0, 1),
    )
    (out / "run_settings.json").write_text(json.dumps(settings, indent=1, default=str))
    from . import report as RP
    from .review import carry_human
    df = carry_human(out / "results.csv", df)     # human elbow/grade measurements belong to the image: keep them
    RP.write_tables(out, df)
    RP.build_report(out)
    try:                                  # saved runs: register this run and keep a frozen "detected" report
        if a.no_library:
            raise _Skip()
        from . import library as LIB
        LIB.register(out)
        LIB.snapshot(out, "detected")
    except _Skip:
        pass
    except Exception as e:
        print(f"note: run not added to the saved runs list ({e})")
    nfl = int(df.flagged.sum()) if len(df) else 0
    print(c(f"Processing complete: {len(df)} images in {(time.time() - t0) / 60:.1f} min. Flagged: {nfl}.", "green"), flush=True)
    print(f"Results table: {out / 'results.xlsx'}   Report: {out / 'report.html'}", flush=True)
    if a.qupath:
        try:
            Q.build_project(out, overwrite=a.force)
        except Exception as e:             # QuPath missing/broken must not lose the results
            print(f"note: QuPath project not made ({type(e).__name__}: {e}). Results, report and table are complete.")
    return out


def cmd_info(a):
    """One JSON line: what a remote computer offers (used by the app's 'Test connection')."""
    info = dict(tool="kidneycyst", tool_version=TOOL_VERSION, model_name=DEFAULT_MODEL_NAME, checkpoint=default_checkpoint(),
                host=platform.node(), system=f"{platform.system()} {platform.machine()}")
    try:
        mt = Path(info["checkpoint"]) / "MODEL.txt"
        info["model_source"] = mt.read_text().splitlines()[0] if mt.exists() else info["checkpoint"]
        if a.no_device:                   # cluster login node: no PyTorch here, the GPU comes from the job queue
            print("KIDNEYCYST_INFO " + json.dumps(info), flush=True)
            return
        import torch
        if torch.cuda.is_available():
            info["device"], info["device_name"] = "cuda", torch.cuda.get_device_name(0)
        elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            info["device"], info["device_name"] = "mps", "Apple GPU"
        else:
            info["device"], info["device_name"] = "cpu", "CPU"
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
    print("KIDNEYCYST_INFO " + json.dumps(info), flush=True)


def _versions():
    from importlib.metadata import PackageNotFoundError, version
    v = {"python": sys.version.split()[0]}
    for m in ("torch", "nnunetv2", "numpy", "scikit-image", "shapely", "tifffile", "paquo"):
        try:
            v[m] = version(m)
        except PackageNotFoundError:
            pass
    return v


# ---------------------------------------------------------------- other commands
def cmd_build(a):
    ids = list(a.images or [])
    if a.images_file:
        ids += [l.strip() for l in Path(a.images_file).read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    Q.build_project(Path(a.out), Path(a.project_dir) if a.project_dir else None, ids or None, a.overwrite)


def cmd_sync(a):
    Q.sync(Path(a.out), a.project or None, a.tolerance, a.reviewer)


def cmd_open(a):
    Q.open_in_qupath(Path(a.out), a.image_id, a.project, wait=a.wait)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kidneycyst", description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", action="version", version=f"kidneycyst {TOOL_VERSION}")
    sp = ap.add_subparsers(dest="cmd", required=True)

    r = sp.add_parser("run", help="predict every TIFF in a folder")
    r.add_argument("folder")
    r.add_argument("--out", help="output folder (default <folder>_kidneycyst next to the input)")
    r.add_argument("--checkpoint", default=None, help="nnU-Net trained model folder (with fold_k/)")
    r.add_argument("--folds", default="all", help="'all' (ensemble of every fold found) or e.g. '0' or '0,1,2'")
    r.add_argument("--checkpoint-name", default="checkpoint_final.pth")
    r.add_argument("--model", default="kc009", choices=sorted(MODELS),
                   help="kc009 (default): 3 leave-one-run-out fold models with held-out scores. "
                        "kc014-all: one model trained on all data v1, no held-out score (opt-in)")
    r.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    r.add_argument("--device", default="auto", choices=["auto", "cuda", "mps", "cpu"])
    r.add_argument("--channel", type=int, default=0, help="GFP channel index (default 0)")
    r.add_argument("--pixel-size", type=float, default=None, help="µm per pixel; overrides the TIFF metadata")
    r.add_argument("--run", default=None, help="run label if the folder names do not contain 'RunN'")
    r.add_argument("--plate", type=int, default=None, help="plate number if the folder names do not contain 'PlateN'")
    r.add_argument("--tile-step", type=float, default=0.5)
    r.add_argument("--no-mirroring", action="store_true", help="faster, slightly less accurate")
    r.add_argument("--limit", type=int, default=0, help="only the first N images (testing)")
    r.add_argument("--qupath", action="store_true", help="also build the QuPath project")
    r.add_argument("--force", action="store_true",
                   help="overwrite an output folder that already has a QuPath project or reviewed results")
    r.add_argument("--cancel-file", default=None, help=argparse.SUPPRESS)      # remote runs: stop when this file appears
    r.add_argument("--no-library", action="store_true", help=argparse.SUPPRESS)  # remote runs: the local app keeps the list
    r.set_defaults(fn=cmd_run)

    i = sp.add_parser("info", help="print this installation's version, model and processing device (JSON)")
    i.add_argument("--no-device", action="store_true", help="skip the graphics card check (cluster login nodes)")
    i.set_defaults(fn=cmd_info)

    q = sp.add_parser("qupath", help="QuPath project tools")
    qs = q.add_subparsers(dest="qcmd", required=True)
    b = qs.add_parser("build", help="build a QuPath 0.6.0 project with the predicted outlines")
    b.add_argument("out", help="the <folder>_kidneycyst results folder")
    b.add_argument("--images", nargs="*", help="only these image ids")
    b.add_argument("--images-file", help="text file with one image id per line")
    b.add_argument("--project-dir")
    b.add_argument("--overwrite", action="store_true")
    b.set_defaults(fn=cmd_build)

    s = sp.add_parser("sync", help="read QuPath edits back into results.csv and retrain_pool/")
    s.add_argument("out")
    s.add_argument("--project", nargs="*", help="project folder(s) or .qpproj (default: every qupath*/ in out)")
    s.add_argument("--reviewer", default="", help="name written to the 'reviewer' column for reviewed images")
    s.add_argument("--tolerance", type=float, default=Q.UNCHANGED_TOL_PX2,
                   help="px² of outline change below which an image counts as not edited")
    s.set_defaults(fn=cmd_sync)

    o = sp.add_parser("open", help="open QuPath on one image of the project")
    o.add_argument("out")
    o.add_argument("image_id")
    o.add_argument("--project")
    o.add_argument("--wait", action="store_true")
    o.set_defaults(fn=cmd_open)

    a = ap.parse_args(argv)
    if os.name == "nt":
        os.system("")                        # enables colour codes in the Windows console
    for st in (sys.stdout, sys.stderr):      # Windows consoles cannot print µ/² in every code page
        try:
            st.reconfigure(errors="replace")
        except Exception:
            pass
    a.fn(a)


if __name__ == "__main__":
    main()
