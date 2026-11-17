@echo off
:: Powered by HentaiP feat. ClawMoew & Maha
setlocal
cd /d "%~dp0"
:: Started from PowerShell 7, Windows PowerShell would inherit a module path it cannot use.
set "PSModulePath="
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_windows.ps1" %*
set "KARS_EXIT=%ERRORLEVEL%"
if not "%KARS_EXIT%"=="0" echo [ERROR] Deployment failed. No success is claimed.
exit /b %KARS_EXIT%
