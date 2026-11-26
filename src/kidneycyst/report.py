"""Report page, thumbnails and the Excel table. Rebuilt after the run AND after every review decision, so they always
show the current outlines, decisions and final areas.

  thumbs/<id>_in.jpg    input crop (display-scaled GFP)            made once, during the run
  thumbs/<id>.jpg       same crop with the CURRENT outline           remade whenever the outline changes
  report.html           one self-contained page (thumbnails embedded)
  results.xlsx          sheet "Results" (what a biologist needs) + sheet "Details" (everything, = results.csv)
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np

THUMB_PX = 160
CROP_PX = 320
CANDIDATE = (255, 133, 0)     # kit: detection orange = model candidate
MINE = (140, 202, 255)        # kit dark-surface blue = an outline a person changed


def final_area(r) -> float:
    """Area used for results: the checked outline if there is one, else the model's; NaN if 'cannot assess'."""
    st = str(r.get("status", "auto"))
    if st == "unusable":
        return float("nan")
    rv = r.get("reviewed_area_um2")
    if st != "auto" and rv is not None and np.isfinite(float(rv)):
        return float(rv)
    return float(r["area_um2"])


DECISION_TEXT = {"auto": "unreviewed", "accepted": "outline accepted", "edited": "outline corrected",
                 "deleted": "no kidney visible", "unusable": "cannot assess"}   # display only; results.csv keeps the codes
# plain-language flag names (also translates results written by older versions)
FLAG_PLAIN = {"no GFP signal": "no GFP signal", "no kidney found": "no outline found", "no outline found": "no outline found",
              "touches border": "outline reaches image boundary", "touches the image edge": "outline reaches image boundary",
              ">1 piece": "multiple disconnected regions", "several separate regions": "multiple disconnected regions",
              "area unusual": "atypical area for this plate", "area unusual for this plate": "atypical area for this plate",
              "low confidence": "model uncertainty", "model unsure": "model uncertainty"}


def plain_flags(flags) -> str:
    if not isinstance(flags, str) or not flags:
        return ""
    return "; ".join(FLAG_PLAIN.get(f.strip(), f.strip()) for f in flags.split(";"))


# ---------------------------------------------------------------- thumbnails
def _crop(mask: np.ndarray, box_mask: np.ndarray):
    from .cli import crop_box
    return crop_box(box_mask if box_mask.any() else mask, CROP_PX)


def save_thumbs(out: Path, iid: str, gray: np.ndarray, auto: np.ndarray, cur: np.ndarray | None = None):
    """gray: display-scaled uint8 image; auto: model mask; cur: current mask (default = auto)."""
    from PIL import Image
    from .cli import _outline
    cur = auto if cur is None else cur
    ys, xs = _crop(auto, auto | cur)
    d = Path(out) / "thumbs"
    d.mkdir(exist_ok=True)
    g = gray[ys, xs]
    Image.fromarray(g).resize((THUMB_PX, THUMB_PX), Image.BILINEAR).save(d / f"{iid}_in.jpg", quality=84)
    rgb = np.repeat(g[..., None], 3, 2)
    rgb[_outline(cur[ys, xs], 2)] = CANDIDATE if np.array_equal(cur, auto) else MINE
    Image.fromarray(rgb).resize((THUMB_PX, THUMB_PX), Image.BILINEAR).save(d / f"{iid}.jpg", quality=84)


