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

rem Check available interpreter versions explicitly; Python Launcher errors are not reliable via IF ERRORLEVEL alone.
where py >nul 2>nul
if not errorlevel 1 (
  py -3.15 -c "import sys; print(sys.executable)" >nul 2>nul && (set "PYEXE=py"& set "PYARGS=-3.15"& goto python_found)
  py -3.13 -c "import sys; print(sys.executable)" >nul 2>nul && (set "PYEXE=py"& set "PYARGS=-3.13"& goto python_found)
  py -3.12 -c "import sys; print(sys.executable)" >nul 2>nul && (set "PYEXE=py"& set "PYARGS=-3.12"& goto python_found)
  py -3.11 -c "import sys; print(sys.executable)" >nul 2>nul && (set "PYEXE=py"& set "PYARGS=-3.11"& goto python_found)
)

rem Fallback: resolve the real python executable path, if it works.
where python >nul 2>nul
if not errorlevel 1 (
  for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
  if defined PYEXE (
    "%PYEXE%" -c "import sys" >nul 2>nul
    if not errorlevel 1 goto python_found
  )
)

echo [ERROR] No se encontro Python utilizable.
echo.
echo Python detectado en el sistema, pero el lanzador no puede abrirlo.
echo Recomendacion: instala Python 3.12 de 64 bits desde:
echo https://www.python.org/downloads/release/python-31210/
echo Marca "Add Python to PATH" durante la instalacion.
echo.
pause
exit /b 1

:python_found
echo [OK] Interprete utilizable:
%PYEXE% %PYARGS% --version
if errorlevel 1 goto no_runtime
echo.
echo [1/4] Preparando entorno virtual...
if not exist ".venv\Scripts\python.exe" (
  %PYEXE% %PYARGS% -m venv ".venv"
  if errorlevel 1 goto venv_error
)
if not exist ".venv\Scripts\python.exe" goto venv_error
".venv\Scripts\python.exe" -c "import sys; print(sys.executable)" 
if errorlevel 1 goto venv_error

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

:venv_error
echo.
echo [ERROR] Python se detecto, pero no se pudo crear .venv.
echo Si .venv esta incompleta, renombrala a .venv_backup y vuelve a ejecutar.
echo Comprueba que Python incluya el modulo venv y permisos de escritura.
pause
exit /b 1

:error
echo.
echo [ERROR] No se pudieron instalar las dependencias.
echo Revisa la conexion a Internet y el mensaje de error anterior.
pause
exit /b 1

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
