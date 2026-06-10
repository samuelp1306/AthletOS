@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  AthletOS Dev Launcher
echo ============================================================
echo.

REM --- 1) Auto-ingest latest Whoop export from Downloads ---
echo [1/7] Checking for new Whoop export in Downloads...
python -m engine.ingest.whoop_auto

REM --- 2) Free port 8000 if occupied ---
echo [2/7] Checking port 8000...
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

REM --- 3) Load .env into current process env (inherited by children) ---
echo [3/7] Loading .env...
if exist ".env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do (
        if not "%%a"=="" set "%%a=%%b"
    )
    echo   .env loaded.
) else (
    echo   No .env found -- skipping.
)

REM --- 4) Start FastAPI server (minimized background window) ---
echo [4/7] Starting FastAPI on :8000...
start "AthletOS API" /MIN cmd /k "python -m uvicorn api.server:app --reload --port 8000"

REM --- 5) Wait for API ---
echo [5/7] Waiting 3s for API to come up...
timeout /t 3 /nobreak >nul

REM --- 6) Start Vite frontend (minimized background window) ---
echo [6/7] Starting Vite frontend on :5173...
start "AthletOS Frontend" /MIN cmd /k "cd /d "%~dp0viz\frontend" && npm run dev"

REM --- 7) Wait, then open browser ---
echo [7/7] Waiting 3s, then opening browser...
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
