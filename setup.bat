@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto missing
if exist ".venv\Scripts\python.exe" goto installed
py -3.11 -m venv .venv
if not errorlevel 1 goto installed
py -3.12 -m venv .venv
if errorlevel 1 goto missing
:installed
".venv\Scripts\python.exe" -m scripts.setup_windows %*
if errorlevel 1 goto failed
exit /b 0
:missing
echo Install Python 3.11 x64 from https://www.python.org/downloads/windows/ with the Python launcher enabled.
echo Then run setup.bat again. Your files are not changed.
pause
exit /b 1
:failed
echo Setup stopped. Read the error above and docs\troubleshooting.md.
echo Use setup.bat --cpu if NVIDIA CUDA libraries could not load.
pause
exit /b 1
