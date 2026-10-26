@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title MARC Studio - Instalacion automatica
color 0B
echo ============================================================
echo   MARC VIDEO STUDIO AI DESKTOP
echo   Instalacion automatica ^| sin claves API
echo ============================================================
echo.
echo [1/7] Buscando Python compatible (3.11 - 3.14)...
call :detect_python
if defined PYEXE goto python_found

echo [AUTO] No se encontro Python compatible. Intentando instalar Python 3.12 con Winget...
where winget >nul 2>nul
if errorlevel 1 goto python_missing
winget install --id Python.Python.3.12 --exact --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 echo [AVISO] Winget no pudo instalar Python automaticamente; intentare detectar las versiones disponibles.
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%LOCALAPPDATA%\Programs\Python\Launcher;%PATH%"
call :detect_python
if defined PYEXE goto python_found

:python_missing
echo.
echo [ERROR] No se encontro una version de Python compatible.
echo Descarga Python 3.12 de 64 bits desde https://www.python.org/downloads/release/python-31210/
echo Si Winget esta disponible, vuelve a ejecutar este instalador despues de cerrar esta ventana.
pause
exit /b 1

:python_found
echo [OK] Interprete seleccionado:
if "%PYEXE%"=="py" (
  %PYEXE% %PYARGS% --version
) else (
  "%PYEXE%" --version
)
echo.

echo [2/7] Comprobando entorno virtual...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,15) else 1)" >nul 2>nul
  if errorlevel 1 (
    echo [AVISO] El entorno .venv existente usa una version incompatible de Python.
    set "VENV_BACKUP=.venv_backup"
    if exist ".venv_backup" set "VENV_BACKUP=.venv_backup_!RANDOM!"
    ren ".venv" "!VENV_BACKUP!"
    if errorlevel 1 (
      echo [ERROR] No se pudo apartar el entorno anterior. No se borro ningun proyecto.
      pause
      exit /b 1
    )
    echo [OK] Entorno anterior conservado como %VENV_BACKUP%.
  )
)
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

echo.
echo [3/7] Actualizando herramientas de instalacion...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto dependency_error

echo.
echo [4/7] Instalando dependencias de MARC...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto dependency_error

echo.
echo [5/7] Detectando hardware y perfil seguro...
set "MARC_DATA=%LOCALAPPDATA%\MARC Video Studio AI Desktop"
if not defined LOCALAPPDATA set "MARC_DATA=%USERPROFILE%\MARC Video Studio AI Desktop"
if not exist "%MARC_DATA%" mkdir "%MARC_DATA%" >nul 2>nul
if exist "%~dp0scripts\detect_hardware.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\detect_hardware.ps1" -OutputPath "%MARC_DATA%\hardware-profile.json"
  if errorlevel 1 echo [AVISO] No se pudo guardar el perfil del equipo; MARC puede detectar el hardware al abrir.
) else (
  echo [AVISO] Falta scripts\detect_hardware.ps1. Se continuara con el modo seguro.
)

echo.
echo [6/7] Instalando herramientas gratuitas de montaje y guion...
where winget >nul 2>nul
if errorlevel 1 goto manual_tools

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [AUTO] Instalando FFmpeg para exportar MP4...
  winget install --id Gyan.FFmpeg.Shared --exact --silent --accept-package-agreements --accept-source-agreements
  if errorlevel 1 echo [AVISO] No se pudo instalar FFmpeg con Winget; MARC seguira permitiendo seleccionar ffmpeg.exe.
)

where ollama >nul 2>nul
if errorlevel 1 (
  echo [AUTO] Instalando Ollama para generar texto local sin pagar una API...
  winget install --id Ollama.Ollama --exact --silent --accept-package-agreements --accept-source-agreements
  if errorlevel 1 echo [AVISO] No se pudo instalar Ollama con Winget. La importacion y el montaje siguen disponibles.
)

rem Refresh common per-user paths for tools installed during this session.
if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links" set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
if exist "%LOCALAPPDATA%\Programs\Ollama" set "PATH=%LOCALAPPDATA%\Programs\Ollama;%PATH%"
if exist "C:\Program Files\FFmpeg\bin" set "PATH=C:\Program Files\FFmpeg\bin;%PATH%"

