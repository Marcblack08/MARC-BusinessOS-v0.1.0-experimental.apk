# Instalación de MARC Video Studio AI Desktop en Windows

## Qué produce el empaquetado

- Una aplicación de escritorio de Windows empaquetada con PyInstaller, sin exigir que el usuario final tenga Python instalado.
- Si está instalado Inno Setup 6, un instalador Setup.exe con asistente, desinstalación y accesos directos opcionales.
- Los proyectos y la base de datos de una instalación empaquetada se guardan en `%LOCALAPPDATA%\MARC Video Studio AI Desktop`, no en la carpeta protegida de instalación.

## Para quien compila

1. Instala Python 3.11 o 3.12 de 64 bits.
2. Instala Ollama si quieres generación de guiones local y descarga el modelo Qwen 2.5 3B por separado.
3. Instala FFmpeg y verifica que `ffmpeg -version` funcione, o prepara su ejecutable para la aplicación.
4. Ejecuta `install_windows.bat`.
5. Instala Inno Setup 6 desde https://jrsoftware.org/isinfo.php.
6. Ejecuta `build_windows.bat`.
7. El instalador se crea en `dist-installer` si ambas compilaciones terminan correctamente.

## Requisitos del usuario final

La aplicación de escritorio no incorpora Ollama/Qwen ni FFmpeg automáticamente. Esos componentes deben instalarse por separado para las funciones de IA local y exportación MP4. La primera descarga del modelo necesita conexión a internet; después, la inferencia de texto puede funcionar localmente.

## Verificación

El instalador generado debe probarse en una cuenta limpia de Windows, verificando inicio, permisos, detección de Ollama/FFmpeg, creación de proyectos, guardado, aprobación, exportación y desinstalación. Este repositorio no incluye un instalador binario precompilado y validado.
