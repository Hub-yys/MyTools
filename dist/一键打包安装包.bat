@echo off
rem ============================================================================
rem  One-click installer builder (lives in dist\).
rem
rem  Double-click this file for an interactive menu, or pass a mode:
rem      packaging.bat full        -> full rebuild (source -> green build -> installer)
rem      packaging.bat installer   -> installer only (reuse dist\WutheringWavesTools)
rem
rem  Why this file is ASCII-only: cmd renders .bat in the OEM codepage, so Chinese
rem  text here would come out garbled. All the Chinese UI lives in
rem  build_installer.ps1, which is UTF-8 **with BOM** (see the project README).
rem ============================================================================
setlocal
set "PS1=%~dp0build_installer.ps1"

if not exist "%PS1%" goto :nops1
if "%~1"=="" goto :menu

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -Mode %1
exit /b %ERRORLEVEL%

:menu
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
set "EXITCODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXITCODE%

:nops1
echo [!] build_installer.ps1 not found next to this file.
echo     Keep both files together in dist\.
pause
exit /b 1
