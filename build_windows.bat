@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m PyInstaller packaging\AccessibilityAI.spec
exit /b %errorlevel%
:missing
echo Run setup.bat first.
pause
exit /b 1
