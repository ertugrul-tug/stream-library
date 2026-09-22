@echo off
start "" "%~dp0kumanda.html"
python "%~dp0show-bridge.py"
if errorlevel 1 pause
