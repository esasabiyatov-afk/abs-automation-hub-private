@echo off
setlocal
set "APP_DIR=%~dp0"
set "PYTHON=%USERPROFILE%\Documents\Python_portable\python.exe"
if not exist "%PYTHON%" (
    echo Portable Python not found: %PYTHON%
    pause
    exit /b 1
)
"%PYTHON%" -X utf8 "%APP_DIR%tolubay_reports_app.py" --insecure
if errorlevel 1 pause
