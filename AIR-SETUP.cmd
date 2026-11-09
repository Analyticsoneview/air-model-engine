@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0AIR-SETUP.ps1" %*
exit /b %ERRORLEVEL%
