@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MARC Studio - Crear aplicacion e instalador
color 0B
echo ============================================================
echo MARC VIDEO STUDIO AI DESKTOP
echo Empaquetado de escritorio e instalador de Windows
echo ============================================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Ejecuta primero install_windows.bat
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller
if errorlevel 1 goto error
echo [1/4] Validando sintaxis y pruebas... 
".venv\Scripts\python.exe" -m py_compile app.py marc_launcher.py video_generation_engine.py scene_engine.py story_engine.py voice_engine.py production_pipeline.py production_package.py media_quality.py remote_server.py ollama_client.py tests\test_video_generation_engine.py tests\test_production_package.py tests\test_scene_engine.py tests\test_story_engine.py tests\test_ffmpeg_smoke.py
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto error
echo [2/4] Limpiando compilacion anterior...
if exist build rmdir /s /q build
if exist "dist\MARC Video Studio AI Desktop" rmdir /s /q "dist\MARC Video Studio AI Desktop"
echo [3/4] Construyendo aplicacion de escritorio...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --hidden-import vlc --hidden-import video_generation_engine --name "MARC Video Studio AI Desktop" marc_launcher.py
if errorlevel 1 goto error
echo.
echo [OK] Aplicacion empaquetada en:
echo %CD%\dist\MARC Video Studio AI Desktop
echo.
where ISCC.exe >nul 2>nul
if errorlevel 1 (
  if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
    set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    goto compile_installer
  )
  if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" (
    set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
    goto compile_installer
  )
  echo [AVISO] Inno Setup 6 no esta instalado. La app esta empaquetada,
  echo pero aun no se ha creado el instalador Setup.exe.
  echo Instala Inno Setup 6 desde https://jrsoftware.org/isinfo.php
  echo y vuelve a ejecutar build_windows.bat.
  pause
  exit /b 0
) else (
  set "ISCC=ISCC.exe"
)
:compile_installer
echo [4/4] Creando instalador de Windows...
if not exist dist-installer mkdir dist-installer
"%ISCC%" "%CD%\installer\MARC-Video-Studio.iss"
if errorlevel 1 goto error
echo.
echo [OK] Instalador generado en dist-installer.
echo Prueba el instalador en Windows antes de distribuirlo.
pause
exit /b 0
:error
echo.
echo [ERROR] La compilacion fallo. Copia el mensaje anterior.
pause
exit /b 1
