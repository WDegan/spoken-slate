@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10-3.12, then run this setup again.
  pause
  exit /b 1
)

python -c "import sys; assert (3, 10) <= sys.version_info[:2] <= (3, 12), 'Python 3.10-3.12 is required'"
if errorlevel 1 (
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto failed

".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed

".venv\Scripts\python.exe" download_assets.py
if errorlevel 1 goto failed

echo.
echo SpokenSlate is ready. Open a folder in Explorer and launch "Launch SpokenSlate.vbs".
pause
exit /b 0

:failed
echo.
echo Setup did not finish. Check the error above and run this file again.
pause
exit /b 1
