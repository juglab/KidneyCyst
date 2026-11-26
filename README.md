# KidneyCyst

Pronephros (kidney) segmentation and area measurement in GFP images of zebrafish larvae.
A local app: choose a folder of TIFF images, run detection (nnU-Net), review the outlines, and export a report and an Excel table.

- **Install:** use the KidneyCyst zip for your computer (Mac, Windows or Linux) and double-click `Install KidneyCyst` inside it. The zips include the trained model; ask the maintainer for the download link.
- **User guide:** [docs/USER_GUIDE.md](docs/USER_GUIDE.md) (also in the app under Help).
- **Model card:** [docs/release/MODEL_CARD.md](docs/release/MODEL_CARD.md).
- **Optional:** run detection on another computer or a Slurm cluster over SSH; the app can install itself there.

## For developers

```bash
pip install -e ".[predict]"
kidneycyst --help          # command line
python -m kidneycyst.webapp  # the app
```

- Installer zips: `python installer/build_dist.py <dest> --zip` (needs the trained model folder).
- Checks: `scripts/test_beta_measures.py <results folder>`, `scripts/ui_flow_test.py <work dir>` (Playwright).

Data and annotations: Institut Imagine. Contact: aman.kukde@fht.org.
