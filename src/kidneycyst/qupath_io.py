"""QuPath round trip for `kidneycyst` results: mask <-> polygon, GeoJSON records, project build (paquo), sync back.

Conventions
-----------
- Coordinates are in QuPath pixel units. A polygon is rasterised exactly like the training masks were
  (`eda/annotations_qupath/stage2.py`: `skimage.draw.polygon(y, x)` on the QuPath coordinates), and a predicted mask is
  turned into a polygon with `find_contours` at level 0.5 in the same index space. So mask -> polygon -> mask is the
  identity up to the light simplification (`SIMPLIFY_PX`), and an outline Nikita edits is rasterised the same way as
  every outline the model was trained on.
- One annotation per image. Several components / holes are one MultiPolygon annotation.
- Three classes: `Kidney (auto)` (as predicted), `Kidney (accepted)` (he looked and agrees), `Kidney (edited)` (optional).
  Edits are detected from the GEOMETRY (symmetric difference with the stored prediction), never from the class alone,
  because he may forget to change the class.
- The canonical record of a prediction is `<out>/geojson/<image_id>.geojson`, with `pred_sha` = hash of the mask.

paquo / Java are imported lazily, so `kidneycyst run` does not need them, and build/sync work from either Python env.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

import numpy as np

AUTO_CLASS = "Kidney (auto)"
ACCEPTED_CLASS = "Kidney (accepted)"
EDITED_CLASS = "Kidney (edited)"
CLASS_COLORS = {AUTO_CLASS: "#ff00ff", ACCEPTED_CLASS: "#00c800", EDITED_CLASS: "#ffa000"}
AREA_MEASUREMENT = "Area µm² (model)"
SIMPLIFY_PX = 0.25          # Douglas-Peucker tolerance on the contour (px); 0 = keep every half-pixel vertex
UNCHANGED_TOL_PX2 = 1.0     # an outline whose symmetric difference with the prediction is <= this (px^2) is "not edited"
DEFAULT_QUPATH_DIR = "/group/jug/aman/ZebrafishKidneyCyst_Runs/qupath/QuPath"
PROJECT_MANIFEST = "kidneycyst_project.json"


# ---------------------------------------------------------------- geometry
def mask_sha(mask: np.ndarray) -> str:
    m = np.asarray(mask, bool)
    return hashlib.sha256(np.packbits(m).tobytes() + str(m.shape).encode()).hexdigest()[:16]


def mask_to_geometry(mask: np.ndarray, simplify_px: float = SIMPLIFY_PX, target_area_px: float | None = None):
    """bool mask -> shapely (Multi)Polygon in QuPath pixel coordinates, or None if the mask is empty.
    Contours are combined with the even-odd rule, so holes and islands-in-holes come out right.

    target_area_px: if given, the outline is moved inward by a uniform sub-pixel distance so its area equals this
    (used with mask_px / RASTER_BIAS: the find_contours outline has area ~= mask pixels, while hand-drawn QuPath
    outlines are ~2% smaller than their rasterised masks; this way QuPath shows the same area as results.csv and
    re-rasterising the outline still gives the predicted mask)."""
    from shapely.geometry import Polygon
    from shapely.validation import make_valid
    from skimage.measure import find_contours

    m = np.asarray(mask, bool)
    if not m.any():
        return None
    pad = np.pad(m, 1).astype(np.float32)          # pad so shapes touching the border close
    polys = []
    for c in find_contours(pad, 0.5):
        if len(c) < 4:
            continue
        xy = np.column_stack([c[:, 1] - 1.0, c[:, 0] - 1.0])   # (row, col) -> (x, y), undo the pad
        p = Polygon(xy)
        if not p.is_valid:
            p = make_valid(p)
        if p.area > 0:
            polys.append(p)
    polys.sort(key=lambda p: -p.area)
    geom = None
    for p in polys:
        geom = p if geom is None else geom.symmetric_difference(p)
    if geom is None or geom.is_empty:
        return None
    if simplify_px > 0:
        geom = geom.simplify(simplify_px, preserve_topology=True)
    geom = _polygonal(geom)
    if geom is not None and target_area_px and geom.length > 0:
        geom = _shrink_to_area(geom, float(target_area_px))
    return snap(geom)


QUPATH_GRID = 0.01   # QuPath stores ROI coordinates rounded to 1/100 px; snap ours so a round trip is exact


def snap(geom):
    import shapely
    if geom is None or geom.is_empty:
        return geom
    return _polygonal(shapely.set_precision(geom, QUPATH_GRID))


def _shrink_to_area(geom, target: float, iters: int = 3):
    d = 0.0
    g = geom
    for _ in range(iters):
        err = g.area - target
        if abs(err) < 0.05 or g.length <= 0:
            break
        d += err / g.length
        if not (0 <= d < 1.0):          # never move an outline by a pixel or more; keep the raw contour instead
            return geom
        g2 = _polygonal(geom.buffer(-d, join_style="mitre", mitre_limit=2.0))
        if g2 is None:
            return geom
        g = g2
    return g


def _polygonal(geom):
    """Keep only polygon parts (make_valid / set operations can leave lines or points)."""
    from shapely.geometry import MultiPolygon, Polygon
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    parts = [g for g in getattr(geom, "geoms", []) if isinstance(g, (Polygon, MultiPolygon))]
    flat = []
    for g in parts:
        flat.extend(g.geoms if isinstance(g, MultiPolygon) else [g])
    if not flat:
        return None
    return flat[0] if len(flat) == 1 else MultiPolygon(flat)


def geometry_to_mask(geom, shape) -> np.ndarray:
    """Rasterise like the training masks (stage2.py: skimage.draw.polygon(y, x)); holes are cleared."""
    from shapely.geometry import MultiPolygon
    from skimage.draw import polygon as skpoly
    m = np.zeros(shape, bool)
    if geom is None or geom.is_empty:
        return m
    for p in (geom.geoms if isinstance(geom, MultiPolygon) else [geom]):
        x, y = np.asarray(p.exterior.coords).T
        rr, cc = skpoly(y, x, shape)
        m[rr, cc] = True
    for p in (geom.geoms if isinstance(geom, MultiPolygon) else [geom]):
        for h in p.interiors:
            x, y = np.asarray(h.coords).T
            rr, cc = skpoly(y, x, shape)
            m[rr, cc] = False
    return m


def iou(a, b) -> float:
    if (a is None or a.is_empty) and (b is None or b.is_empty):
        return 1.0
    if a is None or a.is_empty or b is None or b.is_empty:
        return 0.0
    u = a.union(b).area
    return float(a.intersection(b).area / u) if u > 0 else 1.0


def symdiff_px2(a, b) -> float:
    if (a is None or a.is_empty) and (b is None or b.is_empty):
        return 0.0
    if a is None or a.is_empty:
        return float(b.area)
    if b is None or b.is_empty:
        return float(a.area)
    return float(a.symmetric_difference(b).area)


# ---------------------------------------------------------------- GeoJSON records
def _rgb(hexcol):
    h = hexcol.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def make_feature(geom, name: str, cls: str = AUTO_CLASS, measurements: dict | None = None,
                 metadata: dict | None = None) -> dict:
    from shapely.geometry import mapping
    return {"type": "Feature",
            "geometry": mapping(geom) if geom is not None else None,
            "properties": {"objectType": "annotation", "name": name,
                           "classification": {"name": cls, "color": _rgb(CLASS_COLORS.get(cls, "#ff00ff"))},
                           "measurements": measurements or {}, "metadata": {k: str(v) for k, v in (metadata or {}).items()}}}


def write_geojson(path: Path, features: list[dict], extra: dict | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection", "features": [f for f in features if f.get("geometry")]}
    if extra:
        fc["kidneycyst"] = extra
    path.write_text(json.dumps(fc))


def read_geojson_geometry(path: Path):
    """Union of all feature geometries of a FeatureCollection (None if none)."""
    from shapely.geometry import shape
    from shapely.ops import unary_union
    if not Path(path).exists():
        return None
    fc = json.loads(Path(path).read_text(encoding="utf-8"))
    gs = [shape(f["geometry"]) for f in fc.get("features", []) if f.get("geometry")]
    return _polygonal(unary_union(gs)) if gs else None


# ---------------------------------------------------------------- QuPath helpers
def install_home() -> Path | None:
    """Folder of a local install (set by the launcher); holds model/, config.json, QuPath."""
    h = os.environ.get("KIDNEYCYST_HOME")
    if h:
        return Path(h)
    import sys       # started straight from a shortcut: <install>/files/env/... -> <install>/files
    p = Path(sys.prefix).resolve().parent
    return p if (p / "model" / "plans.json").exists() else None


def local_config() -> dict:
    h = install_home()
    if h is not None and (h / "config.json").exists():
        return json.loads((h / "config.json").read_text(encoding="utf-8"))
    return {}


def qupath_dir() -> Path:
    """QuPath 0.6.0 folder: PAQUO_QUPATH_DIR, else the local install's config, else the server copy."""
    d = os.environ.get("PAQUO_QUPATH_DIR") or local_config().get("qupath_dir")
    return Path(d) if d else Path(DEFAULT_QUPATH_DIR)


