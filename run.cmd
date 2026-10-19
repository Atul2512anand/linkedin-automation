@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [setup] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto :error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

if not exist "config.yaml" (
    copy /Y "config.example.yaml" "config.yaml" >nul
    echo [setup] Created config.yaml from config.example.yaml
)

".venv\Scripts\python.exe" -m la %*
exit /b %ERRORLEVEL%

:error
echo.
echo Setup failed. Check that Python 3.10+ is installed and on PATH.
exit /b 1
