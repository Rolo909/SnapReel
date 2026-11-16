@echo off
rem Starts SnapReel. On the first start it installs the components it needs (once).
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0app\setup\launcher.ps1" %*
