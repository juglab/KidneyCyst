"""In-tool review of predicted outlines (no QuPath needed). The window (gui.py) calls this; it can also be scripted.

Per image the reviewer decides:
  accepted  the model outline is right                      (outline unchanged)
  edited    the outline was fixed with the brush / eraser   (new mask stored)
  deleted   there is no kidney in this image                (empty mask stored; area 0)
  unusable  cannot assess: poor or empty image                (no area; left out of results and retraining)
  auto      undo: back to the model outline, not reviewed

Storage, inside the results folder:
  review/masks/<id>.png, review/geojson/<id>.geojson   current outline of edited/deleted images
  review/review_log.csv                                 one row per decision: who, when, what, area before/after
  results.csv / .xlsx                                   status, edited_by_human, iou_vs_auto, reviewed_area_um2, reviewer, reviewed_at
  retrain_pool/                                         same format as `kidneycyst sync` (packbits masks + GeoJSON + manifest)

Areas of edited outlines use the same estimator as the model's (mask pixels * px² / RASTER_BIAS), so a reviewed area and a
model area are directly comparable and both follow the Excel / QuPath-polygon convention.
"""
from __future__ import annotations

import csv
import datetime as _dt
import os
from pathlib import Path

import numpy as np

from . import data as D
from . import metrics as M
from . import qupath_io as Q

STATUSES = ("auto", "accepted", "edited", "deleted", "unusable")   # unusable = cannot assess (poor image)
# Human measurements on the IMAGE (not on the model's outline): the validation data for the beta columns. They are kept
# when detection is run again (carry_human), and QuPath sync leaves them alone.
HUMAN_COLS = [("elbow_points_px", ""), ("elbow_measured_straight_um", np.nan), ("elbow_measured_path_um", np.nan),
              ("elbow_measured_by", ""), ("elbow_measured_at", ""), ("grade_human", ""), ("grade_human_by", ""),
              ("grade_human_at", "")]
GRADES = ("normal", "unfused", "cyst")


def carry_human(old_csv: Path, df):
    """Copy the human measurement columns of an earlier results.csv onto a new results table (same image ids)."""
    import pandas as pd
    if not Path(old_csv).exists():
        return df
    try:
        old = pd.read_csv(old_csv, usecols=lambda c: c == "image_id" or c in dict(HUMAN_COLS), dtype=str)
    except Exception:
        return df
    have = [c for c, _ in HUMAN_COLS if c in old]
    if not have or "image_id" not in old:
        return df
    old = old.set_index("image_id")[have]
    old = old[old.notna().any(axis=1)]
    if not len(old):
        return df
    d = df.set_index("image_id", drop=False)
    for c, default in HUMAN_COLS:
        if c not in d:
            d[c] = default
    common = d.index.intersection(old.index)
    for c in have:
        vals = old.loc[common, c]
        num = isinstance(dict(HUMAN_COLS)[c], float)
        d.loc[common, c] = pd.to_numeric(vals, errors="coerce") if num else vals.fillna("")
    return d.reset_index(drop=True)


REVIEW_COLS = [("status", "auto"), ("edited_by_human", False), ("iou_vs_auto", np.nan), ("reviewed_area_um2", np.nan),
               ("reviewer", ""), ("reviewed_at", ""), ("review_source", "")]


def _png_read(p: Path) -> np.ndarray:
    from PIL import Image
    return np.array(Image.open(p)) > 0


def _png_write(p: Path, m: np.ndarray):
    from PIL import Image
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((np.asarray(m, bool) * 255).astype(np.uint8)).save(p, optimize=True)


def area_um2(n_px: int, px_um: float) -> float:
    return float(M.px_to_um2(n_px) * (px_um / D.UM_PER_PX) ** 2) if n_px else 0.0


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 1.0


def current_geometry_path(out: Path, iid: str) -> Path:
    """The outline as it is now: the reviewed one if there is one, else the model's."""
    p = Path(out) / "review" / "geojson" / f"{iid}.geojson"
    return p if p.exists() else Path(out) / "geojson" / f"{iid}.geojson"


