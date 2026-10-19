@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
set "PATH=%CD%\.venv\Scripts;%PATH%"
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1
powershell -NoProfile -File scripts\build_windows.ps1 %*
exit /b %errorlevel%
:missing
echo Run setup.bat first.
pause
exit /b 1