def _ensure_paquo_env():
    os.environ["PAQUO_QUPATH_DIR"] = str(qupath_dir())


PAQUO_REQ = ["paquo==0.9.0", "jpype1==1.7.1"]


def has_paquo() -> bool:
    import importlib.util
    return importlib.util.find_spec("paquo") is not None


def install_paquo() -> None:
    """QuPath support is optional and installed only on request: paquo is GPL-3.0 (JPype: Apache-2.0).
    Uses the uv binary shipped in the install folder; falls back to pip."""
    import subprocess
    import sys
    home = install_home()
    uvs = []
    if home is not None:
        name = "uv.exe" if os.name == "nt" else "uv"
        uvs += [home / "tools" / name, home / "tools" / "uv-mac-arm64"]
    env = dict(os.environ)
    if home is not None:
        env.setdefault("UV_CACHE_DIR", str(home / "tools" / "uv-cache"))
    for uv in uvs:
        if uv.exists():
            subprocess.run([str(uv), "pip", "install", "--python", sys.executable, *PAQUO_REQ], check=True, env=env)
            break
    else:
        subprocess.run([sys.executable, "-m", "pip", "install", *PAQUO_REQ], check=True)
    import importlib
    importlib.invalidate_caches()
    if not has_paquo():
        raise RuntimeError("QuPath support could not be installed (paquo)")


