@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  AthletOS Dev Launcher
echo ============================================================
echo.

REM --- 1) Free port 8000 if occupied ---
echo [1/6] Checking port 8000...
set "FOUND_PID="
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    set "FOUND_PID=%%a"
)
if defined FOUND_PID (
    echo   Port 8000 in use by PID !FOUND_PID! -- killing...
    taskkill /F /PID !FOUND_PID! >nul 2>&1
    timeout /t 1 /nobreak >nul
) else (
    echo   Port 8000 free.
)

REM --- 2) Load .env into current process env (inherited by children) ---
echo [2/6] Loading .env...
if exist ".env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do (
        if not "%%a"=="" set "%%a=%%b"
    )
    echo   .env loaded.
) else (
    echo   No .env found -- skipping.
)

REM --- 3) Start FastAPI server (minimized background window) ---
echo [3/6] Starting FastAPI on :8000...
start "AthletOS API" /MIN cmd /k "python -m uvicorn api.server:app --reload --port 8000"

REM --- 4) Wait for API ---
echo [4/6] Waiting 3s for API to come up...
timeout /t 3 /nobreak >nul

REM --- 5) Start Vite frontend (minimized background window) ---
echo [5/6] Starting Vite frontend on :5173...
start "AthletOS Frontend" /MIN cmd /k "cd /d "%~dp0viz\frontend" && npm run dev"

REM --- 6) Wait, then open browser ---
echo [6/6] Waiting 3s, then opening browser...
timeout /t 3 /nobreak >nul
start "" "http://localhost:5173"

echo.
echo ============================================================
echo  Started
echo    API:      http://localhost:8000
echo    Frontend: http://localhost:5173
echo ============================================================
echo.
echo Closing THIS window does NOT stop the servers.
echo To stop them, close the minimized "AthletOS API" and
echo "AthletOS Frontend" windows in the taskbar.
echo.
pause
