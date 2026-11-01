@echo off
title AI Interview Copilot - One-Click Installer for Friend PC
cd /d "%~dp0"

echo =====================================================================
echo           AI INTERVIEW COPILOT - AUTOMATED SETUP WIZARD
echo =====================================================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python is not detected on this computer.
    echo [*] Installing Python automatically using Windows Package Manager...
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo [ERROR] Could not auto-install Python. Please download Python 3.10+ from https://www.python.org/downloads/
        echo Make sure to check "Add Python to PATH" during installation.
        pause
        exit /b 1
    )
    echo [*] Python installed! Please restart this setup script.
    pause
    exit /b 0
)

echo [OK] Python detected.

:: 2. Check Virtual Environment
if not exist ".venv\Scripts\python.exe" (
    echo [*] Creating isolated virtual environment (.venv)...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: 3. Install Dependencies
echo [*] Installing required packages (FastAPI, Groq, Gemini, Loopback Audio)...
".venv\Scripts\pip.exe" install --upgrade pip
".venv\Scripts\pip.exe" install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Package installation encountered an error.
    pause
    exit /b 1
)

:: 4. Check .env configuration
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo [!] Created .env file. Please ensure API keys (GROQ_API_KEY / GEMINI_API_KEY) are set in .env.
    )
)

:: 5. Create Desktop Icon
echo [*] Creating Desktop Shortcut with custom icon...
".venv\Scripts\python.exe" create_shortcut.py

echo.
echo =====================================================================
echo [SUCCESS] AI Interview Copilot is fully installed on this laptop!
echo Look on the Desktop for the "AI Interview Copilot" icon.
echo Double-clicking that icon will launch the software anytime.
echo =====================================================================
echo.
set /p launch="Would you like to start the software now? (Y/N): "
if /i "%launch%"=="Y" (
    start "" run.bat
)
