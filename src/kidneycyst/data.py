"""Single source of truth for what the model sees.

The EDA notebook and the (future) nnU-Net converter both import this module, so what we *show*
and what we *train on* cannot drift apart.

Contract (data-contract v1):
  - one row per TIFF (2,073); `usable` = passes every exclusion rule below, in this order;
  - `reason` = the FIRST rule that excluded an image ('' if usable);
  - GFP = channel 0, brightfield = channel 1 (UNCONFIRMED by Nikita; GFP identity verified visually);
  - mask = union of all polygons of an image, rasterised from QuPath (see eda/annotations_qupath);
  - splits = leave-one-run-out, grouped by well.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import tifffile

PROJ = Path("/home/aman.kukde/KidneyCyst")
EDA = PROJ / "eda"
RAW = Path("/group/jug/aman/Datasets/Zebrafish_KidneyCyst/raw")
MASKS = Path("/group/jug/aman/ZebrafishKidneyCyst_Runs/eda/masks")
KEY = ["run", "plate", "well", "field"]

GFP_BG = 163.0        # detector offset: identical across runs (image_stats)
GFP_SCALE = 13700.0   # pooled q99 of per-image p99.9 (image_stats); one GLOBAL scale, never per image
HARD_PLATES = {("Run3", 3), ("Run4", 4)}   # ~65% fuzzy/empty: report separately
UM_PER_PX = 1.19595

# exclusion rules, applied in this order; the first one that fires is the recorded reason
REASONS = [
    ("bad_tiff", "single-channel or all-zero TIFF"),
    ("no_polygon", "no QuPath outline (unannotated is NOT 'normal')"),
    ("multi_instance", "2 outlines in one field with different grades (Excel rows '4.1'/'4.2'): ambiguous, excluded"),
    ("no_label_row", "outline but no Excel row"),
    ("fuzzy", "fuzzy / excluded / yellow row in Excel"),
    ("grade_unknown", "grade missing, 'unknown' (U/M)"),
]


def _read(p):
    return pd.read_csv(p)


def build_index(fuzzy_policy: str = "all", drop_uncertain: bool = False) -> pd.DataFrame:
    """Return one row per TIFF with label columns, `usable` and `reason`.

    fuzzy_policy: 'all'     -> fuzzy_flag | fuzzy_soft | excluded_flag | yellow_row   (conservative, default)
                  'lenient' -> fuzzy_flag | excluded_flag
    drop_uncertain: also drop rows whose grade has a '?' / ambiguous multi-label (strict set).
    """
    idx = _read(EDA / "index_completeness/master_index.csv")
    st = _read(EDA / "image_stats/image_stats.csv")
    lab = _read(EDA / "labels_excel/labels_tidy.csv")   # primary parse (NOT master_labels.csv: join_check truncated 4.1/4.2 to 4)
    poly = _read(EDA / "annotations_qupath/polygons.csv")

    df = idx[KEY + ["rel_path", "n_pages", "shape", "has_qupath", "qupath_entry", "qupath_nObjects"]].copy()
    df["rel_path"] = df.rel_path.astype(str)
    df["n_ch"] = df["shape"].str.extract(r"\((\d+),")[0].astype(float)
    df["field"] = df.field.astype(int)

    stc = ["gfp_empty", "gfp_faint", "gfp_touch_border", "bf_empty", "c0_p50", "c0_p999", "c1_p50"]
    s = st[KEY + [c for c in stc if c in st.columns]].copy()
    s["field"] = s.field.astype(int)
    df = df.merge(s, on=KEY, how="left")
    df["all_zero"] = (df.c0_p999.fillna(0) == 0) & (df.c1_p50.fillna(0) == 0) & df.c0_p50.notna()

    p = poly.groupby(KEY).agg(n_poly=("area_px", "size"), poly_area_px=("area_px", "sum")).reset_index()
    df = df.merge(p, on=KEY, how="left")
    df["n_poly"] = df.n_poly.fillna(0).astype(int)

    lab = lab[lab.run.isin(["Run2", "Run3", "Run4"])].copy()
    lab["field"] = pd.to_numeric(lab.field, errors="coerce")
    lab = lab.dropna(subset=["field"])
    # fractional fields ('4.1', '4.2') = two Excel rows for ONE image; never truncate them to field 4
    lab = lab[np.isclose(lab.field, lab.field.round())].copy()
    lab["field"] = lab.field.round().astype(int)
    lc = ["area_um2", "cyst_grade", "grade_raw", "grade_uncertain", "grade_ambiguous", "fuzzy_flag", "fuzzy_soft",
          "excluded_flag", "yellow_row", "treatment_um", "reason_text"]
    # duplicate (run, plate, well, field) rows: prefer the row that carries an area; never two labelled rows
    lab = lab.assign(_has=lab.area_um2.notna()).sort_values("_has", ascending=False, kind="stable")
    _d = lab[lab.duplicated(KEY, keep=False)]
    _bad = _d.groupby(KEY)["_has"].sum()
    assert not (_bad > 1).any(), f"two labelled Excel rows share one image key: {_bad[_bad > 1].index.tolist()}"
    lab = lab.drop_duplicates(KEY, keep="first")[KEY + lc]
    df = df.merge(lab, on=KEY, how="left")
    df["has_label_row"] = df.cyst_grade.notna() | df.area_um2.notna()

    f = lambda c: df[c].fillna(False).astype(bool)
    if fuzzy_policy == "all":
        df["fuzzy"] = f("fuzzy_flag") | f("fuzzy_soft") | f("excluded_flag") | f("yellow_row")
    elif fuzzy_policy == "lenient":
        df["fuzzy"] = f("fuzzy_flag") | f("excluded_flag")
    else:
        raise ValueError(fuzzy_policy)
    uncertain = f("grade_uncertain") | f("grade_ambiguous")

    df["group"] = df.run + "_P" + df.plate.astype(str) + "_" + df.well          # one larva-ish unit: a well
    df["name"] = df.run + "_P" + df.plate.astype(str) + "_" + df.well + "_F" + df.field.astype(str)
    df["hard_plate"] = [(r, int(pl)) in HARD_PLATES for r, pl in zip(df.run, df.plate)]

    conds = [
        ("bad_tiff", (df.n_ch != 2) | df.all_zero),
        ("no_polygon", df.n_poly == 0),
        ("multi_instance", df.n_poly > 1),
        ("no_label_row", ~df.has_label_row),
        ("fuzzy", df.fuzzy),
        ("grade_unknown", df.cyst_grade.isna() | (df.cyst_grade == "unknown")),
    ]
    if drop_uncertain:
        conds.append(("grade_uncertain", uncertain))
    reason = pd.Series("", index=df.index)
    for name, c in conds:
        reason = reason.where(reason != "", np.where(c, name, ""))
    df["reason"] = reason
    df["usable"] = df.reason == ""
    df["grade3"] = df.cyst_grade.map({"normal": "normal", "unfused": "unfused", "cyst_1side": "cyst",
                                      "cyst_2side": "cyst", "cyst_unspec": "cyst"})
    return df.sort_values(KEY).reset_index(drop=True)


def waterfall(df: pd.DataFrame) -> pd.DataFrame:
    """How many images survive each rule (first-failing-reason accounting)."""
    n = len(df)
    rows = [("all TIFFs", n)]
    left = n
    for name, desc in REASONS:
        k = int((df.reason == name).sum())
        left -= k
        rows.append((f"- {name}: {desc}", -k))
        rows.append((f"= after {name}", left))
    if "grade_uncertain" in set(df.reason):
        k = int((df.reason == "grade_uncertain").sum())
        left -= k
        rows.append(("- grade_uncertain", -k))
        rows.append(("= after grade_uncertain", left))
    return pd.DataFrame(rows, columns=["step", "n"])


# ---------------------------------------------------------------- pixels
def path(row) -> Path:
    return RAW / row["rel_path"]


def load_raw(row) -> np.ndarray:
    """(2, 1080, 1080) uint16: ch0 = GFP, ch1 = brightfield."""
    return tifffile.imread(path(row))


def norm_gfp(x: np.ndarray) -> np.ndarray:
    """Global GFP scaling: (x - 163) / 13700. Same constants for every image/run. NO clipping:
    clipping pinned ~1% of in-outline pixels (the brightest ones) and truncated sensor noise below background.
    Range is therefore roughly [-0.012, 4.8] (raw 0..65535)."""
    return (x.astype(np.float32) - GFP_BG) / GFP_SCALE


def norm_bf(x: np.ndarray) -> np.ndarray:
    """Brightfield: per-image robust median/IQR (BF varies with illumination, not with biology)."""
    x = x.astype(np.float32)
    q1, med, q3 = np.percentile(x[::4, ::4], [25, 50, 75])
    return (x - med) / max(q3 - q1, 1.0)


@lru_cache(maxsize=16)
def _npz(run: str, plate: int):
    return np.load(MASKS / f"{run}_Plate{plate}_masks_packed.npz")


def load_mask(row) -> np.ndarray:
    """Union of every polygon of this image -> bool (1080, 1080)."""
    z = _npz(row["run"], int(row["plate"]))
    pre = f"{row['run']}_P{int(row['plate'])}_{row['well']}_F{int(row['field'])}_a"
    ks = [k for k in z.keys() if k.startswith(pre)]
    if not ks:
        raise KeyError(f"no mask for {row['name']}")
    m = np.zeros(1080 * 1080, bool)
    for k in ks:
        m |= np.unpackbits(z[k])[: 1080 * 1080].astype(bool)
    return m.reshape(1080, 1080)


def model_input(row, with_bf: bool = False):
    """Exactly what the model gets: (C,H,W) float32 [+ the target mask]. GFP only by default."""
    raw = load_raw(row)
    chans = [norm_gfp(raw[0])]
    if with_bf:
        chans.append(norm_bf(raw[1]))
    return np.stack(chans), load_mask(row)


# ---------------------------------------------------------------- splits
def loro_splits(df: pd.DataFrame, use_only_usable: bool = True) -> dict:
    """Leave-one-run-out. Wells never straddle folds (a well lives inside one run)."""
    d = df[df.usable] if use_only_usable else df
    out = {}
    for held in sorted(d.run.unique()):
        te = d[d.run == held]
        tr = d[d.run != held]
        assert not (set(te.group) & set(tr.group)), "well leaked across folds"
        out[held] = dict(train=tr.index.to_numpy(), test=te.index.to_numpy())
    return out
