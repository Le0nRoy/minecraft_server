@echo off
setlocal
set "INSTANCE_DIR=%~dp0"
if "%INSTANCE_DIR:~-1%"=="\" set "INSTANCE_DIR=%INSTANCE_DIR:~0,-1%"
set "TMPPS1=%TEMP%\mip-uninstall-%RANDOM%.ps1"
copy "%~dp0uninstall.ps1" "%TMPPS1%" >nul
start "Uninstall Minecraft Infra Pack" powershell -NoExit -ExecutionPolicy Bypass -File "%TMPPS1%" -InstanceDir "%INSTANCE_DIR%"
exit /b
