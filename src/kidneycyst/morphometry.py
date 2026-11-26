"""Measurements from one predicted (or hand-drawn) kidney outline: elbow-to-elbow length and grade features.

Elbow-to-elbow is NOT annotated anywhere in Nikita's data. Two candidate definitions, both in micrometres:
  elbow_straight_um : longest straight line across the outline (max Feret diameter), tip to tip.
  elbow_midline_um  : length along the outline's midline (longest skeleton path, polyline through every 8th pixel).
Both are BETA until checked against his own measurements (the elbow block in the reader study / app).

Grade features are the ones from scripts/grade_baseline.py (shape + GFP inside vs around), computed on the
largest connected region. Intensities use the global GFP scaling (data.norm_gfp), lengths use the image's px size.
The grade model itself (3 classes: normal / unfused / cyst) is a logistic regression stored as plain JSON
(grade_model_v1.json beside this file) so the tool needs no scikit-learn pickle.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from skimage.measure import label, regionprops
from skimage.morphology import skeletonize

GRADE_MODEL_PATH = Path(__file__).with_name("grade_model_v1.json")
FEATURES = ["area", "feret", "minor", "aspect", "solidity", "extent", "compact", "in_mean", "in_med", "in_p90",
            "in_cv", "ring_mean", "in_over_ring", "frac_dark", "frac_bright", "edge_sharp"]
_ST = ndi.generate_binary_structure(2, 1)


def largest_region(mask: np.ndarray) -> np.ndarray:
    lab = label(mask, connectivity=2)
    if lab.max() <= 1:
        return mask.astype(bool)
    return lab == (np.argmax(np.bincount(lab.ravel())[1:]) + 1)


def _skeleton_longest_path(m: np.ndarray) -> tuple[float, list]:
    """Longest geodesic path (pixels, diagonal steps = sqrt 2) through the skeleton: double sweep on the pixel graph."""
    sk = skeletonize(m)
    ys, xs = np.nonzero(sk)
    n = len(ys)
    if n < 2:
        return float(n), []
    idx = -np.ones(m.shape, int); idx[ys, xs] = np.arange(n)
    rows, cols, w = [], [], []
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        y2, x2 = ys + dy, xs + dx
        ok = (y2 >= 0) & (y2 < m.shape[0]) & (x2 >= 0) & (x2 < m.shape[1])
        j = np.full(n, -1); j[ok] = idx[y2[ok], x2[ok]]
        k = j >= 0
        rows += list(np.flatnonzero(k)); cols += list(j[k]); w += [np.hypot(dy, dx)] * int(k.sum())
    g = coo_matrix((w, (rows, cols)), shape=(n, n)).tocsr()
    d0 = dijkstra(g, directed=False, indices=0); d0[~np.isfinite(d0)] = -1
    a = int(np.argmax(d0))
    da, pred = dijkstra(g, directed=False, indices=a, return_predecessors=True); da[~np.isfinite(da)] = -1
    b = int(np.argmax(da))
    path, k = [], b
    while k >= 0 and k != a:
        path.append((int(ys[k]), int(xs[k]))); k = pred[k]
    path.append((int(ys[a]), int(xs[a])))
    return float(da[b]), path[::-1]


def elbow(mask: np.ndarray, px_um: float) -> dict:
    """Both elbow-to-elbow candidates (µm) + the endpoints of the straight one (row, col) for drawing."""
    m = largest_region(mask)
    if not m.any():
        return dict(elbow_straight_um=np.nan, elbow_midline_um=np.nan, elbow_p1=None, elbow_p2=None)
    p = regionprops(m.astype(np.uint8))[0]
    pts = np.argwhere(m ^ ndi.binary_erosion(m, _ST))           # boundary pixels
    if len(pts) > 600:
        pts = pts[np.linspace(0, len(pts) - 1, 600).astype(int)]
    d = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)
    i, j = np.unravel_index(np.argmax(d), d.shape)
    _, path = _skeleton_longest_path(m)
    # 8-connected pixel steps are a staircase (~6% too long): measure a polyline through every 8th skeleton pixel
    # (+ the last), same as the reader study's midline_smooth_um. The skeleton stops ~half a width short of each tip.
    mid_px = 0.0
    if len(path) >= 2:
        q = np.array(path[::8] + ([path[-1]] if (len(path) - 1) % 8 else []), float)
        mid_px = float(np.hypot(*np.diff(q, axis=0).T).sum())
    return dict(elbow_straight_um=float(p.feret_diameter_max * px_um),
                elbow_midline_um=float(mid_px * px_um) if mid_px > 0 else np.nan,
                elbow_p1=tuple(map(int, pts[i])), elbow_p2=tuple(map(int, pts[j])))


def grade_features(gfp_norm: np.ndarray, mask: np.ndarray, px_um: float, area_um2: float | None = None) -> dict | None:
    m = largest_region(mask)
    if m.sum() < 20:
        return None
    p = regionprops(m.astype(np.uint8))[0]
    g = gfp_norm
    ring = ndi.binary_dilation(m, _ST, 25) & ~ndi.binary_dilation(m, _ST, 6)
    band = ndi.binary_dilation(m, _ST, 4) & ~ndi.binary_erosion(m, _ST, 4)
    gi, gr = g[m], g[ring]
    gy, gx = np.gradient(ndi.gaussian_filter(g, 1.5)); gm = np.hypot(gx, gy)
    return dict(
        area=float(area_um2 if area_um2 is not None else m.sum() * px_um ** 2), feret=p.feret_diameter_max * px_um,
        minor=p.axis_minor_length * px_um, aspect=p.axis_minor_length / max(p.axis_major_length, 1),
        solidity=p.solidity, extent=p.extent, compact=p.perimeter ** 2 / max(p.area, 1),
        in_mean=gi.mean(), in_med=np.median(gi), in_p90=np.percentile(gi, 90), in_cv=gi.std() / max(gi.mean(), 1e-6),
        ring_mean=gr.mean(), in_over_ring=gi.mean() / max(gr.mean(), 1e-6), frac_dark=(gi < 0.03).mean(),
        frac_bright=(gi > 0.5).mean(), edge_sharp=gm[band].mean() / max(gi.mean(), 1e-6))


_MODEL = None


def grade(features: dict | None) -> dict:
    """3-class beta grade from grade_features(). Returns grade_beta, p_normal/p_unfused/p_cyst, grade_confident."""
    global _MODEL
    out = dict(grade_beta="", p_normal=np.nan, p_unfused=np.nan, p_cyst=np.nan, grade_confident=False)
    if features is None or not GRADE_MODEL_PATH.exists():
        return out
    if _MODEL is None:
        _MODEL = json.loads(GRADE_MODEL_PATH.read_text())
    M = _MODEL
    x = (np.array([features[k] for k in M["features"]], float) - np.array(M["mean"])) / np.array(M["scale"])
    z = np.array(M["coef"]) @ x + np.array(M["intercept"])
    pr = np.exp(z - z.max()); pr /= pr.sum()
    k = int(np.argmax(pr))
    out.update(grade_beta=M["classes"][k], grade_confident=bool(pr[k] >= M["confident_threshold"]),
               **{f"p_{c}": float(v) for c, v in zip(M["classes"], pr)})
    return out
