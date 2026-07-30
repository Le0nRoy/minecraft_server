@echo off
REM install-client-windows.bat - double-click wrapper for install-client-windows.ps1
REM
REM Explorer runs .ps1 files (if at all) without -ExecutionPolicy Bypass, which
REM hits the default Restricted execution policy and closes instantly with an
REM error. This wrapper calls PowerShell directly with the right flags so
REM double-clicking this file actually works, and keeps the window open
REM (-NoExit) so you can read the output when it's done.
REM
REM Always fetches the current script from GitHub, so it stays in sync with
REM the repo without needing the .ps1 file to sit next to it.

powershell -NoExit -ExecutionPolicy Bypass -Command "iex (irm 'https://raw.githubusercontent.com/Le0nRoy/minecraft_server/neoforge-1.21.1-migration/scripts/install-client-windows.ps1')"
