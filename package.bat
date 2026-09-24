@echo off
rem WutheringWavesTools one-click packaging (PyInstaller + Inno Setup).
rem Double-click this file, or run from a terminal:  package.bat 0.4.0
rem With no argument the version comes from src\app_config.py (APP_VERSION).
rem Keep this file ASCII-only: the actual logic lives in package.ps1 (UTF-8 BOM).

setlocal
if "%~1"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0package.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0package.ps1" -Version %1
)
set EXITCODE=%ERRORLEVEL%
echo.
pause
exit /b %EXITCODE%
