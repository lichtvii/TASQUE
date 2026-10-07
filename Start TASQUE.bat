@echo off
title TASQUE
cd /d "%~dp0"

if not exist ".env" (
    echo Missing .env - copy .env.example to .env and fill in DISCORD_TOKEN and OPENROUTER_API_KEY.
    goto :stop
)

if not exist ".venv\Scripts\python.exe" (
    echo First launch: setting up Python environment...
    python -m venv .venv || goto :setup_failed
)

".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt || goto :setup_failed

echo Starting TASQUE. Close this window or press Ctrl+C to stop it.
echo.
".venv\Scripts\python.exe" "%~dp0run.py"
echo.
echo TASQUE stopped.
goto :stop

:setup_failed
echo Setup failed. Make sure Python 3.11+ is installed and on PATH.

:stop
pause
