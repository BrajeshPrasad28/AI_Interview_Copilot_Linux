@echo off
title AI Interview Copilot
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" run.py
) else (
    start "" pythonw run.py 2>nul || python run.py
)
exit /b 0
