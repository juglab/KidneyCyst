#!/bin/bash
# KidneyCyst installer for Mac (Apple Silicon). Double-click once (first time: right-click > Open).
# Afterwards KidneyCyst is an ordinary app: Applications, Launchpad, Spotlight or the Desktop icon.
cd "$(dirname "$0")"; HERE="$(pwd)"; F="$HERE/files"
step() { printf "\n\033[1;36m━━ Step %s of 4: %s\033[0m\n\n" "$1" "$2"; }
ok()   { printf "\033[32m   ✓ %s\033[0m\n" "$1"; }
fail() { printf "\n\033[1;31m   ✗ Installation failed. Send the error details to aman.kukde@fht.org.\033[0m\n\n"; read -n1 -r -p " Press any key to close."; exit 1; }
if [ "$(uname -m)" != "arm64" ]; then echo " Intel Macs are not supported by this build. An Apple Silicon Mac (M1 or later) is required."; fail; fi
if ! df -l "$HERE" >/dev/null 2>&1; then   # network drive / server share: Python environments cannot be created there
  echo " This folder is on a network drive. Copy the whole KidneyCyst folder into Documents, then double-click Install KidneyCyst there."; fail; fi
xattr -dr com.apple.quarantine "$HERE" 2>/dev/null   # let the bundled tools run (macOS blocks downloaded programs)
UV="$F/tools/uv"; chmod +x "$UV"
export UV_CACHE_DIR="$F/tools/uv-cache" UV_PYTHON_INSTALL_DIR="$F/tools/python"
PY="$F/env/bin/python"
printf "\n\033[1m KidneyCyst installer\033[0m\n Installation requires an internet connection. Keep this window open until installation finishes.\n"
step 1 "Creating a local Python environment…"
"$UV" venv "$F/env" --python 3.12 --clear || fail; ok "Python ready"
step 2 "Downloading and installing PyTorch…"
"$UV" pip install --python "$PY" --compile-bytecode 'torch!=2.9.*' || fail; ok "PyTorch ready"
step 3 "Installing KidneyCyst and dependencies…"
"$UV" pip install --python "$PY" --compile-bytecode -r "$F/app/requirements.txt" "$F"/app/kidneycyst-*.whl || fail
ok "KidneyCyst installed"
step 4 "Running a sample-image test…"
KIDNEYCYST_HOME="$F" "$PY" -m kidneycyst.setup_local || fail

printf "\n   Creating the KidneyCyst app…\n"
RUNNER="$F/tools/start_kidneycyst.sh"
cat > "$RUNNER" <<EOS
#!/bin/bash
# Started by the KidneyCyst app. Opens the KidneyCyst page in the default browser; output goes to a log file.
LOG="$F/kidneycyst_app_log.txt"
echo "=== \$(date) starting KidneyCyst" >> "\$LOG"
"$F/env/bin/python" -m kidneycyst.gui >> "\$LOG" 2>&1; RC=\$?
[ \$RC -ne 0 ] && [ \$RC -lt 128 ] && osascript -e 'display dialog "KidneyCyst could not start. Send kidneycyst_app_log.txt from the installation folder to aman.kukde@fht.org." buttons {"OK"} with icon stop'
EOS
chmod +x "$RUNNER"
APP="$HERE/KidneyCyst.app"; rm -rf "$APP"
osacompile -o "$APP" -e "do shell script quoted form of \"$RUNNER\" & \" > /dev/null 2>&1 &\"" >/dev/null 2>&1 || fail
RES="$APP/Contents/Resources"; PL="$APP/Contents/Info.plist"; PB=/usr/libexec/PlistBuddy
cp "$F/tools/KidneyCyst.icns" "$RES/applet.icns"
rm -f "$RES/Assets.car"                                    # newer macOS puts the default icon here; it would win
$PB -c "Delete :CFBundleIconName" "$PL" 2>/dev/null
$PB -c "Set :CFBundleIconFile applet" "$PL" 2>/dev/null || $PB -c "Add :CFBundleIconFile string applet" "$PL"
$PB -c "Set :CFBundleName KidneyCyst" "$PL" 2>/dev/null
codesign --force --deep --sign - "$APP" >/dev/null 2>&1   # changing the icon breaks the signature: sign again
touch "$APP"
mkdir -p "$HOME/Applications"; rm -rf "$HOME/Applications/KidneyCyst.app"
ditto "$APP" "$HOME/Applications/KidneyCyst.app"
rm -f "$HOME/Desktop/KidneyCyst"; ln -s "$HOME/Applications/KidneyCyst.app" "$HOME/Desktop/KidneyCyst"
rm -rf "$F/tools/uv-cache"                                 # downloads no longer needed (saves disk space)
ok "KidneyCyst app created (Applications, Desktop and this folder)"
printf "\n\033[1;32m   Installation complete. KidneyCyst opens now. Next time, open it from Applications or the Desktop.\033[0m\n\n"
open "$HOME/Applications/KidneyCyst.app"
read -n1 -r -t 20 -p " This window closes by itself." ; echo
osascript -e 'tell application "Terminal" to close (every window whose name contains "Install KidneyCyst")' >/dev/null 2>&1 &
exit 0
