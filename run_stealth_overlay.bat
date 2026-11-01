@echo off
title Stealth Overlay Launcher
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" desktop_overlay.py
) else (
    start "" python desktop_overlay.py
)
exit
