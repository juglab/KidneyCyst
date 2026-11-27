"""Fast checks that need no model, no GPU and no data (run by GitHub Actions on every push, and before a release).

Usage: python scripts/ci_checks.py [path/to/kidneycyst-X.Y.Z-py3-none-any.whl]
With a wheel: also checks that it carries the right version and every file the app needs.
Exit code 1 on any failure.
"""
import importlib
import json
import re
import sys
import zipfile
from pathlib import Path

import numpy as np

FAIL = []


def check(ok, what):
    print(("PASS " if ok else "FAIL ") + what)
    if not ok:
        FAIL.append(what)


import kidneycyst
V = kidneycyst.__version__
check(re.fullmatch(r"\d+\.\d+\.\d+", V) is not None, f"version {V} is X.Y.Z")

# 1. every module imports (PyTorch / nnU-Net are imported lazily, only when detection runs)
for m in ["cli", "webapp", "review", "report", "library", "morphometry", "remote_gpu", "qupath_io", "updater", "gui"]:
    try:
        importlib.import_module(f"kidneycyst.{m}")
        check(True, f"import kidneycyst.{m}")
    except Exception as e:
        check(False, f"import kidneycyst.{m}: {type(e).__name__}: {e}")

from kidneycyst import cli, updater
from kidneycyst import morphometry as MO
check(cli.TOOL_VERSION == V, "cli reports the package version")

# 2. measurements on a synthetic 200 x 20 px bar (same as scripts/test_beta_measures.py part 1)
mask = np.zeros((300, 300), bool)
mask[50:250, 140:160] = True
g = np.random.default_rng(0).random((300, 300)).astype(np.float32) * 0.05
g[mask] += 0.6
b = cli.beta_measures(g, mask, 1.0, float(mask.sum()))
check(195 < b["elbow_straight_um_beta"] < 205, f"elbow straight of a 200 px bar = {b['elbow_straight_um_beta']:.1f}")
check(0 < b["elbow_midline_um_beta"] < b["elbow_straight_um_beta"], "midline shorter than tip-to-tip")
check(MO.GRADE_MODEL_PATH.exists(), "grade model file is in the package")
check(b["grade_beta"] in ("normal", "unfused", "cyst"), f"grade model gives a grade ({b['grade_beta']})")

# 3. updater logic (no network)
check(updater._vt("0.10.0") > updater._vt("0.9.3") and updater._vt("v1.2") == (1, 2, 0), "version comparison")
check(isinstance(updater.BASE, int) and updater.BASE >= 1, f"installation generation BASE = {updater.BASE}")

# 4. web pages and their static files
static = Path(kidneycyst.__file__).parent / "static"
for page in ["index.html", "run.html", "review.html", "help.html", "style.css"]:
    check((static / page).exists(), f"static/{page}")
for html in static.glob("*.html"):
    for icon in set(re.findall(r"/static/icons/([\w-]+\.svg)", html.read_text(encoding="utf-8"))):
        check((static / "icons" / icon).exists(), f"{html.name}: icon {icon}")

# 5. the built wheel (release only)
if len(sys.argv) > 1:
    w = Path(sys.argv[1])
    check(w.name == f"kidneycyst-{V}-py3-none-any.whl", f"wheel name {w.name} matches version {V}")
    names = set(zipfile.ZipFile(w).namelist())
    for need in ["kidneycyst/grade_model_v1.json", "kidneycyst/report_template.html", "kidneycyst/static/review.html",
                 "kidneycyst/static/icons/contrast.svg", "kidneycyst/updater.py"]:
        check(need in names, f"wheel contains {need}")
    check(not any(n.startswith("kidneycyst/") and n.endswith("review_gui.py") for n in names), "wheel has no stale files")

print(f"\n{len(FAIL)} failure(s)" if FAIL else "\nall checks passed")
sys.exit(1 if FAIL else 0)
