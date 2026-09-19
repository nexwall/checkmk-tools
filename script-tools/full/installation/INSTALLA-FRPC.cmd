@echo off
REM Launcher per install-frpc-pc.ps1 con bypass ExecutionPolicy
echo.
echo ========================================
echo   INSTALLAZIONE FRPC CLIENT
echo ========================================
echo.
echo Avvio script PowerShell con bypass ExecutionPolicy...
echo.

powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0install-frpc-pc.ps1"

echo.
echo Premi un tasto per chiudere...
pause >nul
