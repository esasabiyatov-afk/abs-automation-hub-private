@echo off
setlocal
set "APP_DIR=%~dp0"
set "PORTABLE_APP=%APP_DIR%release\TolubayReports.exe"
if exist "%PORTABLE_APP%" (
    "%PORTABLE_APP%" --insecure
    exit /b %errorlevel%
)
set "PYTHON=%USERPROFILE%\Documents\Python_portable\python.exe"
if not exist "%PYTHON%" (
    echo Portable app not found: %PORTABLE_APP%
    echo Portable Python not found: %PYTHON%
    pause
    exit /b 1
)
"%PYTHON%" -X utf8 "%APP_DIR%tolubay_reports_app.py" --insecure
if errorlevel 1 pause
