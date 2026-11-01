@echo off
title Stop AI Interview Copilot
cd /d "%~dp0"
echo ========================================================
echo    Stopping AI Interview Copilot Background Tasks
echo ========================================================
echo.

:: 1. Terminate windows by title
taskkill /F /FI "WINDOWTITLE eq Realtek HD Audio Universal Service*" /T 2>nul
taskkill /F /FI "WINDOWTITLE eq AI Interview Copilot*" /T 2>nul
taskkill /F /FI "WINDOWTITLE eq Stealth Overlay Launcher*" /T 2>nul
taskkill /F /FI "WINDOWTITLE eq Interview Stealth Overlay*" /T 2>nul
taskkill /F /FI "WINDOWTITLE eq AI Interview Copilot*" /T 2>nul


:: 2. Determine target port from .env or default to 8585
set TARGET_PORT=8585
if exist ".env" (
    for /f "tokens=1,2 delims==" %%i in (.env) do (
        if "%%i"=="PORT" set TARGET_PORT=%%j
    )
)

:: 3. Terminate process on TARGET_PORT
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :%TARGET_PORT% ^| findstr LISTENING') do (
    echo Stopping process on port %TARGET_PORT% (PID %%a)...
    taskkill /F /PID %%a 2>nul
)

:: Also clean up default 8585 if TARGET_PORT was different
if not "%TARGET_PORT%"=="8585" (
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8585 ^| findstr LISTENING') do (
        echo Stopping process on port 8585 (PID %%a)...
        taskkill /F /PID %%a 2>nul
    )
)

echo.
echo AI Interview Copilot stopped successfully.
timeout /t 3

