@echo off
title OmniSave - Universal Media & Song Downloader
color 0B
echo ========================================================
echo       OmniSave - Universal Media & Music Downloader
echo ========================================================
echo.
echo Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ from python.org and check "Add Python to PATH".
    pause
    exit /b 1
)

echo Checking dependencies...
python -m pip install -r requirements.txt --quiet

echo.
echo Starting server on http://localhost:5000 ...
start http://localhost:5000
python app.py
pause
