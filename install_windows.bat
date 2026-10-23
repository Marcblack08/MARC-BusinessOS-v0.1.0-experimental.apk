@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MARC Studio - Instalacion
color 0B
echo ============================================================
echo   MARC VIDEO STUDIO AI DESKTOP
echo   Preparacion local - sin claves API
echo ============================================================
echo.

where py >nul 2>nul
if not errorlevel 1 (
  py -3.11 --version >nul 2>nul
  if not errorlevel 1 (
    set "PY=py -3.11"
    goto python_found
  )
  py -3.12 --version >nul 2>nul
  if not errorlevel 1 (
    set "PY=py -3.12"
    goto python_found
  )
)
where python >nul 2>nul
if not errorlevel 1 (
  python --version
  set "PY=python"
  goto python_found
)
echo [ERROR] No se encontro Python 3.11 o superior.
echo Instala Python 3.11+ y activa la opcion "Add Python to PATH".
echo Luego vuelve a ejecutar este archivo.
pause
exit /b 1

:python_found
echo [1/4] Preparando entorno de Python...
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
  if errorlevel 1 goto error
)
echo [2/4] Actualizando herramientas de instalacion...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto error
echo [3/4] Instalando dependencias del proyecto...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error
echo [4/4] Revisando herramientas opcionales...
where ollama >nul 2>nul
if errorlevel 1 (
  echo [AVISO] Ollama no aparece en PATH. La IA local requiere instalar Ollama.
) else (
  echo [OK] Ollama encontrado.
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [AVISO] FFmpeg no aparece en PATH. MARC permitira seleccionar ffmpeg.exe al exportar.
) else (
  echo [OK] FFmpeg encontrado.
)
echo.
echo ============================================================
echo Instalacion completada.
echo Para abrir MARC, ejecuta start_windows.bat.
echo Para crear una version portable, ejecuta build_windows.bat.
echo ============================================================
pause
exit /b 0

:error
echo.
echo [ERROR] No se pudo completar la instalacion.
echo Revisa la conexion a Internet y vuelve a intentarlo.
pause
exit /b 1
