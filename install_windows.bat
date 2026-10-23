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

set "PYEXE="
set "PYARGS="

rem Test each runtime explicitly; do not rely on py --version error handling.
where py >nul 2>nul
if not errorlevel 1 (
  py -3.13 -c "import sys" >nul 2>nul
  if not errorlevel 1 goto use_py313
  py -3.12 -c "import sys" >nul 2>nul
  if not errorlevel 1 goto use_py312
  py -3.11 -c "import sys" >nul 2>nul
  if not errorlevel 1 goto use_py311
)

rem Fallback to python.exe on PATH.
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys" >nul 2>nul
  if not errorlevel 1 goto use_python
)

echo [ERROR] No se encontro una instalacion funcional de Python 3.11, 3.12 o 3.13.
echo.
echo Instala Python 3.12 de 64 bits desde:
echo https://www.python.org/downloads/release/python-31210/
echo Durante la instalacion marca "Add python.exe to PATH".
echo Luego cierra esta ventana y ejecuta este archivo de nuevo.
echo.
pause
exit /b 1

:use_py313
set "PYEXE=py"
set "PYARGS=-3.13"
goto python_found
:use_py312
set "PYEXE=py"
set "PYARGS=-3.12"
goto python_found
:use_py311
set "PYEXE=py"
set "PYARGS=-3.11"
goto python_found
:use_python
set "PYEXE=python"
set "PYARGS="
goto python_found

:python_found
echo [OK] Python detectado:
%PYEXE% %PYARGS% --version
if errorlevel 1 goto no_runtime
echo.
echo [1/4] Preparando entorno virtual...
if not exist ".venv\Scripts\python.exe" (
  %PYEXE% %PYARGS% -m venv .venv
  if errorlevel 1 goto venv_error
)
if not exist ".venv\Scripts\python.exe" goto venv_error

echo [2/4] Actualizando herramientas de instalacion...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto error

echo [3/4] Instalando dependencias del proyecto...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error

echo [4/4] Revisando herramientas opcionales...
where ollama >nul 2>nul
if errorlevel 1 (
  echo [AVISO] Ollama no aparece en PATH. Instala Ollama para usar la IA local.
) else (
  echo [OK] Ollama encontrado.
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [AVISO] FFmpeg no aparece en PATH. Puedes seleccionar ffmpeg.exe desde MARC al exportar.
) else (
  echo [OK] FFmpeg encontrado.
)
echo.
echo ============================================================
echo Instalacion de dependencias completada.
echo Abre MARC con start_windows.bat.
echo Para empaquetar la aplicacion, usa build_windows.bat.
echo ============================================================
pause
exit /b 0

:no_runtime
echo [ERROR] El lanzador de Python no pudo abrir el runtime elegido.
pause
exit /b 1

:venv_error
echo.
echo [ERROR] Python se detecto, pero no se pudo crear .venv.
echo Comprueba que Python tenga el modulo venv y permisos de escritura.
echo Si .venv esta incompleta, renombrala a .venv_backup y vuelve a ejecutar.
pause
exit /b 1

:error
echo.
echo [ERROR] No se pudo completar la instalacion de dependencias.
echo Comprueba la conexion a Internet y el contenido de requirements.txt.
pause
exit /b 1
