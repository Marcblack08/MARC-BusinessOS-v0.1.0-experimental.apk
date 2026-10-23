@echo off
setlocal
cd /d "%~dp0"
title MARC Studio - Construir version portable
echo ============================================================
echo MARC VIDEO STUDIO AI DESKTOP - BUILD PORTABLE
echo Esto genera una carpeta portable, no un instalador MSI.
echo ============================================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo Ejecuta primero install_windows.bat.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --name "MARC Video Studio AI Desktop" app.py
if errorlevel 1 goto error
echo.
echo Build terminado en la carpeta dist.
echo IMPORTANTE: prueba la carpeta en Windows antes de distribuirla.
echo Ollama/Qwen y FFmpeg siguen siendo componentes locales separados.
pause
exit /b 0
:error
echo No se pudo construir la version portable.
pause
exit /b 1
