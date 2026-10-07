@echo off
title Disable TASQUE Autostart
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\autostart.ps1" disable
echo.
echo To turn it back on, run "Enable TASQUE Autostart.bat".
pause
