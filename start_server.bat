@echo off
title Elderly Care Monitoring System (ECMS)
echo ===================================================
echo Starting Elderly Care Monitoring System Server...
echo ===================================================
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found in venv folder!
    pause
    exit /b 1
)

echo Opening browser at http://127.0.0.1:8000 ...
start /b cmd /c "ping 127.0.0.1 -n 3 >nul && start http://127.0.0.1:8000"

echo Starting server process...
venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload

pause


