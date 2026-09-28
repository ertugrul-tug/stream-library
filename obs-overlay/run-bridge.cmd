@echo off
rem Keeps the show bridge running: if it ever exits or crashes mid-stream, it comes back in 3 seconds.
rem Its output also goes to .bridge.log next to this file, so the reason can be read afterwards.
title Qedy Show Bridge
cd /d "%~dp0"
:loop
python show-bridge.py
echo.
echo [%date% %time%] Kopru kapandi (kod %errorlevel%). 3 sn sonra yeniden baslatiliyor... Durdurmak icin bu pencereyi kapat.
timeout /t 3 /nobreak >nul
goto loop