def _b64(p: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode() if p.exists() else ""


# ---------------------------------------------------------------- plate layout (which well got which treatment)
LAYOUT_FILE = "plate_layout.json"   # {"mode": "column"|"row"|"well", "labels": {"1": "DMSO", ...}, "order": [...]}


def load_layout(out: Path) -> dict | None:
    p = Path(out) / LAYOUT_FILE
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_layout(out: Path, layout: dict):
    import os
    p = Path(out) / LAYOUT_FILE
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(layout, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def condition_of(well: str, layout: dict | None) -> str:
    if not layout or not isinstance(well, str) or len(well) < 2:
        return ""
    lab = layout.get("labels") or {}
    mode = layout.get("mode", "column")
    if mode == "row":
        key = well[0].upper()
    elif mode == "well":
        key = well.upper()
    else:
        try:
            key = str(int(well[1:]))
        except ValueError:
            return ""
    return str(lab.get(key, "") or "").strip()


# ---------------------------------------------------------------- tables
RESULT_COLS = [("run", "Run"), ("plate", "Plate"), ("well", "Well"), ("field", "Field"), ("condition", "Condition"),
               ("final_area_um2", "Current area (µm²)"), ("area_source", "Area source"), ("decision", "Review decision"),
               ("area_um2", "Model area (µm²)"),
               ("flags", "Flags"), ("reviewer", "Reviewed by"), ("reviewed_at", "Reviewed at"),
               # BETA (not yet validated against Nikita) and the human measurements that will validate them
               ("grade_beta", "Grade (beta)"), ("grade_p_beta", "Grade probability (beta)"),
               ("elbow_straight_um_beta", "Elbow straight µm (beta)"), ("elbow_midline_um_beta", "Elbow midline µm (beta)"),
               ("grade_human", "Grade (yours)"), ("elbow_measured_straight_um", "Elbow measured straight µm"),
               ("elbow_measured_path_um", "Elbow measured path µm"), ("elbow_measured_by", "Elbow measured by"),
               ("image", "Image file")]
OPTIONAL_COLS = {"grade_beta", "grade_p_beta", "elbow_straight_um_beta", "elbow_midline_um_beta", "grade_human",
                 "elbow_measured_straight_um", "elbow_measured_path_um", "elbow_measured_by"}   # shown only when filled


def tidy(df, layout: dict | None = None):
    import pandas as pd
    d = df.copy()
    d["condition"] = [condition_of(w, layout) for w in d.get("well", pd.Series([""] * len(d)))]
    for c in ("status", "reviewer", "reviewed_at", "flags"):
        if c not in d:
            d[c] = "" if c != "status" else "auto"
        d[c] = d[c].fillna("auto" if c == "status" else "").astype(str)
    d["final_area_um2"] = [round(final_area(r), 1) for _, r in d.iterrows()]
    d["area_source"] = ["" if s_ == "unusable" else ("model" if s_ == "auto" else "reviewed") for s_ in d.status]
    d["flags"] = d["flags"].map(plain_flags)
    d["decision"] = d.status.map(DECISION_TEXT).fillna(d.status)
    d["area_um2"] = pd.to_numeric(d.area_um2).round(1)
    if {"p_normal", "p_unfused", "p_cyst"} <= set(d.columns):
        d["grade_p_beta"] = d[["p_normal", "p_unfused", "p_cyst"]].apply(pd.to_numeric, errors="coerce").max(axis=1).round(2)
    for c in ("elbow_straight_um_beta", "elbow_midline_um_beta", "elbow_measured_straight_um", "elbow_measured_path_um"):
        if c in d:
            d[c] = pd.to_numeric(d[c], errors="coerce").round(1)
    return d


def write_tables(out: Path, df):
    """results.csv (everything, machine-readable) + results.xlsx (Results sheet for people, Details sheet)."""
    import os
    out = Path(out)
    res = df.reset_index(drop=True) if df.index.name == "image_id" else df
    tmp = out / "results.csv.tmp"
    res.to_csv(tmp, index=False)
    os.replace(tmp, out / "results.csv")
    try:
        import pandas as pd
        t = tidy(res, load_layout(out))
        def shown(c):
            if c == "condition":
                return (t["condition"] != "").any()
            if c in OPTIONAL_COLS:
                return c in t and t[c].replace("", np.nan).notna().any()
            return True
        cols = [(c, n) for c, n in RESULT_COLS if shown(c)]
        people = t[[c for c, _ in cols]].rename(columns=dict(cols))
        with pd.ExcelWriter(out / "results.xlsx", engine="openpyxl") as xw:
            people.to_excel(xw, index=False, sheet_name="Results")
            res.to_excel(xw, index=False, sheet_name="Details")
            ws = xw.sheets["Results"]
            widths = {"Run": 7, "Plate": 6, "Well": 7, "Field": 6, "Condition": 18, "Current area (µm²)": 17, "Area source": 10,
                      "Review decision": 18, "Model area (µm²)": 17, "Flags": 34, "Reviewed by": 14, "Reviewed at": 20,
                      "Image file": 50}
            from openpyxl.utils import get_column_letter
            for k, (_, name) in enumerate(cols):
                col = get_column_letter(k + 1)
                w = widths.get(name, 14)
                ws.column_dimensions[col].width = w
            ws.freeze_panes = "A2"
            st = _settings_rows(out)
            if st:
                pd.DataFrame(st, columns=["Setting", "Value"]).to_excel(xw, index=False, sheet_name="Settings")
                xw.sheets["Settings"].column_dimensions["A"].width = 30
                xw.sheets["Settings"].column_dimensions["B"].width = 90
    except Exception as e:  # e.g. the file is open in Excel on Windows (locked): the CSV is still current
        print(f"Could not update results.xlsx: {type(e).__name__}: {e}. Close the file in Excel. Writing will be retried at the next save.")
        return False
    return True


def _settings_rows(out: Path) -> list[tuple]:
    """How the numbers were made: versions, model, pixel size and its source, settings. For methods sections."""
    p = Path(out) / "run_settings.json"
    if not p.exists():
        return []
    s = json.loads(p.read_text(encoding="utf-8"))
    sizes = s.get("pixel_sizes_used") or {}
    px_txt = "; ".join(f"{float(k):.5g} µm ({n} image{'s' if n != 1 else ''})" for k, n in sizes.items()) or "?"
    src_names = {"tiff:resolution": "TIFF metadata", "tiff:ome": "TIFF metadata (OME)", "--pixel-size": "manual entry"}
    srcs = s.get("pixel_size_sources") or {}
    src_txt = "; ".join(f"{src_names.get(k, 'unverified default' if str(k).startswith('default') else k)}"
                        f" ({n} image{'s' if n != 1 else ''})" for k, n in srcs.items()) or "?"
    qc = s.get("qc_thresholds") or {}
    qc_txt = (f"no GFP signal: 99.9th percentile − median < {qc.get('no_gfp_signal_p999_minus_median')} and "
              f"< {100 * qc.get('no_gfp_signal_sigfrac', 0):.1f}% bright pixels; atypical area: more than "
              f"{qc.get('area_outlier_mad')} robust SDs from the plate median (plates with ≥ {qc.get('area_outlier_min_n')} "
              f"images); model uncertainty: mean probability inside the outline < {qc.get('low_confidence_mean_prob')} or "
              f"> {100 * qc.get('low_confidence_uncertain_frac', 0):.0f}% uncertain pixels") if qc else ""
    ver = s.get("versions") or {}
    ver_txt = ", ".join(f"{k} {v}" for k, v in ver.items())
    folds = s.get("folds", [])
    rows = [("KidneyCyst version", s.get("tool_version")), ("Model", s.get("model_version")),
            ("Training data", s.get("training_data", "")),
            ("Beta measures", (s.get("beta_measures") or {}).get("note", "")),
            ("Grade model (beta)", (s.get("beta_measures") or {}).get("grade_model", "")),
            ("Elbow definitions (beta)", (s.get("beta_measures") or {}).get("elbow", "")),
            ("Ensemble size", f"{len(folds)} model{'s' if len(folds) != 1 else ''} (folds {', '.join(map(str, folds))})" if folds else ""),
            ("Run date", (s.get("date") or "").replace("T", " ")),
            ("Input folder", s.get("input_folder")), ("Images", s.get("n_images")),
            ("Run cancelled", "yes" if s.get("cancelled") else "no"),
            ("Pixel size", px_txt), ("Calibration source", src_txt),
            ("GFP channel", f"channel {s.get('channel')} (first channel = 0)"),
            ("Intensity scaling", (s.get("normalisation") or {}).get("rule")),
            ("Inference", f"sliding window (step {s.get('tile_step_size')}); prediction averaging across mirrored inputs "
                          f"{'enabled' if s.get('mirroring') else 'disabled'}"),
            ("Mask postprocessing", "none"),
            ("Area calculation", "mask pixel count × pixel area ÷ 1.02"),
            ("Flag criteria", qc_txt),
            ("Processing device", {"cuda": "NVIDIA GPU", "mps": "Apple GPU", "cpu": "CPU"}
             .get(s.get("device"), s.get("device")) + f" ({s.get('host')})"),
            ("Software versions", ver_txt),
            ("Area source", "model: unreviewed prediction; reviewed: outline accepted or corrected in KidneyCyst or QuPath. "
                            "Images marked Cannot assess have no reported area.")]
    return [(k, "" if v is None else str(v)) for k, v in rows if v not in (None, "")]


# ---------------------------------------------------------------- report page
def _beta_row(r) -> dict:
    """Beta grade / elbow per image for the report table (empty when the run predates them)."""
    def num(k):
        v = r.get(k, np.nan)
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return None if v != v else round(v, 2)
    g = r.get("grade_beta", "")
    g = g if isinstance(g, str) else ""
    gh = r.get("grade_human", "")
    return dict(grade=g, gp=num("grade_p_beta"), gsure=str(r.get("grade_confident", "")).lower() == "true",
                elb=num("elbow_straight_um_beta"), elbm=num("elbow_midline_um_beta"),
                gh=gh if isinstance(gh, str) else "", em=num("elbow_measured_path_um"), es=num("elbow_measured_straight_um"))


def build_report(out: Path, snapshot: dict | None = None, target: Path | None = None):
    import pandas as pd
    out = Path(out)
    df = pd.read_csv(out / "results.csv", dtype={"well": str})
    settings = json.loads((out / "run_settings.json").read_text(encoding="utf-8"))
    layout = load_layout(out)
    t = tidy(df, layout)
    rows = []
    for _, r in t.iterrows():
        iid = r["image_id"]
        rows.append(dict(id=iid, run=r["run"] if isinstance(r["run"], str) else "",
                         plate=None if pd.isna(r["plate"]) else int(r["plate"]),
                         well=r["well"] if isinstance(r["well"], str) else "",
                         field=None if pd.isna(r["field"]) else int(r["field"]),
                         area=None if pd.isna(r["final_area_um2"]) else float(r["final_area_um2"]),
                         src=r["area_source"], model=float(r["area_um2"]), status=r["status"],
                         flags=r["flags"], flagged=bool(r["flagged"]), cond=r["condition"],
                         a=_b64(out / "thumbs" / f"{iid}_in.jpg"), b=_b64(out / "thumbs" / f"{iid}.jpg"), **_beta_row(r)))
    meta = dict(folder=settings["input_folder"], date=settings["date"][:16].replace("T", " "),
                model=settings.get("model_version", settings.get("model_name", "")), device=settings.get("device", ""),
                n=len(rows), tool=settings.get("tool_version", ""), settings=_settings_rows(out), layout=layout,
                snapshot=snapshot, model_name=settings.get("model_name", ""), model_note=settings.get("training_data", "") if settings.get("model_choice", "kc009") != "kc009" else "")
    tpl = Path(__file__).with_name("report_template.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/null", json.dumps(dict(meta=meta, rows=rows)))
    dest = Path(target) if target else out / "report.html"
    tmp = dest.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    import os
    os.replace(tmp, dest)
    return dest
