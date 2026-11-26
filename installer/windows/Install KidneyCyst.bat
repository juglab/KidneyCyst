@echo off
rem KidneyCyst installer for Windows. Double-click once. No administrator rights needed.
rem Afterwards start KidneyCyst from the desktop or the Start menu.
setlocal
cd /d "%~dp0"
set "HERE=%~dp0"
set "F=%HERE%files\"
set "UV=%F%tools\uv.exe"
set "UV_CACHE_DIR=%F%tools\uv-cache"
set "UV_PYTHON_INSTALL_DIR=%F%tools\python"
set "PY=%F%env\Scripts\python.exe"
echo.
echo  KidneyCyst installer
echo  Installation requires an internet connection. Keep this window open until installation finishes.
call :step "Step 1 of 4: Creating a local Python environment..."
"%UV%" venv "%F%env" --python 3.12 --clear || goto :fail
call :step "Step 2 of 4: Downloading and installing PyTorch..."
"%UV%" pip install --python "%PY%" --compile-bytecode "torch!=2.9.*" --torch-backend=auto || goto :fail
call :step "Step 3 of 4: Installing KidneyCyst and dependencies..."
"%UV%" pip install --python "%PY%" --compile-bytecode -r "%F%app\requirements.txt" "%F%app\kidneycyst-0.1.0-py3-none-any.whl" || goto :fail
call :step "Step 4 of 4: Running a sample-image test..."
set "KIDNEYCYST_HOME=%F%"
"%PY%" -m kidneycyst.setup_local || goto :fail
echo.
echo    Creating KidneyCyst shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; foreach($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'), '%HERE%'.TrimEnd('\'))){ $s=$w.CreateShortcut((Join-Path $d 'KidneyCyst.lnk')); $s.TargetPath='%F%env\Scripts\pythonw.exe'; $s.Arguments='-m kidneycyst.gui'; $s.WorkingDirectory='%F%'.TrimEnd('\'); $s.IconLocation='%F%tools\KidneyCyst.ico'; $s.Description='KidneyCyst: pronephros segmentation and area measurement'; $s.Save() }"
if exist "%F%tools\uv-cache" rmdir /s /q "%F%tools\uv-cache"
echo.
powershell -NoProfile -Command "Write-Host '   Installation complete. KidneyCyst opens now. Next time, open it from the desktop or the Start menu.' -ForegroundColor Green"
start "" "%F%env\Scripts\pythonw.exe" -m kidneycyst.gui
timeout /t 15
exit /b 0
:step
echo.
powershell -NoProfile -Command "Write-Host '== %~1' -ForegroundColor Cyan"
echo.
exit /b 0
:fail
echo.
powershell -NoProfile -Command "Write-Host '   Installation failed. Send the error details to aman.kukde@fht.org.' -ForegroundColor Red"
echo.
pause
exit /b 1
