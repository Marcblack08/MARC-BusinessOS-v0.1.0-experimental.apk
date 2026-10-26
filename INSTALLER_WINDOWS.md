# Instalación de MARC Video Studio AI Desktop en Windows

## Qué produce el empaquetado

- Una aplicación de escritorio de Windows empaquetada con PyInstaller, sin exigir que el usuario final tenga Python instalado.
- Si está instalado Inno Setup 6, un instalador Setup.exe con asistente, desinstalación y accesos directos opcionales.
- Los proyectos y la base de datos de una instalación empaquetada se guardan en `%LOCALAPPDATA%\MARC Video Studio AI Desktop`, no en la carpeta protegida de instalación.

## Para quien compila

1. Instala Python 3.11 o 3.12 de 64 bits.
2. Ejecuta `install_windows.bat`. El script prepara el entorno, instala dependencias Python y, si Windows tiene Winget, intenta instalar FFmpeg y Ollama automáticamente.
3. Si Ollama queda disponible, el script descarga Qwen 2.5 3B para generación local de guiones. Esto requiere Internet y varios GB de espacio; puedes omitirlo si solo vas a importar guiones ya escritos.
4. El instalador ejecuta una comprobación de sintaxis y las pruebas unitarias, mostrando avisos si alguna falla.
5. Para crear el ejecutable de escritorio, instala Inno Setup 6 desde https://jrsoftware.org/isinfo.php y ejecuta `build_windows.bat`.
6. El instalador se crea en `dist-installer` si las herramientas de empaquetado están instaladas y la compilación termina correctamente.

## Requisitos del usuario final

La instalación desde el código intenta configurar automáticamente FFmpeg y Ollama mediante Winget. Si Winget no está disponible o una instalación falla, el asistente muestra las páginas oficiales. La primera descarga de Qwen necesita conexión a Internet; después, la generación de guiones puede funcionar localmente. No se descargan automáticamente checkpoints de imagen o modelos generativos de vídeo de varios GB: son opcionales, dependen del hardware y la aplicación también puede editar vídeos usando imágenes que el usuario ya tenga.

## Verificación

El instalador generado debe probarse en una cuenta limpia de Windows, verificando inicio, permisos, detección de Ollama/FFmpeg, creación de proyectos, guardado, aprobación, exportación y desinstalación. Este repositorio no incluye un instalador binario precompilado y validado.
