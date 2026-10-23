# MARC Video Studio AI Desktop

Aplicación de escritorio local para diseñar historias, generar guiones por capítulos con Ollama/Qwen, revisarlos y exportar un MP4 básico con FFmpeg.

> **Estado honesto:** las mejoras de interfaz e IA están incorporadas al código de `main`, pero esta revisión aún necesita validación en Windows. No es todavía un instalador EXE compilado. El render actual utiliza tarjetas de texto sobre fondos; aún no genera automáticamente imágenes cinematográficas ni narración de voz.

## Funcionalidad implementada en el código
- Interfaz rediseñada en azul tecnológico: azul noche, tarjetas, panel de proyectos y estados de herramientas.
- Indicador de disponibilidad de Ollama y búsqueda de FFmpeg.
- Conexión local a `http://127.0.0.1:11434/api/generate`; modelo esperado: `qwen2.5:3b`.
- Parámetros de guion independientes: género, premisa, protagonista, conflicto central, tono, narrador, desenlace, plataforma y duración.
- Plan de continuidad y generación secuencial por capítulos para que las historias largas no dependan de una sola respuesta.
- Generación en segundo plano para mantener la interfaz sensible, progreso por capítulos y cancelación entre solicitudes.
- Proyectos almacenados en SQLite. La migración añade los nuevos campos sin borrar proyectos guardados.
- La exportación exige aprobación humana. Guardar cambios en texto o parámetros invalida la aprobación anterior.
- FFmpeg se busca en PATH y en carpetas habituales de discos locales; también se permite seleccionarlo manualmente.

## Requisitos
- Windows 10/11 de 64 bits.
- Python 3.11+ con Tcl/Tk disponible.
- Ollama instalado y ejecutándose.
- Modelo local descargado: `qwen2.5:3b`.
- FFmpeg para exportar MP4.
- Equipo objetivo de desarrollo: Intel Core i5 de 4.ª generación, 16 GB RAM, SSD y NVIDIA GTX 750. Qwen puede funcionar por CPU; los guiones largos pueden tardar bastante.

## Instalación/ejecución
1. Instala Python y Ollama desde sus sitios oficiales.
2. Descarga el modelo una vez desde PowerShell:
   ```powershell
   ollama run qwen2.5:3b
   ```
   Espera a que termine la descarga. Para uso posterior, deja Ollama abierto/en ejecución.
3. Extrae FFmpeg Essentials. MARC intenta encontrar `ffmpeg.exe` en `bin`; no es obligatorio añadirlo a PATH.
4. Ejecuta `install_windows.bat`.
5. Ejecuta `start_windows.bat`.

## Flujo de trabajo
1. Define el tema y los parámetros narrativos.
2. MARC solicita a Qwen una biblia/escaleta de continuidad.
3. Qwen genera los capítulos en orden y MARC conserva un borrador local.
4. Edita la historia y pulsa **Aprobar guion**.
5. Solo entonces puedes exportar el MP4.

No se publica automáticamente en redes sociales ni se envía el contenido a una nube de IA; las solicitudes del modelo se dirigen al servicio Ollama local.

## Límites actuales
- El tamaño de las respuestas depende del modelo local. La división por capítulos mejora la continuidad, pero no garantiza exactamente el número de palabras ni la duración final.
- Cancelar una generación detiene el proceso después de que termine la solicitud actual de Ollama.
- La exportación crea tarjetas de texto con FFmpeg, sin voz, música ni imágenes generadas. El montaje avanzado y las herramientas de voz son fases posteriores.
- El código se actualiza en GitHub; para usar estas mejoras en una copia ya descargada hay que actualizar `app.py` y reiniciar la aplicación.
- El EXE y la instalación limpia aún no se han verificado en esta máquina de desarrollo.
