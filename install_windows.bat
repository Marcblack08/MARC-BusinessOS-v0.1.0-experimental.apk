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
  rem Prefer Python 3.12, the version used by the Windows validation workflow.
  for %%V in (3.12 3.11 3.13 3.14) do (
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

echo [4/6] Instalando herramientas gratuitas necesarias...
where winget >nul 2>nul
if errorlevel 1 goto manual_tools

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [AUTO] Instalando FFmpeg para exportar MP4...
  winget install --id Gyan.FFmpeg.Shared --exact --silent --accept-package-agreements --accept-source-agreements
  if errorlevel 1 echo [AVISO] Winget no pudo instalar FFmpeg; MARC seguira permitiendo seleccionarlo manualmente.
)

where ollama >nul 2>nul
if errorlevel 1 (
  echo [AUTO] Instalando Ollama para guiones locales sin pagar API...
  winget install --id Ollama.Ollama --exact --silent --accept-package-agreements --accept-source-agreements
  if errorlevel 1 echo [AVISO] Winget no pudo instalar Ollama; consulta https://ollama.com/download
)

rem Refresh common per-user paths for tools installed during this session.
if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links" set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
if exist "%LOCALAPPDATA%\Programs\Ollama" set "PATH=%LOCALAPPDATA%\Programs\Ollama;%PATH%"
if exist "C:\Program Files\FFmpeg\bin" set "PATH=C:\Program Files\FFmpeg\bin;%PATH%"

:tools_ready
echo.
echo [5/6] Comprobando FFmpeg y Ollama...
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [AVISO] FFmpeg no se detecto en PATH. MARC puede buscarlo o permitir seleccionarlo.
) else (
  echo [OK] FFmpeg disponible.
)
where ollama >nul 2>nul
if errorlevel 1 (
  echo [AVISO] Ollama no se detecto en PATH. La importacion de guion, imagenes, voz y montaje seguira disponible.
  goto tests
)
echo [OK] Ollama disponible.
ollama list 2>nul | findstr /I /C:"qwen2.5:3b" >nul
if not errorlevel 1 (
  echo [OK] Qwen 2.5 3B ya esta descargado; se omite otra descarga.
  goto tests
)
echo [AUTO] Descargando Qwen 2.5 3B, modelo gratuito local para generar guiones.
echo Esta descarga ocupa varios GB y necesita conexion a Internet.
ollama pull qwen2.5:3b
if errorlevel 1 echo [AVISO] No se pudo descargar Qwen. Puedes volver a intentarlo luego con: ollama pull qwen2.5:3b

:tests
echo.
echo [6/6] Validacion automatizada...
".venv\Scripts\python.exe" -m compileall -q app.py scene_engine.py story_engine.py voice_engine.py production_pipeline.py media_quality.py remote_server.py
if errorlevel 1 (
  echo [AVISO] La comprobacion de sintaxis detecto errores. Revisa el registro antes de ejecutar MARC.
) else (
  echo [OK] Sintaxis Python validada.
)
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 echo [AVISO] Algunas pruebas no pasaron. La instalacion sigue, pero revisa los resultados anteriores.
echo.
echo ============================================================
echo Preparacion de MARC terminada.
echo Abre MARC con start_windows.bat.
echo Para crear un instalador empaquetado, usa build_windows.bat.
echo El motor de imagenes IA es opcional; puedes importar tus propias imagenes sin descargar modelos.
echo ============================================================
echo.
echo Abriendo MARC Video Studio AI...
start "" "%~dp0start_windows.bat"
pause
exit /b 0

:manual_tools
echo [AVISO] Winget no esta disponible. Para instalar herramientas automaticamente, instala App Installer de Microsoft Store.
echo Puedes instalar FFmpeg desde https://ffmpeg.org/download.html y Ollama desde https://ollama.com/download
goto tools_ready

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
