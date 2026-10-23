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

rem First try the installed launcher, then fall back to the actual python.exe path.
set "PYEXE="
set "PYARGS="
where py >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.15 3.13 3.12 3.11) do (
    py -%%V -c "import sys" >nul 2>nul
    if not errorlevel 1 if not defined PYARGS (
      set "PYEXE=py"
      set "PYARGS=-%%V"
    )
  )
)
if defined PYEXE goto python_found

where python >nul 2>nul
if not errorlevel 1 (
  for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
  if defined PYEXE (
    "%PYEXE%" -c "import sys" >nul 2>nul
    if not errorlevel 1 goto python_found
  )
)

echo [ERROR] No se encontro una instalacion de Python que pueda ejecutarse.
echo Instala Python 3.12 de 64 bits desde https://www.python.org/downloads/release/python-31210/
echo Marca "Add python.exe to PATH" y luego vuelve a ejecutar este archivo.
pause
exit /b 1

:python_found
echo [OK] Interprete encontrado:
if "%PYEXE%"=="py" (
  %PYEXE% %PYARGS% --version
) else (
  "%PYEXE%" --version
)
echo.
echo [1/4] Preparando entorno virtual...
if not exist ".venv\Scripts\python.exe" (
  if "%PYEXE%"=="py" (
    py %PYARGS% -m venv ".venv"
  ) else (
    "%PYEXE%" -m venv ".venv"
  )
  if errorlevel 1 goto venv_error
)
if not exist ".venv\Scripts\python.exe" goto venv_error
".venv\Scripts\python.exe" -c "import sys; print(sys.version)"
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
echo [ERROR] No se pudo crear el entorno virtual .venv.
echo Si existe una carpeta .venv incompleta, renombrala a .venv_backup y vuelve a ejecutar.
echo Comprueba que Python incluya el modulo venv y que tengas permisos de escritura.
pause
exit /b 1

:error
echo.
echo [ERROR] No se pudieron instalar las dependencias.
echo Comprueba la conexion a Internet y revisa el mensaje anterior.
pause
exit /b 1
