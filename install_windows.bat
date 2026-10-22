@echo off
setlocal
cd /d "%~dp0"
echo ================================================
echo MARC Video Studio AI Desktop - preparacion local
echo ================================================
where python >nul 2>nul
if errorlevel 1 (
  echo No se encontro Python. Instala Python 3.11+ desde python.org y activa Add Python to PATH.
  pause
  exit /b 1
)
python --version
python -m venv .venv
if errorlevel 1 goto error
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto error
python -m pip install -r requirements.txt
if errorlevel 1 goto error
echo.
echo Preparacion terminada. Ejecuta start_windows.bat.
pause
exit /b 0
:error
echo Ocurrio un error durante la preparacion.
pause
exit /b 1