def qupath_executable() -> Path:
    d = qupath_dir()
    for c in [d / "bin" / "QuPath", d / "QuPath-0.6.0.exe", d / "QuPath.exe", d / "QuPath-0.6.0 (console).exe",
              d / "Contents" / "MacOS" / "QuPath", d / "bin" / "QuPath.sh"]:
        if c.exists():
            return c
    hits = sorted(d.glob("QuPath*.exe"))
    if hits:
        return hits[0]
    raise FileNotFoundError(f"QuPath executable not found under {d}; set PAQUO_QUPATH_DIR to the QuPath 0.6.0 folder")


def _load_results(out: Path):
    import pandas as pd
    df = pd.read_csv(out / "results.csv", dtype={"well": str})
    settings = json.loads((out / "run_settings.json").read_text(encoding="utf-8"))
    return df, settings


def _save_results(out: Path, df):
    from .report import build_report, write_tables
    write_tables(out, df)
    try:
        build_report(out)
    except Exception as e:
        print(f"note: report.html not updated ({e})")


def entry_name(row) -> str:
    """Name shown in QuPath's image list. Flagged images carry a CHECK tag so he can filter on it."""
    name = str(row["image_id"])
    flags = str(row.get("flags") or "")
    if flags and flags != "nan":
        name += f" [CHECK: {flags}]"
    return name