class ReviewSession:
    def __init__(self, out: Path, reviewer: str | None = None):
        import pandas as pd
        self.out = Path(out)
        self.df, self.settings = Q._load_results(self.out)
        self.df = self.df.set_index("image_id", drop=False)
        for c, default in REVIEW_COLS:
            if c not in self.df:
                self.df[c] = default
        for c in ("status", "reviewer", "reviewed_at", "review_source"):
            self.df[c] = self.df[c].fillna("auto" if c == "status" else "").astype(str)
        self.df["edited_by_human"] = self.df["edited_by_human"].fillna(False).astype(bool)
        for c, default in HUMAN_COLS:
            if c not in self.df:
                self.df[c] = default
            if not isinstance(default, float):
                self.df[c] = self.df[c].fillna("").astype(str)
        self.reviewer = reviewer if reviewer is not None else (os.environ.get("USERNAME") or os.environ.get("USER") or "")
        self.in_root = Path(self.settings["input_folder"])
        self._dirty_xlsx = 0
        self._pd = pd

    # ---------------------------------------------------------------- order / counts
    def order(self, which: str = "all") -> list[str]:
        """Images to show. Flagged outlines first, then flagged fields with no outline, then the rest.
        which: all | todo (not reviewed) | flagged"""
        d = self.df
        prio = np.where(d.flagged & (d.area_px > 0), 0, np.where(d.flagged, 1, 2))
        d = d.assign(_p=prio).reset_index(drop=True).sort_values(["_p", "run", "plate", "well", "field", "image_id"])
        if which == "todo":
            d = d[d.status == "auto"]
        elif which == "flagged":
            d = d[d.flagged]
        return d.image_id.tolist()

    def counts(self) -> dict:
        c = self.df.status.value_counts().to_dict()
        return {s: int(c.get(s, 0)) for s in STATUSES}

    # ---------------------------------------------------------------- images
    def row(self, iid: str):
        return self.df.loc[iid]

    def load(self, iid: str):
        """-> (raw GFP uint16 HxW, model mask, current mask)."""
        from .cli import read_gfp
        r = self.df.loc[iid]
        raw = read_gfp(self.in_root / r["image"], int(self.settings.get("channel", 0)))
        auto = _png_read(self.out / "masks" / f"{iid}.png")
        cur_p = self.out / "review" / "masks" / f"{iid}.png"
        cur = _png_read(cur_p) if cur_p.exists() else auto.copy()
        return raw, auto, cur

    # ---------------------------------------------------------------- decisions
    def decide(self, iid: str, action: str, mask: np.ndarray | None = None, note: str = "") -> str:
        """Record a decision; returns the status actually stored (an 'edit' that changes nothing is 'accepted')."""
        if action not in STATUSES:
            raise ValueError(action)
        r = self.df.loc[iid]
        was_unreviewed = str(r["status"]) == "auto"
        auto = _png_read(self.out / "masks" / f"{iid}.png")
        px = float(r["px_um"])
        before = float(r["reviewed_area_um2"]) if r["status"] != "auto" and np.isfinite(r["reviewed_area_um2"]) \
            else float(r["area_um2"])
        if action == "edited":
            if mask is None:
                raise ValueError("an edit needs the new mask")
            mask = np.asarray(mask, bool)
            if not mask.any():
                action = "deleted"
            elif np.array_equal(mask, auto):
                action = "accepted"
        if action == "deleted":
            mask = np.zeros_like(auto)
        rv_m = self.out / "review" / "masks" / f"{iid}.png"
        rv_g = self.out / "review" / "geojson" / f"{iid}.geojson"
        now = _dt.datetime.now().isoformat(timespec="seconds")
        if action in ("edited", "deleted"):
            _png_write(rv_m, mask)
            geom = Q.mask_to_geometry(mask, target_area_px=mask.sum() / M.RASTER_BIAS) if mask.any() else None
            Q.write_geojson(rv_g, [Q.make_feature(geom, iid, Q.EDITED_CLASS, {Q.AREA_MEASUREMENT: area_um2(int(mask.sum()), px)},
                                                  {"source": "human", "reviewer": self.reviewer, "status": action})]
                            if geom is not None else [], extra={"status": action, "reviewer": self.reviewer, "at": now})
            cur = mask
        else:                                   # accepted / auto / unusable: the model outline is kept on file
            rv_m.unlink(missing_ok=True)
            rv_g.unlink(missing_ok=True)
            cur = auto
            geom = Q.read_geojson_geometry(self.out / "geojson" / f"{iid}.geojson")
        n = int(cur.sum())
        self.df.at[iid, "status"] = action
        self.df.at[iid, "edited_by_human"] = action in ("edited", "deleted")
        self.df.at[iid, "iou_vs_auto"] = mask_iou(cur, auto) if action != "auto" else np.nan
        self.df.at[iid, "reviewed_area_um2"] = area_um2(n, px) if action not in ("auto", "unusable") else np.nan
        self.df.at[iid, "reviewer"] = self.reviewer if action != "auto" else ""
        self.df.at[iid, "reviewed_at"] = now if action != "auto" else ""
        self.df.at[iid, "review_source"] = "kidneycyst" if action != "auto" else ""
        self._log(dict(time=now, reviewer=self.reviewer, image_id=iid, action=action,
                       area_before_um2=round(before, 2), area_after_um2=round(area_um2(n, px), 2),
                       model_area_um2=round(float(r["area_um2"]), 2), iou_vs_auto=round(mask_iou(cur, auto), 4), note=note))
        try:                                     # the report thumbnail shows the CURRENT outline
            from .cli import _display, read_gfp
            from .report import save_thumbs
            raw = read_gfp(self.in_root / r["image"], int(self.settings.get("channel", 0)))
            save_thumbs(self.out, iid, _display(raw), auto, cur)
        except Exception as e:
            print(f"note: thumbnail not updated ({e})")
        pool = [(iid, geom, action, [])] if action in ("edited", "deleted", "accepted") else []
        Q._write_pool(self.out, self.df, pool, self.settings, now)
        self.save(xlsx=False)
        if was_unreviewed and action != "auto" and self.counts()["auto"] == 0:
            try:                              # the last image was just reviewed: keep a frozen "final" report
                from .library import snapshot
                snapshot(self.out, "final")
            except Exception as e:
                print(f"note: final snapshot not saved ({e})")
        return action

    # ---------------------------------------------------------------- human measurements (beta validation)
    def measure_elbow(self, iid: str, points: list) -> dict:
        """points: [[x, y], ...] in image pixels along the tubule, elbow to elbow. [] clears the measurement."""
        r = self.df.loc[iid]
        px = float(r["px_um"])
        now = _dt.datetime.now().isoformat(timespec="seconds")
        pts = [(float(x), float(y)) for x, y in points]
        if len(pts) >= 2:
            seg = sum(float(np.hypot(b[0] - a[0], b[1] - a[1])) for a, b in zip(pts, pts[1:]))
            straight = float(np.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]))
            vals = dict(elbow_points_px=";".join(f"{x:.1f},{y:.1f}" for x, y in pts),
                        elbow_measured_straight_um=straight * px, elbow_measured_path_um=seg * px,
                        elbow_measured_by=self.reviewer, elbow_measured_at=now)
        else:
            vals = dict(elbow_points_px="", elbow_measured_straight_um=np.nan, elbow_measured_path_um=np.nan,
                        elbow_measured_by="", elbow_measured_at="")
        for k, v in vals.items():
            self.df.at[iid, k] = v
        self._log(dict(time=now, reviewer=self.reviewer, image_id=iid, what="elbow",
                       value=vals["elbow_points_px"], straight_um=vals["elbow_measured_straight_um"],
                       path_um=vals["elbow_measured_path_um"]), "measurements_log.csv")
        self.save()
        return {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in vals.items()}

    def set_grade(self, iid: str, g: str) -> dict:
        g = (g or "").strip().lower()
        if g and g not in GRADES:
            raise ValueError(f"grade must be one of {', '.join(GRADES)} or empty")
        now = _dt.datetime.now().isoformat(timespec="seconds")
        vals = dict(grade_human=g, grade_human_by=self.reviewer if g else "", grade_human_at=now if g else "")
        for k, v in vals.items():
            self.df.at[iid, k] = v
        self._log(dict(time=now, reviewer=self.reviewer, image_id=iid, what="grade", value=g, straight_um="",
                       path_um=""), "measurements_log.csv")
        self.save()
        return vals

    def _log(self, row: dict, name: str = "review_log.csv"):
        p = self.out / "review" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        new = not p.exists()
        with open(p, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(row))
            if new:
                w.writeheader()
            w.writerow(row)

    def save(self, xlsx: bool = True):
        """results.csv always; Excel + report too (they are cheap: ~0.3 s for 160 images)."""
        from .report import build_report, write_tables
        ok = write_tables(self.out, self.df)
        try:
            build_report(self.out)
        except Exception as e:
            ok = False
            print(f"Could not update report.html: {e}")
        self.last_export_ok = ok
        return ok
