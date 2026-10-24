# Instalar MARC en Windows

## Requisitos principales
- Windows 10/11 de 64 bits.
- Recomendado: SSD y 16 GB de RAM. Algunos modelos visuales requieren GPU compatible y bastante memoria.
- MARC Video Studio (el programa).
- Ollama y el modelo `qwen2.5:3b` para guiones y prompts.
- FFmpeg para exportar MP4.
- ComfyUI y un checkpoint compatible para generar imágenes (opcional para abrir MARC, necesario para imágenes IA).
- Voz española de Windows para narración local; VLC de 64 bits es opcional para reproducir MP4 dentro de MARC.

**Importante:** el instalador de MARC no incluye los motores externos ni los modelos de IA. MARC aplica movimientos de cámara 2D a imágenes fijas; no genera automáticamente animación neuronal completa.

## 1. Instalar MARC
1. Abre el repositorio: https://github.com/Marcblack08/MARC-BusinessOS-v0.1.0-experimental.apk
2. En **Actions**, abre una ejecución exitosa de **Build Windows desktop installer**.
3. Descarga y extrae el artefacto `MARC-Video-Studio-Windows`.
4. Ejecuta `MARC-Video-Studio-Setup-0.2.0-x64.exe` y sigue el asistente. Los artefactos de Actions caducan; si ya no aparece, usa la ejecución más reciente.

## 2. Instalar Ollama y Qwen
1. Instala Ollama: https://ollama.com/download/windows
2. En PowerShell ejecuta `ollama run qwen2.5:3b`.
3. Espera la descarga; luego escribe `/bye` para salir del chat.
4. Comprueba con `ollama list` que aparezca `qwen2.5:3b`. MARC se conecta a `http://127.0.0.1:11434` sin clave API.

## 3. Instalar FFmpeg
1. Abre https://www.ffmpeg.org/download.html y sigue uno de los enlaces de compilaciones para Windows.
2. Extrae FFmpeg en una carpeta estable, por ejemplo `C:\Tools\ffmpeg`.
3. Localiza `bin\ffmpeg.exe`; recomendado: agrega la carpeta `bin` a `Path`.
4. Abre una consola nueva y comprueba `ffmpeg -version`. También puedes seleccionar `ffmpeg.exe` desde MARC.

## 4. Imágenes con ComfyUI
1. Sigue la guía oficial: https://docs.comfy.org/installation/comfyui_portable_windows
2. Inicia ComfyUI (normalmente `http://127.0.0.1:8188`).
3. Instala un checkpoint compatible en `ComfyUI\models\checkpoints`. Revisa licencia y requisitos de memoria/GPU.
4. En MARC pulsa **Detectar ComfyUI** y selecciona el checkpoint.
5. Revisa y aprueba el guion antes de generar imágenes. MARC prepara prompts agrupados; ComfyUI genera las imágenes una por una.
6. Si usas otro puerto, define `MARC_COMFYUI_URL` antes de iniciar MARC.

## 5. Voces y prueba completa
1. Para voz local, instala una voz española en Configuración de Windows → Hora e idioma → Voz; luego pulsa **Detectar voces** en MARC.
2. Crea un proyecto **Corto (2 minutos)**, escribe una premisa y genera el guion.
3. Revisa el gancho, diálogos, continuidad y escenas; aprueba el guion.
4. Objetivo de storyboard: al menos 24 planos para 2 minutos, con máximo previsto de 5 segundos por plano. La salida de IA debe revisarse.
5. Genera las imágenes faltantes, configura la voz, añade música/efectos con licencia y usa la vista previa.
6. Exporta el MP4 y reproduce el archivo final para verificar imagen, duración, voz, música y subtítulos.

## Diagnóstico rápido
- **No genera guion:** comprueba Ollama y `ollama list`.
- **No genera imágenes:** ComfyUI debe estar activo, con checkpoint y memoria suficiente.
- **Falla exportación:** comprueba `ffmpeg -version` o selecciona `ffmpeg.exe`.
- **No hay voz española:** instala una voz compatible de Windows.
- **El MP4 no se reproduce dentro de MARC:** instala VLC de 64 bits o ábrelo con el reproductor de Windows.

## Datos del usuario
Los proyectos empaquetados se guardan en `%LOCALAPPDATA%\MARC Video Studio AI Desktop`. No se sincronizan entre computadoras; cierra MARC antes de copiar los datos y guarda una copia de seguridad.
