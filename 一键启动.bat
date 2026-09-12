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

rem ---------------- Frontend :3016 ----------------
netstat -ano | findstr "LISTENING" | findstr ":3016" >nul 2>&1
if %errorlevel%==0 (
    echo [OK]  Frontend is RUNNING  http://localhost:3016
) else (
    echo [..]  Frontend NOT running. Starting...
    rem 项目端口统一为 3016（package.json / vite.config.ts / 后端 CORS 均为 3016），这里显式指定以防配置漂移
    rem 本地启动固定把 API 地址指向本机后端，避免 frontend\.env 里过期的公网地址生效
    start "agent-frontend" cmd /c "cd /d %~dp0frontend && set VITE_API_BASE_URL=http://127.0.0.1:8002&& npx vite --port 3016 --host 0.0.0.0 --strictPort"
    echo [OK]  Frontend start command sent.
)

echo.
echo ------------ Final Check -------------
netstat -ano | findstr "LISTENING" | findstr ":8002" >nul 2>&1 && (echo [OK]  Backend :8002 READY) || (echo [!!]  Backend :8002 NOT ready, check log window)
netstat -ano | findstr "LISTENING" | findstr ":3016" >nul 2>&1 && (echo [OK]  Frontend :3016 READY) || (echo [!!]  Frontend :3016 NOT ready, check log window)

echo.
echo Open browser:  http://localhost:3016
echo Health check:  http://localhost:8002/healthz
echo.
echo Press any key to close.
pause >nul
