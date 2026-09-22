@echo off
start "Qedy Show Bridge" cmd /k python "%~dp0show-bridge.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8766/kumanda.html"
echo Telefon/tablet icin adres, "Qedy Show Bridge" penceresinde yazan LAN adresidir.
