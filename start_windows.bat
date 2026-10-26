@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MARC Video Studio AI Desktop
if exist "%~dp0MARC Video Studio AI Desktop.exe" (
  start "" "%~dp0MARC Video Studio AI Desktop.exe"
  exit /b 0
)
if not exist ".venv\Scripts\python.exe" (
  echo MARC aun no esta preparado.
  echo Ejecuta install_windows.bat para preparar el entorno de desarrollo.
  pause
  exit /b 1
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" marc_launcher.py
  exit /b 0
)
".venv\Scripts\python.exe" marc_launcher.py
if errorlevel 1 (
  echo.
  echo MARC termino con un error. Copia el mensaje anterior para diagnosticarlo.
  pause
)
