# KidneyCyst release checklist (25 Nov 2026)

| Item | Status | Where |
|---|---|---|
| Code license | MIT proposed; needs collaborator + institute agreement | `LICENSE_PROPOSED_MIT.txt` |
| Dependency review | First pass done (106 packages in a real install, 25 Nov). **paquo 0.9.0 is GPL-3.0**: DONE 25 Nov, now installed only when a user turns on QuPath support (asks first, names the license); the default install has no GPL code. Also: connected-components-3d (LGPL-3.0, used unmodified via nnU-Net), tqdm and certifi (MPL-2.0, unmodified): normally fine to redistribute with notices. cuda-toolkit: NVIDIA license, installed by PyTorch from PyPI. QuPath itself (GPL-3.0) is only downloaded on request. Needs a check by someone qualified before release. | `THIRD_PARTY_NOTICES.txt` in the install folder; Help > Licenses |
| Model weights terms | Open | Help > Licenses ("to be agreed") |
| Example image terms | Open (Institut Imagine data) | Help > Licenses |
| Artwork credit | AI-assisted mascot + vector icons, credited separately | Help > Licenses |
| Funding wording | Draft MSCA sentence (101169364); check against the grant agreement | Help > Licenses, Help > About |
| Authorship / order | Open; citation draft lists "Kukde A, et al." | `CITATION.cff.draft`, Help > How to cite |
| Validation | LORO cross-validation documented; blinded reader study underway | `MODEL_CARD.md`, Help > Model & validation |
| Network behaviour | Verified in code: local server on 127.0.0.1 only; internet only in the installer and on-request QuPath download | Help > Data & network |
| Reproducibility | Versions, model, pixel size + source, settings in report ("How these numbers were made") and Excel "Settings" sheet | report.html, results.xlsx |
| Support | aman.kukde@fht.org; diagnostics copy button | Help > Report a problem |
| Windows test | Not done (no Windows machine) | |
| Code signing (Mac/Windows) | Not done: users see "unidentified developer" warnings | |
