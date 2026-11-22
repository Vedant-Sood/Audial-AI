@echo off
rem Kandha Stole: build, flash and open the serial console (Windows). Double-click, or run:
rem   firmware\kandha\flash.bat            build, flash, then open the console
rem   firmware\kandha\flash.bat -Port COM5 use this port
rem   firmware\kandha\flash.bat -MonitorOnly   only open the console
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0flash.ps1" %*
if errorlevel 1 pause
