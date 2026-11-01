@echo off
title AI Interview Copilot - Desktop Icon Setup
cd /d "%~dp0"

echo ========================================================
echo    Setting up AI Interview Copilot Desktop Shortcut
echo ========================================================
echo.

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" create_shortcut.py
) else (
    python create_shortcut.py
)

echo.
echo ========================================================
echo All set! Look at your Desktop for the 'AI Interview Copilot' icon.
echo Double-clicking that icon will launch your tool anytime!
echo ========================================================
echo.
pause