def build_project(out: Path, project_dir: Path | None = None, image_ids: list[str] | None = None,
                  overwrite: bool = False) -> Path:
    """Build a QuPath 0.6.0 project from a `kidneycyst run` output folder.

    out:         the `<folder>_kidneycyst` results folder
    project_dir: default `<out>/qupath`; a subset (image_ids) defaults to `<out>/qupath_subset`
    image_ids:   only these images (e.g. the reader study's "I'll draw one" queue); default all
    """
    _ensure_paquo_env()
    from jpype import JClass
    from paquo.classes import QuPathPathClass
    from paquo.images import QuPathImageType
    from paquo.projects import QuPathProject

    out = Path(out)
    df, settings = _load_results(out)
    if image_ids:
        missing = sorted(set(image_ids) - set(df.image_id))
        if missing:
            raise KeyError(f"not in {out}/results.csv: {missing[:10]}{' ...' if len(missing) > 10 else ''}")
        df = df[df.image_id.isin(image_ids)]
    project_dir = Path(project_dir) if project_dir else out / ("qupath_subset" if image_ids else "qupath")
    if project_dir.exists():
        if not overwrite:
            raise FileExistsError(f"{project_dir} exists (it may hold edits). Run `kidneycyst sync` first, then pass "
                                  f"--overwrite to rebuild, or choose another --project-dir.")
        shutil.rmtree(project_dir)

    Builder = JClass("qupath.lib.images.servers.ImageServerMetadata$Builder")
    in_root = Path(settings["input_folder"])
    model = settings.get("model_version", "")
    ids = {}
    with QuPathProject(project_dir, mode="x") as qp:
        have = {c.name for c in qp.path_classes}
        qp.path_classes = list(qp.path_classes) + [QuPathPathClass(n, color=c) for n, c in CLASS_COLORS.items()
                                                   if n not in have]
        cls = {c.name: c for c in qp.path_classes}
        for _, r in df.iterrows():
            img = in_root / r["image"]
            e = qp.add_image(img, image_type=QuPathImageType.FLUORESCENCE)
            e.image_name = entry_name(r)
            e.metadata["kidneycyst_id"] = str(r["image_id"])
            e.metadata["kidneycyst_flags"] = str(r.get("flags") if isinstance(r.get("flags"), str) else "")
            e.metadata["kidneycyst_model"] = model
            # pixel size: set explicitly (the TIFF usually carries it, but the value we measured with must win)
            px = float(r["px_um"])
            idata = e._image_data
            md = idata.getServer().getMetadata()
            idata.updateServerMetadata(Builder(md).pixelSizeMicrons(px, px).build())
            # start from the outline as it is NOW (reviewed in the tool, else the model's) and remember it as the
            # baseline that `sync` compares against
            from .review import current_geometry_path
            src = current_geometry_path(out, str(r["image_id"]))
            geom = read_geojson_geometry(src)
            (project_dir / "baseline").mkdir(exist_ok=True)
            shutil.copy2(src, project_dir / "baseline" / f"{r['image_id']}.geojson") if src.exists() else None
            st = str(r.get("status", "auto")) if isinstance(r.get("status"), str) else "auto"
            klass = {"accepted": ACCEPTED_CLASS, "edited": EDITED_CLASS}.get(st, AUTO_CLASS)
            if geom is not None:
                a = e.hierarchy.add_annotation(roi=geom, path_class=cls[klass])
                a.name = str(r["image_id"])
                a.measurements[AREA_MEASUREMENT] = float(geom.area * px * px)
                meta = a.java_object.getMetadata()
                for k, v in {"source": "nnunet", "model": model, "pred_sha": str(r.get("pred_sha", "")),
                             "kidneycyst_id": str(r["image_id"])}.items():
                    meta.put(k, v)
            e.save()
            ids[str(r["image_id"])] = e.image_name
    (project_dir / PROJECT_MANIFEST).write_text(json.dumps(
        {"results_dir": str(out.resolve()), "built": _dt.datetime.now().isoformat(timespec="seconds"),
         "model_version": model, "n_images": len(ids), "entries": ids}, indent=1))
    print(f"QuPath project: {project_dir / 'project.qpproj'}  ({len(ids)} images)")
    return project_dir / "project.qpproj"


