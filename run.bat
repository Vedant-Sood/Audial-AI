@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" -m app.main %*
exit /b %errorlevel%
:missing
echo Run setup.bat first.
pause
exit /b 1