goto tools_ready

:manual_tools
echo [AVISO] Winget no esta disponible; se omitira la instalacion automatica de herramientas externas.
echo Instaladores oficiales: FFmpeg https://ffmpeg.org/download.html ^| Ollama https://ollama.com/download

:tools_ready
echo.
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [AVISO] FFmpeg no aparece en PATH. MARC puede buscarlo o permitir seleccionar ffmpeg.exe.
) else (
  echo [OK] FFmpeg disponible.
)
where ollama >nul 2>nul
if errorlevel 1 (
  echo [AVISO] Ollama no se detecto. La importacion de imagenes/guion y el montaje siguen disponibles.
  goto tests
)
echo [OK] Ollama disponible.
ollama list 2>nul | findstr /I /C:"qwen2.5:3b" >nul
if not errorlevel 1 (
  echo [OK] Qwen 2.5 3B ya esta descargado; se omite otra descarga.
  goto tests
)
echo [AUTO] Descargando Qwen 2.5 3B, modelo local gratuito para guiones.
echo Esta descarga ocupa varios GB. Puedes dejar que termine; no se descargan modelos visuales pesados.
ollama pull qwen2.5:3b
if errorlevel 1 echo [AVISO] No se pudo descargar Qwen; puedes reintentar luego con: ollama pull qwen2.5:3b

:tests
echo.
echo [7/7] Validando sintaxis y pruebas...
".venv\Scripts\python.exe" -m compileall -q app.py scene_engine.py story_engine.py voice_engine.py production_pipeline.py production_package.py media_quality.py remote_server.py
if errorlevel 1 (
  echo [ERROR] La comprobacion de sintaxis detecto errores. No se abrira MARC automaticamente.
  pause
  exit /b 1
)
echo [OK] Sintaxis Python validada.
".venv\Scripts\python.exe" -m unittest discover -s tests -v > "%MARC_DATA%\installation-tests.log" 2>&1
if errorlevel 1 (
  echo [ERROR] Algunas pruebas fallaron. El registro esta en:
  echo %MARC_DATA%\installation-tests.log
  type "%MARC_DATA%\installation-tests.log"
  pause
  exit /b 1
)
findstr /C:"Ran " /C:"OK" "%MARC_DATA%\installation-tests.log"
echo [OK] Pruebas automatizadas superadas. Registro: %MARC_DATA%\installation-tests.log

echo.
echo ============================================================
echo Preparacion de MARC terminada.
echo Los recursos externos se instalan solo cuando son necesarios:
echo - FFmpeg: montaje/exportacion MP4.
echo - Ollama + Qwen: guion local opcional.
echo - Imagenes propias: no requieren modelos visuales grandes.
echo - ComfyUI y modelos de video: opcionales; no se descargan por defecto.
echo ============================================================
echo.
echo Abriendo MARC Video Studio AI...
start "" "%~dp0start_windows.bat"
pause
exit /b 0

:detect_python
set "PYEXE="
set "PYARGS="
where py >nul 2>nul
if not errorlevel 1 (
  call :try_launcher 3.12
  call :try_launcher 3.11
  call :try_launcher 3.13
  call :try_launcher 3.14
)
if defined PYEXE exit /b 0
where python >nul 2>nul
if not errorlevel 1 (
  for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
)
if defined PYEXE (
  "%PYEXE%" -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,15) else 1)" >nul 2>nul
  if errorlevel 1 set "PYEXE="
)
exit /b 0

:try_launcher
if defined PYEXE exit /b 0
py -%~1 -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,15) else 1)" >nul 2>nul
if not errorlevel 1 (
  set "PYEXE=py"
  set "PYARGS=-%~1"
)
exit /b 0

:venv_error
echo.
echo [ERROR] No se pudo crear el entorno virtual .venv.
echo Comprueba que la version de Python seleccionada incluya el modulo venv.
pause
exit /b 1

:dependency_error
echo.
echo [ERROR] No se pudieron instalar las dependencias de MARC.
echo Comprueba la conexion a Internet y revisa el mensaje anterior.
pause
exit /b 1