def _project_dirs(out: Path, projects=None) -> list[Path]:
    if projects:
        return [Path(p).parent if str(p).endswith(".qpproj") else Path(p) for p in projects]
    ds = [p.parent for p in sorted(Path(out).glob("qupath*/project.qpproj"))]
    return sorted(ds, key=lambda d: (d / "project.qpproj").stat().st_mtime)   # oldest first: newest edits win


def sync(out: Path, projects=None, tol_px2: float = UNCHANGED_TOL_PX2, reviewer: str = "") -> "pd.DataFrame":
    """Read every QuPath project of `out` back, detect edits, update results.csv, fill retrain_pool/."""
    _ensure_paquo_env()
    import pandas as pd
    from shapely.ops import unary_union
    from paquo.projects import QuPathProject

    out = Path(out)
    df, settings = _load_results(out)
    df = df.set_index("image_id", drop=False)
    for c, default in [("status", "auto"), ("edited_by_human", False), ("iou_vs_auto", np.nan),
                       ("reviewed_area_um2", np.nan), ("qupath_area_um2", np.nan), ("qupath_class", ""), ("reviewer", ""), ("synced_at", ""),
                       ("qupath_project", "")]:
        if c not in df:
            df[c] = default
    df["qupath_class"] = df["qupath_class"].fillna("").astype(str)
    df["reviewer"] = df["reviewer"].fillna("").astype(str)
    df["synced_at"] = df["synced_at"].fillna("").astype(str)
    df["qupath_project"] = df["qupath_project"].fillna("").astype(str)
    df["status"] = df["status"].fillna("auto").astype(str)
    df["edited_by_human"] = df["edited_by_human"].fillna(False).astype(bool)
    now = _dt.datetime.now().isoformat(timespec="seconds")
    pool = []
    seen = {}
    for pdir in _project_dirs(out, projects):
        with QuPathProject(pdir, mode="r") as qp:
            for e in qp.images:
                iid = e.metadata.get("kidneycyst_id") if "kidneycyst_id" in e.metadata else None
                if iid is None or iid not in df.index:
                    continue
                anns = list(e.hierarchy.annotations)
                classes = sorted({a.path_class.name if a.path_class else "" for a in anns})
                geoms = [a.roi for a in anns if a.roi is not None and not a.roi.is_empty]
                new = snap(_polygonal(unary_union(geoms))) if geoms else None
                auto = snap(read_geojson_geometry(out / "geojson" / f"{iid}.geojson"))
                bpath = pdir / "baseline" / f"{iid}.geojson"
                base = snap(read_geojson_geometry(bpath)) if bpath.exists() else auto
                sd = symdiff_px2(new, base)          # changed in QuPath, relative to what the project started with
                changed = sd > tol_px2
                px = float(df.at[iid, "px_um"])
                # QuPath's own area of the ROI(s), in µm² (Java, not shapely)
                q_area = float(sum(a.java_object.getROI().getScaledArea(px, px) for a in anns
                                   if a.java_object.getROI() is not None)) if anns else 0.0
                if not changed:
                    status = "accepted" if (ACCEPTED_CLASS in classes or EDITED_CLASS in classes) else "auto"
                elif new is None:
                    status = "deleted"
                else:
                    status = "edited"
                df.at[iid, "qupath_area_um2"] = q_area
                prev = seen.get(iid)
                if prev is not None and status == "auto":
                    continue          # an older project said more than "untouched": keep it
                if not changed and (status == "auto" or df.at[iid, "status"] != "auto"):
                    continue          # untouched in QuPath: keep whatever was decided before (e.g. in the review screen)
                seen[iid] = status
                df.at[iid, "status"] = status
                df.at[iid, "edited_by_human"] = bool(changed)
                df.at[iid, "iou_vs_auto"] = iou(new, auto)
                # QuPath's own number when there is one outline; union area if several overlap
                df.at[iid, "reviewed_area_um2"] = 0.0 if new is None else (q_area if len(anns) == 1 else new.area * px * px)
                df.at[iid, "qupath_class"] = ";".join(c for c in classes if c)
                df.at[iid, "qupath_project"] = str(pdir.name)
                if status != "auto":
                    df.at[iid, "synced_at"] = now
                    if reviewer:
                        df.at[iid, "reviewer"] = reviewer
                if changed:            # make the QuPath edit the current outline for the review screen too
                    _store_review_outline(out, df, iid, new)
                if status in ("edited", "deleted", "accepted"):
                    pool.append((iid, new, status, classes))
    _write_pool(out, df, pool, settings, now)
    res = df.reset_index(drop=True)
    _save_results(out, res)
    n = res.status.value_counts().to_dict()
    print(f"sync: {n}  | edited_by_human: {int(res.edited_by_human.sum())}  -> {out / 'results.csv'}")
    return res


