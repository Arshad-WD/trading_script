@echo off
title Institutional Trading Intelligence System
color 0A
cd /d "%~dp0"

echo ===================================================================
echo     Institutional Orderflow & F&O Trading Engine (Angel One)
echo ===================================================================
echo.

:: 1. Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [ERROR] Python is not detected on this computer!
    echo.
    echo Please follow these 2 simple steps:
    echo  1. Download Python from: https://www.python.org/downloads/
    echo  2. IMPORTANT: In the installer, check the box:
    echo     [X] "Add python.exe to PATH"
    echo  3. After installation finishes, double-click this file again!
    echo.
    pause
    exit /b 1
)

:: 2. Check if virtual environment exists; if not, create and install packages
if not exist "venv\Scripts\python.exe" (
    echo [FIRST TIME SETUP DETECTED]
    echo Setting up your trading environment. This takes about 1-2 minutes...
    echo.
    echo [1/3] Creating virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        color 0C
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )

    echo [2/3] Upgrading pip package installer...
    .\venv\Scripts\python.exe -m pip install --upgrade pip --quiet

    echo [3/3] Installing institutional trading packages...
    .\venv\Scripts\python.exe -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        color 0C
        echo [ERROR] Failed to install required packages. Check internet connection.
        pause
        exit /b 1
    )
    echo.
    echo [SETUP COMPLETE] All packages installed successfully!
    echo ===================================================================
    echo.
)

:: 3. Check if .env configuration file exists
if not exist ".env" (
    if exist ".env.example" (
        echo [NOTICE] Creating .env from template...
        copy ".env.example" ".env" >nul
        echo [WARNING] Please open the .env file in Notepad and add your Angel One API credentials!
        echo.
        pause
    )
)

:: 4. Start the live trading engine
echo [STARTING] Connecting to Angel One live WebSocket stream...
echo Press Ctrl+C at any time to stop.
echo.
.\venv\Scripts\python.exe main.py --broker angel

echo.
echo ===================================================================
echo   Engine stopped.
echo ===================================================================
pause
