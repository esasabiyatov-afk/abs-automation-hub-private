@echo off
setlocal
"%~dp0TolubayReports.exe" --insecure
if errorlevel 1 pause