def _store_review_outline(out: Path, df, iid: str, geom):
    h, w = int(df.at[iid, "height"]), int(df.at[iid, "width"])
    m = geometry_to_mask(geom, (h, w))
    from PIL import Image
    (out / "review" / "masks").mkdir(parents=True, exist_ok=True)
    Image.fromarray((m * 255).astype(np.uint8)).save(out / "review" / "masks" / f"{iid}.png")
    write_geojson(out / "review" / "geojson" / f"{iid}.geojson",
                  [make_feature(geom, iid, EDITED_CLASS, metadata={"source": "qupath"})] if geom is not None else [],
                  extra={"status": "edited" if geom is not None else "deleted", "source": "qupath"})


def _pool_key(r) -> str:
    """Same key format as the training masks (stage2.py): Run_P<plate>_<well>_F<field>_a<k>."""
    try:
        if str(r["run"]) not in ("", "nan") and str(r["plate"]) not in ("", "nan"):
            return f"{r['run']}_P{int(float(r['plate']))}_{r['well']}_F{int(float(r['field']))}_a0"
    except (TypeError, ValueError):
        pass
    return f"{r['image_id']}_a0"


def _write_pool(out: Path, df, pool, settings, now):
    """retrain_pool/: GeoJSON + packbits masks (MASKS format) + manifest. Idempotent: keyed by image, rewritten."""
    import pandas as pd
    pd_dir = out / "retrain_pool"
    if not pool and not pd_dir.exists():
        return
    (pd_dir / "geojson").mkdir(parents=True, exist_ok=True)
    npz_path = pd_dir / "masks_packed.npz"
    masks = dict(np.load(npz_path)) if npz_path.exists() else {}
    man_path = pd_dir / "manifest.csv"
    man = pd.read_csv(man_path) if man_path.exists() else pd.DataFrame()
    rows = []
    for iid, geom, status, classes in pool:
        r = df.loc[iid]
        h, w = int(r["height"]), int(r["width"])
        m = geometry_to_mask(geom, (h, w))
        key = _pool_key(r)
        masks[key] = np.packbits(m)
        write_geojson(pd_dir / "geojson" / f"{iid}.geojson",
                      [make_feature(geom, str(iid), EDITED_CLASS if status == "edited" else ACCEPTED_CLASS,
                                    metadata={"status": status, "source": "human" if status != "accepted" else "nnunet+accepted"})]
                      if geom is not None else [], extra={"status": status, "image": r["image"]})
        rows.append(dict(image_id=iid, mask_key=key, image=r["image"], input_folder=settings["input_folder"],
                         status=status, label_kind="human_outline" if status == "edited" else
                         ("human_empty" if status == "deleted" else "accepted_prediction"),
                         mask_px=int(m.sum()), polygon_area_px=float(geom.area) if geom is not None else 0.0,
                         height=h, width=w, iou_vs_auto=float(r["iou_vs_auto"]), model_version=r.get("model_version", ""),
                         reviewer=r.get("reviewer", ""), synced_at=now))
    new = pd.DataFrame(rows, columns=["image_id", "mask_key"]) if not rows else pd.DataFrame(rows)
    if len(man):
        man = man[~man.image_id.isin(new.image_id)]
    man = pd.concat([man, new], ignore_index=True)
    # an image that went back to "auto" (edit undone) leaves the pool
    still = set(df.index[df.status.isin(["edited", "deleted", "accepted"])])
    gone = man[~man.image_id.isin(still)]
    for _, g in gone.iterrows():
        masks.pop(g.mask_key, None)
        (pd_dir / "geojson" / f"{g.image_id}.geojson").unlink(missing_ok=True)
    man = man[man.image_id.isin(still)]
    np.savez_compressed(npz_path, **masks)
    man.to_csv(man_path, index=False)
    (pd_dir / "README.txt").write_text(
        "Human-reviewed outlines collected by `kidneycyst sync`.\n"
        "masks_packed.npz: key = Run_P<plate>_<well>_F<field>_a0 (or <image_id>_a0), value = np.packbits of a bool HxW mask;\n"
        "  np.unpackbits(v)[:H*W].reshape(H, W). Rasterised like the training masks (skimage.draw.polygon on QuPath coords).\n"
        "manifest.csv: one row per image; label_kind = human_outline (edited) | human_empty (outline deleted: he says no kidney)\n"
        "  | accepted_prediction (prediction left unchanged but marked Kidney (accepted)).\n")


