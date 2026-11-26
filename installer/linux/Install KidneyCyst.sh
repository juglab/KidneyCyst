#!/usr/bin/env bash
# KidneyCyst installer for Linux: run once (bash "Install KidneyCyst.sh"). Afterwards: applications menu, or ./KidneyCyst
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; F="$HERE/files"
export UV_CACHE_DIR="$F/tools/uv-cache" UV_PYTHON_INSTALL_DIR="$F/tools/python"
UV="$F/tools/uv"; PY="$F/env/bin/python"; chmod +x "$UV"
step() { printf "\n\033[1;36m== Step %s of 4: %s\033[0m\n\n" "$1" "$2"; }
step 1 "Creating a local Python environment…"; "$UV" venv "$F/env" --python 3.12 --clear
step 2 "Downloading and installing PyTorch…"; "$UV" pip install --python "$PY" --compile-bytecode 'torch!=2.9.*' --torch-backend=auto
step 3 "Installing KidneyCyst and dependencies…"; "$UV" pip install --python "$PY" --compile-bytecode -r "$F/app/requirements.txt" "$F/app/kidneycyst-0.1.0-py3-none-any.whl"
step 4 "Running a sample-image test…"; KIDNEYCYST_HOME="$F" "$PY" -m kidneycyst.setup_local
printf '#!/usr/bin/env bash\nexec "%s" -m kidneycyst.gui "$@"\n' "$PY" > "$HERE/KidneyCyst"; chmod +x "$HERE/KidneyCyst"
mkdir -p "$HOME/.local/share/applications"
printf '[Desktop Entry]\nType=Application\nName=KidneyCyst\nComment=Pronephros segmentation and area measurement\nExec="%s" -m kidneycyst.gui\nIcon=%s/tools/icon.png\nTerminal=false\nCategories=Science;\n' "$PY" "$F" > "$HOME/.local/share/applications/kidneycyst.desktop"
rm -rf "$F/tools/uv-cache"
printf "\n\033[1;32m   Installation complete. Start KidneyCyst from the applications menu, or run %s/KidneyCyst\033[0m\n" "$HERE"
