"""Checks for the BETA grade / elbow columns and the human elbow + grade measurements (no pytest needed).

Usage: python scripts/test_beta_measures.py <a results folder made by `kidneycyst run`>
The results folder is copied to a temporary folder first; the original is never changed.
Exit code 1 on any failure.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from kidneycyst import cli
from kidneycyst import morphometry as MO
from kidneycyst import report as RP
from kidneycyst.review import ReviewSession, carry_human

FAIL = []


def check(ok, what):
    print(("PASS " if ok else "FAIL ") + what)
    if not ok:
        FAIL.append(what)


# 1. beta measures on a synthetic tubule: a 200 x 20 px bar -> straight ~ 201 px, midline < straight
mask = np.zeros((300, 300), bool)
mask[50:250, 140:160] = True
g = np.random.default_rng(0).random((300, 300)).astype(np.float32) * 0.05
g[mask] += 0.6
b = cli.beta_measures(g, mask, 1.0, float(mask.sum()))
check(195 < b["elbow_straight_um_beta"] < 205, f"elbow straight of a 200 px bar = {b['elbow_straight_um_beta']:.1f} µm")
check(0 < b["elbow_midline_um_beta"] < b["elbow_straight_um_beta"], "midline is positive and shorter than tip-to-tip")
check(len(b["elbow_line_px"].split(",")) == 4, f"elbow line has 4 coordinates ({b['elbow_line_px']})")
check(cli.beta_measures(g, np.zeros_like(mask), 1.0, 0.0)["elbow_line_px"] == "", "no outline -> empty beta values")

# 2. the grade, with a stand-in model file (the real grade_model_v1.json may not exist yet)
real = MO.GRADE_MODEL_PATH
with tempfile.TemporaryDirectory() as td:
    fake = Path(td) / "grade_model_v1.json"
    feats = MO.grade_features(g, mask, 1.0, float(mask.sum()))
    fake.write_text(json.dumps(dict(features=MO.FEATURES, mean=[0] * len(MO.FEATURES), scale=[1] * len(MO.FEATURES),
                                    coef=[[0] * len(MO.FEATURES)] * 3, intercept=[0, 0, 3], classes=["normal", "unfused", "cyst"],
                                    confident_threshold=0.7)))
    MO.GRADE_MODEL_PATH, MO._MODEL = fake, None
    b2 = cli.beta_measures(g, mask, 1.0, float(mask.sum()))
    check(b2["grade_beta"] == "cyst" and b2["grade_confident"] and not b2["flag_grade_uncertain"],
          f"stand-in model: grade {b2['grade_beta']}, p_cyst {b2['p_cyst']:.2f}, confident")
    fake.write_text(fake.read_text().replace('"intercept": [0, 0, 3]', '"intercept": [0, 0, 0.5]'))
    MO._MODEL = None
    b3 = cli.beta_measures(g, mask, 1.0, float(mask.sum()))
    check(b3["flag_grade_uncertain"] and not b3["grade_confident"], f"low probability ({b3['p_cyst']:.2f}) -> flag_grade_uncertain")
    MO.GRADE_MODEL_PATH, MO._MODEL = real, None

# 3. human measurements on a copy of a real results folder
src = Path(sys.argv[1])
with tempfile.TemporaryDirectory() as td:
    out = Path(td) / src.name
    shutil.copytree(src, out)
    s = ReviewSession(out, reviewer="tester")
    iid = s.order("all")[0]
    px = float(s.df.loc[iid, "px_um"])
    v = s.measure_elbow(iid, [[0, 0], [30, 40], [30, 100]])          # 50 + 60 = 110 px path, straight 104.4 px
    check(abs(v["elbow_measured_path_um"] - 110 * px) < 1e-6, f"path = 110 px x {px:.4f} µm/px = {v['elbow_measured_path_um']:.2f} µm")
    check(abs(v["elbow_measured_straight_um"] - np.hypot(30, 100) * px) < 1e-6, "straight = first to last point")
    s.set_grade(iid, "unfused")
    try:
        s.set_grade(iid, "banana")
        check(False, "invalid grade refused")
    except ValueError:
        check(True, "invalid grade refused")
    d = pd.read_csv(out / "results.csv")
    r = d.set_index("image_id").loc[iid]
    check(r["grade_human"] == "unfused" and r["elbow_measured_by"] == "tester", "grade + measurer saved to results.csv")
    x = pd.read_excel(out / "results.xlsx", sheet_name="Results")
    check({"Grade (yours)", "Elbow measured path µm", "Elbow straight µm (beta)"} <= set(x.columns),
          "Excel Results sheet has the beta and human columns")
    check((out / "review" / "measurements_log.csv").exists(), "measurements are logged")
    # re-running detection must keep them: simulate a new results table for the same images
    new = d.drop(columns=[c for c in d.columns if c.startswith(("elbow_measured", "elbow_points", "grade_human"))])
    kept = carry_human(out / "results.csv", new).set_index("image_id").loc[iid]
    check(kept["grade_human"] == "unfused" and abs(kept["elbow_measured_path_um"] - 110 * px) < 1e-6,
          "human values carried onto a new run")
    # clearing
    s.measure_elbow(iid, [])
    check(pd.isna(pd.read_csv(out / "results.csv").set_index("image_id").loc[iid, "elbow_measured_path_um"]), "clear removes it")
    # the report builds with the new columns
    RP.build_report(out)
    check("Grade (yours)" in (out / "report.html").read_text(), "report has the human grade column")

print(f"\n{len(FAIL)} failure(s)" if FAIL else "\nall checks passed")
sys.exit(1 if FAIL else 0)
