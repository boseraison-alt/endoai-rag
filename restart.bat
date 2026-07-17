@echo off
REM Restart endo-ai-rag Flask server (port 5000)
setlocal

echo [restart] Stopping anything on port 5000...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING"') do (
    echo   killing PID %%P
    taskkill /F /PID %%P >nul 2>&1
)

REM Small grace period so the port releases before we rebind
timeout /t 1 /nobreak >nul

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON=venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

echo [restart] Starting app.py with %PYTHON% ...
echo [restart] http://127.0.0.1:5000
echo.
"%PYTHON%" app.py

endlocal
