"""The ONE evaluation harness. Every baseline/model goes through `evaluate_predictions`.

Reports (per held-out run, per hard plate, and pooled-over-folds):
  Dice / IoU                       vs the QuPath outline
  area agreement                   vs the Excel area (== QuPath polygon area), in % of truth:
                                   Bland-Altman bias + 95% limits, ICC(2,1) with bootstrap CI,
                                   % within 10 / 20 %, outlier rate (>20 %), Spearman
  improvement over constant-area   same metrics for the 'predict the training-fold median' baseline
  false positives                  predicted pixels on images that have NO kidney in frame (empty / tail-only)

Area of a prediction = pixel count * um_per_px^2 / RASTER_BIAS (masks are ~2% larger than the polygon
because rasterisation adds boundary pixels; truth is the polygon/Excel area, so correct for it).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import data as D  # noqa

RASTER_BIAS = 1.020        # median mask_px / polygon_px measured in notebook 01
UM2 = D.UM_PER_PX ** 2


def px_to_um2(n_px):
    return np.asarray(n_px, float) * UM2 / RASTER_BIAS


def dice_iou(pred: np.ndarray, gt: np.ndarray):
    p, g = pred.astype(bool), gt.astype(bool)
    inter = (p & g).sum()
    s = p.sum() + g.sum()
    dice = 1.0 if s == 0 else 2 * inter / s
    union = (p | g).sum()
    return float(dice), float(1.0 if union == 0 else inter / union)


def icc_2_1(x: np.ndarray, y: np.ndarray) -> float:
    """ICC(2,1): two-way random, absolute agreement, single measurement (x = method, y = truth)."""
    d = np.column_stack([x, y]).astype(float)
    n, k = d.shape
    gm = d.mean()
    msr = k * ((d.mean(1) - gm) ** 2).sum() / (n - 1)
    msc = n * ((d.mean(0) - gm) ** 2).sum() / (k - 1)
    sse = ((d - d.mean(1, keepdims=True) - d.mean(0, keepdims=True) + gm) ** 2).sum()
    mse = sse / ((n - 1) * (k - 1))
    return float((msr - mse) / (msr + (k - 1) * mse + k * (msc - mse) / n))


def agreement(pred_um2, true_um2, n_boot: int = 500, seed: int = 0) -> dict:
    """Area agreement of predictions against truth. Errors are % of truth."""
    p, t = np.asarray(pred_um2, float), np.asarray(true_um2, float)
    ok = np.isfinite(p) & np.isfinite(t) & (t > 0)
    p, t = p[ok], t[ok]
    if len(t) < 5:
        return dict(n=int(len(t)))
    err = 100 * (p - t) / t
    rng = np.random.default_rng(seed)
    bs = [icc_2_1(p[i], t[i]) for i in (rng.integers(0, len(t), len(t)) for _ in range(n_boot))]
    sp = pd.Series(p).corr(pd.Series(t), method="spearman")
    return dict(n=int(len(t)), bias_pct=float(err.mean()), loa_lo=float(err.mean() - 1.96 * err.std(ddof=1)),
                loa_hi=float(err.mean() + 1.96 * err.std(ddof=1)), mae_pct=float(np.abs(err).mean()),
                within10=float((np.abs(err) < 10).mean()), within20=float((np.abs(err) < 20).mean()),
                outlier_gt20=float((np.abs(err) >= 20).mean()), icc=icc_2_1(p, t),
                icc_lo=float(np.percentile(bs, 2.5)), icc_hi=float(np.percentile(bs, 97.5)), spearman=float(sp))


def constant_area_predictions(index: pd.DataFrame) -> pd.Series:
    """Leave-one-run-out 'predict the training-fold median area' for every usable image."""
    u = index[index.usable]
    out = pd.Series(np.nan, index=u.index)
    for run in sorted(u.run.unique()):
        out[u.run == run] = u[u.run != run].area_um2.median()
    return out


def evaluate_predictions(index: pd.DataFrame, pred_area_um2: pd.Series, dice: pd.Series | None = None,
                         iou: pd.Series | None = None, label: str = "model") -> pd.DataFrame:
    """index: build_index() frame; pred_area_um2/dice/iou indexed like index (usable rows)."""
    u = index[index.usable].copy()
    u["pred"] = pred_area_um2.reindex(u.index)
    if dice is not None:
        u["dice"] = dice.reindex(u.index)
    if iou is not None:
        u["iou"] = iou.reindex(u.index)
    rows = []
    groups = [("ALL (pooled over folds)", u)] + [(f"held-out {r}", g) for r, g in u.groupby("run")]
    groups += [("hard plates (Run3 P3 + Run4 P4)", u[u.hard_plate]), ("non-hard plates", u[~u.hard_plate])]
    groups += [(f"cyst only", u[u.grade3 == "cyst"]), (f"normal only", u[u.grade3 == "normal"])]
    for name, g in groups:
        r = dict(model=label, subset=name, **agreement(g.pred, g.area_um2))
        if "dice" in g:
            r["dice"] = float(g.dice.mean())
        if "iou" in g:
            r["iou"] = float(g.iou.mean())
        rows.append(r)
    return pd.DataFrame(rows)
