# Model card: KC009-p512-250ep-gfp (KidneyCyst 0.1.0)

**Status: draft.** Validation section to be extended with the independent (blinded reader) evaluation when it is done.

| | |
|---|---|
| Task | Segment the zebrafish pronephros (kidney) and measure its area. Cyst detection and other measurements: planned, not included. |
| Architecture | nnU-Net v2, 2-D configuration, training patch 512 × 512 px, 250 epochs (`nnUNetTrainer_250epochs`, plans `nnUNetPlans_p512`). Same recipe as KC007 (100 epochs), trained longer. |
| Models shipped | 3 (one per left-out run, folds 0–2); the app averages them by default (`--folds 0` = one model, "fast mode"). Checkpoints slimmed to inference weights. |
| Input | GFP channel (channel 0) of z-projected TIFFs, 1080 × 1080 px, 1.19595 µm/px (Opera Phenix), zebrafish larvae at 2 dpf. Intensity scaling (x − 163) / 13700, same for every image, no clipping. |
| Output | Binary mask (raw, no largest-component step) → outline (find_contours) → area = mask px × px² / 1.02 (rasterisation correction calibrated against QuPath polygon areas). |
| Training data | 686 images, Runs 2–4 (Institut Imagine, ONO-AE3-208 toxicity experiments), one outline per image drawn in QuPath 0.6.0 by Nikita Toločkovs. Excluded: fuzzy/excluded rows, no outline, two outlines with different grades, unknown grade. |
| Splits | Leave-one-run-out, grouped by well (a well never appears in two folds). |

## Validation (leave-one-run-out cross-validation, n = 686 held-out images)

Area agreement with the hand-drawn QuPath area; every image measured by a single model that never saw its run.
All 686 images received an outline.

| Images | n | within 10% | within 20% | MAE | ICC(2,1) | Dice |
|---|---|---|---|---|---|---|
| all | 686 | 93.1% | 99.3% | 4.6% | 0.91 | 0.940 |
| Run 2 | 212 | 94.3% | 99.1% | 4.3% | 0.92 | 0.939 |
| Run 3 | 202 | 89.1% | 98.5% | 5.3% | 0.89 | 0.938 |
| Run 4 | 272 | 95.2% | 100% | 4.3% | 0.92 | 0.942 |
| cysts only | 68 | 86.8% | 97.1% | 5.8% | 0.91 | 0.938 |

Versus KC007 (100 epochs): within 10% +1.6 points (95% CI +0.2 to +3.1, bootstrap by well).
The default three-model average has not been validated separately on held-out runs.

Baseline: predicting the training-fold median area for every image is within 20% for 81% of images.
Source: `experiments/KC009.yaml`, `data/eval_kc009_p512_250ep_pred_px_raw.csv`.

## Limitations
- Single annotator: the model reproduces one person's outlining style; annotator noise vs model error is being
  separated by the blinded reader study (in progress).
- Harder runs/plates (more fuzzy images) are less accurate (Run 3: 89% within 10%).
- Not evaluated on other stages, microscopes, magnifications or reporter lines.
- Kidneys cut by the image border are measured up to the border (flagged "touches the image edge").
