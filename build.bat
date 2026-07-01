@echo off
setlocal
cd /d "%~dp0"
py -m pip install --upgrade pyinstaller
if errorlevel 1 goto :error
py -m PyInstaller --noconfirm --clean --onefile --windowed --name "定时连点器" autoclicker.py
if errorlevel 1 goto :error
echo.
echo Build complete: dist\定时连点器.exe
pause
exit /b 0
:error
echo.
echo Build failed. Install Python 3.11 or newer and try again.
pause
exit /b 1
