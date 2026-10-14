@echo off
:: Powered by HentaiP feat. ClawMoew
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_windows.ps1" %*
set "KARS_EXIT=%ERRORLEVEL%"
if not "%KARS_EXIT%"=="0" echo [ERROR] Deployment failed. No success is claimed.
exit /b %KARS_EXIT%
