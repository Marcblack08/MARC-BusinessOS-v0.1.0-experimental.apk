@echo off
setlocal
cd /d "%~dp0"
title MARC Video Studio AI Desktop
if not exist ".venv\Scripts\python.exe" (
  echo MARC aun no esta preparado.
  echo Ejecuta primero install_windows.bat.
  pause
  exit /b 1
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" app.py
  exit /b 0
)
".venv\Scripts\python.exe" app.py
if errorlevel 1 (
  echo.
  echo MARC termino con un error. Copia el mensaje anterior para diagnosticarlo.
  pause
)
