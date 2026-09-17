@echo off
cd /d "%~dp0"
py -3 --version >nul 2>&1
if errorlevel 1 goto fallback
py -3 algo.py
goto done
:fallback
python algo.py
:done
pause
