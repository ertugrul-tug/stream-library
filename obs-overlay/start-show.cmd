@echo off
cd /d "%~dp0"

set "SB=%LOCALAPPDATA%\Microsoft\WinGet\Packages\streamerbot.streamerbot_Microsoft.Winget.Source_8wekyb3d8bbwe\Streamer.bot.exe"
tasklist /FI "IMAGENAME eq Streamer.bot.exe" 2>nul | find /I "Streamer.bot.exe" >nul
if errorlevel 1 if exist "%SB%" start "" "%SB%"

netstat -ano | find ":8765 " | find "LISTENING" >nul
if errorlevel 1 (
  start "Qedy Show Bridge" cmd /k python "%~dp0show-bridge.py"
  timeout /t 2 /nobreak >nul
)
start "" "http://127.0.0.1:8766/kumanda.html"
