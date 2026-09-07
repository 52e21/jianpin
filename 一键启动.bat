@echo off
title AI Agent Service Manager
cd /d "%~dp0"

echo ==================================================
echo   AI Agent Task Assistant - Check and Start
echo ==================================================
echo.

rem ---------------- Backend :8002 ----------------
netstat -ano | findstr "LISTENING" | findstr ":8002" >nul 2>&1
if %errorlevel%==0 (
    echo [OK]  Backend is RUNNING  http://localhost:8002
) else (
    echo [..]  Backend NOT running. Starting...
    start "agent-backend" cmd /c "cd /d %~dp0backend && .venv\Scripts\python.exe -m uvicorn app.main:app --port 8002 --host 127.0.0.1"
    echo [OK]  Backend start command sent.
)

rem ---------------- Frontend :5174 ----------------
netstat -ano | findstr "LISTENING" | findstr ":5174" >nul 2>&1
if %errorlevel%==0 (
    echo [OK]  Frontend is RUNNING  http://localhost:5174
) else (
    echo [..]  Frontend NOT running. Starting...
    start "agent-frontend" cmd /c "cd /d %~dp0frontend && npm run dev"
    echo [OK]  Frontend start command sent.
)

echo.
echo ------------ Final Check -------------
netstat -ano | findstr "LISTENING" | findstr ":8002" >nul 2>&1 && (echo [OK]  Backend :8002 READY) || (echo [!!]  Backend :8002 NOT ready, check log window)
netstat -ano | findstr "LISTENING" | findstr ":5174" >nul 2>&1 && (echo [OK]  Frontend :5174 READY) || (echo [!!]  Frontend :5174 NOT ready, check log window)

echo.
echo Open browser:  http://localhost:5174
echo Health check:  http://localhost:8002/healthz
echo.
echo Press any key to close.
pause >nul