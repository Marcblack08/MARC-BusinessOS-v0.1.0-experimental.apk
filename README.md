# MARC Video Studio AI Desktop

Aplicación de escritorio local para desarrollar historias con Ollama/Qwen, organizar escenas, asignar o generar ilustraciones localmente y exportar MP4 con FFmpeg.

## Estado real del proyecto
El código fuente está en desarrollo. La validación automatizada comprueba la sintaxis de Python y pruebas unitarias de las funciones de escenas. La ejecución completa de la interfaz, la generación con Ollama/ComfyUI, el render y la instalación requieren una prueba real en Windows antes de considerar una versión estable. No se distribuye todavía un instalador binario probado dentro del repositorio.

## Funciones presentes en el código
- Interfaz de edición oscura inspirada en Premiere, maximizada, con biblioteca y paneles redimensionables.
- Pestañas **Guion**, **Escenas**, **Montaje**, **Vista previa** y **Audio**.
- Timeline multipista visual con clips por escena, pistas de narración/música, bloques de subtítulos aproximados, cabezal navegable, zoom y selección sincronizada con la lista de escenas.
- Edición básica de montaje: mover el clip seleccionado una posición a izquierda/derecha, editar la duración de cada escena (5–3600 segundos) y conservar duraciones e imágenes asignadas en los recursos del proyecto. Estos cambios invalidan la aprobación del guion y requieren volver a aprobar antes de exportar.
- El monitor todavía no reproduce el montaje en tiempo real; el cabezal sirve para navegar y seleccionar escenas.
- Género, premisa, protagonistas, conflicto, tono, narrador, desenlace, plataforma, duración, estilo de dibujo y animación.
- Generación de historias en capítulos de aproximadamente 5 minutos con Ollama/Qwen 2.5 3B local, en segundo plano y con cancelación entre solicitudes. Los proyectos admiten de 1 a 120 minutos; los guiones largos se dividen en partes para reducir solicitudes enormes.
- Detección del equipo y estimación inicial de tiempos.
- Persistencia local en SQLite con migraciones para bases existentes.
- Tabla de escenas con título, palabras, duración asignada y recurso visual.
- Asignación de imágenes propias a las escenas.
- Integración opcional con ComfyUI local en `http://127.0.0.1:8188` para generar una imagen fija por escena.
- Render MP4 en segundo plano, con barra de progreso y cancelación. Las escenas terminadas se guardan como puntos de recuperación y se reutilizan si el contenido, la duración, la imagen o la resolución no han cambiado. El progreso informa de bloques aproximados de 5 minutos. En equipos con 4 hilos lógicos o menos de 8 GB de RAM, se activa un perfil de render de menor resolución para reducir la carga. Imágenes asignadas reciben movimiento sencillo de cámara; las escenas sin imágenes se renderizan como tarjetas de texto.
- Pestaña de audio con pistas separadas de narración y música; generación de voz offline con Windows System.Speech, mezcla de ambas pistas con volumen de música reducido y repetición opcional de la música.
- Aprobación humana obligatoria antes de exportar; modificar el guion invalida la aprobación.
- Búsqueda y selección manual de FFmpeg.
- Script local de instalación de dependencias y constructor de app/instalador.

## Requisitos
- Vídeos de 1 a 120 minutos por proyecto, generados por capítulos de aproximadamente 5 minutos. El tiempo total depende del hardware; la generación de imágenes locales puede ser especialmente lenta en GPU antiguas.
- Windows 10/11 de 64 bits.
- Python 3.11+ para ejecución desde el código fuente.
- Ollama y el modelo local `qwen2.5:3b` para generar guiones.
- FFmpeg para exportar MP4.
- Opcional: ComfyUI local y un checkpoint compatible para generación de imágenes.
- Equipo objetivo: Intel Core i5 de 4.ª generación, 16 GB RAM, SSD y NVIDIA GTX 750. Las historias largas tardarán más; la GTX 750 tiene recursos limitados para modelos de imagen modernos.

## Instalación desde el código
1. Descarga o clona el repositorio.
2. Ejecuta `install_windows.bat` para detectar Python y preparar `.venv`.
3. Ejecuta `start_windows.bat`.
4. Instala Ollama por separado y descarga el modelo una vez con `ollama run qwen2.5:3b`.
5. Instala FFmpeg por separado. MARC intenta detectarlo automáticamente y también permite seleccionar `ffmpeg.exe`.

## Construir la aplicación de Windows
**En tu PC de desarrollo:**
1. Ejecuta `install_windows.bat`.
2. Ejecuta `build_windows.bat` para ejecutar las validaciones, compilar la aplicación con PyInstaller y, si está instalado Inno Setup 6, producir `Setup.exe`.
3. Prueba el programa y la instalación en un Windows limpio antes de distribuirlos.

**Desde GitHub Actions:** entra en Actions → **Build Windows desktop installer** → **Run workflow**. Si la ejecución termina correctamente, descarga el artefacto `MARC-Video-Studio-Windows` desde esa ejecución. El artefacto incluye el instalador y la carpeta de aplicación portable. Las validaciones incluyen pruebas reales de FFmpeg para el montaje con voz y música, además de pruebas unitarias. Aun así, el programa completo debe probarse con Ollama/ComfyUI y con las voces disponibles en el PC objetivo antes de distribuirlo a usuarios finales.

Ollama, sus modelos, ComfyUI/checkpoints y FFmpeg no se incluyen en el instalador; se instalan por separado. En la versión empaquetada, los proyectos y la base de datos se guardan en `%LOCALAPPDATA%\\MARC Video Studio AI Desktop`.

## Flujo de trabajo
1. Configura la premisa, género y duración.
2. Genera el guion con la IA local.
3. Revisa el guion y las escenas; importa imágenes o genera ilustraciones con ComfyUI si está instalado.
4. Opcionalmente, añade una pista de narración/música local.
5. Exporta subtítulos SRT si los necesitas y revisa su sincronización.
6. Aprueba el guion.
7. Exporta MP4 y abre el resultado desde la pestaña **Vista previa**.

## Límites importantes
- La integración de ComfyUI genera **imágenes fijas**, no vídeo neuronal completo. El render aplica movimiento de cámara sencillo a imágenes y tarjetas tipográficas donde no haya recursos.
- La voz local usa las voces SAPI que tenga Windows instaladas; puede necesitar que instales una voz española desde la configuración de idioma/voz. No es una voz neuronal de alta calidad y el resultado varía según la voz disponible. La música de fondo se mezcla a menor volumen que la narración; revisa el balance auditivo antes de publicar.
- La estimación de tiempo es orientativa; ComfyUI depende mucho del checkpoint y del hardware y puede tardar mucho o no funcionar en GPUs antiguas.
- La vista previa abre el archivo MP4 en el reproductor predeterminado del sistema, no dentro de una superficie de reproducción integrada.
- La validación de CI no sustituye las pruebas del programa gráfico, generación local y exportación sobre el PC real.
