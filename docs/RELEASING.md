# Versions and releases

## The two kinds of release

| What changed | What users need | How |
|---|---|---|
| App code only (pages, report, measurements, bug fixes) | Nothing: the start page offers **Update now** | Tag a release (below) |
| Python packages, PyTorch, or the model | A new installation download (zip) | Raise `BASE` in `src/kidneycyst/updater.py`, tag a release, build the zips, upload them |

When `BASE` is higher than the user's installation, the app says that a new download is needed instead of updating.

## Version numbers

`X.Y.Z`, written only in `src/kidneycyst/__init__.py` (`__version__`):
- `Z` (0.2.0 -> 0.2.1): fixes only.
- `Y` (0.2.1 -> 0.3.0): new features, or anything that changes a measured number. Say so in the changelog.
- `X`: reserved for 1.0 (published, validated version).

Every results folder records the version that made it (`run_settings.json`, report header), so numbers stay traceable.

## Making a release

1. Change `__version__` in `src/kidneycyst/__init__.py`.
2. Add a `## X.Y.Z` section at the top of `CHANGELOG.md`, in plain words for users (it is shown as "What's new").
3. Commit and push, wait for the **checks** workflow to pass on GitHub (Actions tab).
4. Tag and push the tag:
   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```
   The **release** workflow checks that the tag, the version and the changelog agree, builds the wheel, and publishes the
   release with `kidneycyst-X.Y.Z-py3-none-any.whl` and `version.json`. Installed apps see it within a day (or at the next
   start after that).

A bad release: publish a fixed `X.Y.Z+1` quickly. An update that does not import is rolled back on the user's computer
automatically, but a version that imports and misbehaves is not.

## Zips (new download only)

```bash
TMPDIR=/group/jug/aman/ZebrafishKidneyCyst_Runs/tmp /group/jug/aman/ZebrafishKidneyCyst_Runs/envs/nnunet/bin/python -I installer/build_dist.py <new empty folder> --zip
```
Then replace the files on Google Drive with **Manage versions -> Upload new version** so the shared link stays the same.
The zips can also be attached to the GitHub release (`gh release upload vX.Y.Z <zip>`; limit 2 GB per file).

## Testing an update without publishing

Serve a folder holding `version.json` and a wheel (`python -m http.server`) and start an installed app with
`KIDNEYCYST_UPDATE_URL=http://127.0.0.1:<port>/version.json`; `version.json` may give `wheel_url` directly.