def open_in_qupath(out: Path, image_id: str, project: Path | None = None, wait: bool = False):
    """Open QuPath on one image of a project: QuPath -p project.qpproj -i <image name>."""
    out = Path(out)
    pdirs = [Path(project).parent if str(project).endswith(".qpproj") else Path(project)] if project else \
        _project_dirs(out)
    for pdir in pdirs:
        man = pdir / PROJECT_MANIFEST
        if man.exists():
            ents = json.loads(man.read_text(encoding="utf-8"))["entries"]
            if image_id in ents:
                cmd = [str(qupath_executable()), "-p", str(pdir / "project.qpproj"), "-i", ents[image_id]]
                print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
                p = subprocess.Popen(cmd) if not wait else subprocess.run(cmd)
                return p
    raise KeyError(f"{image_id} is in none of: {[str(p) for p in pdirs]}")


def open_project(project_dir: Path):
    """Open QuPath with a whole project (no image selected)."""
    p = Path(project_dir)
    p = p if p.suffix == ".qpproj" else p / "project.qpproj"
    return subprocess.Popen([str(qupath_executable()), "-p", str(p)])


def java_area_um2(project_dir: Path, image_id: str) -> float:
    """QuPath's own area for an image's annotations (for checks)."""
    _ensure_paquo_env()
    from paquo.projects import QuPathProject
    with QuPathProject(project_dir, mode="r") as qp:
        for e in qp.images:
            if e.metadata.get("kidneycyst_id") == image_id:
                px = float(e._image_data.getServer().getMetadata().getPixelWidthMicrons())
                return float(sum(a.java_object.getROI().getScaledArea(px, px) for a in e.hierarchy.annotations))
    raise KeyError(image_id)


def host_info() -> str:
    return f"{platform.node()} ({platform.system()})"
