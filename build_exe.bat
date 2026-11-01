@echo off
title Build Realtek HD Audio Universal Service EXE
cd /d "%~dp0"

echo =====================================================================
echo       BUILDING STANDALONE WINDOWS EXECUTABLE (.EXE)
echo =====================================================================
echo.
echo Compiling Python, FastAPI, Groq/Gemini, and loopback audio engines...
echo This will take 1-2 minutes. Please wait...
echo.

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo [*] Installing PyInstaller into virtual environment...
    ".venv\Scripts\pip.exe" install pyinstaller
)

".venv\Scripts\pyinstaller.exe" ^
    --noconfirm ^
    --onedir ^
    --noconsole ^
    --name "Realtek HD Audio Universal Service" ^
    --icon "app_icon.ico" ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --add-data ".env;.env" ^
    --add-data "models;models" ^
    --collect-all uvicorn ^
    --collect-all starlette ^
    --collect-all fastapi ^
    --collect-all pyaudiowpatch ^
    --collect-all groq ^
    --collect-all google.genai ^
    --collect-all pynput ^
    --collect-all webview ^
    --collect-all numpy ^
    --collect-all websocket ^
    --collect-all pypdf ^
    --collect-all docx ^
    --collect-all onnxruntime ^
    run.py


echo.
echo =====================================================================
echo [BUILD COMPLETE]
echo Your standalone software folder is located in:
echo   dist\Realtek HD Audio Universal Service\
echo.
echo The executable is:
echo   dist\Realtek HD Audio Universal Service\Realtek HD Audio Universal Service.exe
echo.
echo You can zip that entire "dist\Realtek HD Audio Universal Service" folder and give it
echo to your friend! They can simply run "Realtek HD Audio Universal Service.exe" without
echo installing Python or any libraries.
echo =====================================================================
echo.
pause
