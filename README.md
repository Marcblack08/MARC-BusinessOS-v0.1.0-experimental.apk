# MARC Video Studio AI Desktop

Aplicación de escritorio local para desarrollar historias con Ollama/Qwen, organizar escenas, asignar o generar ilustraciones localmente y exportar MP4 con FFmpeg.

## Estado real del proyecto
El código fuente está en desarrollo. La validación automatizada comprueba la sintaxis de Python y pruebas unitarias de las funciones de escenas. La ejecución completa de la interfaz, la generación con Ollama/ComfyUI, el render y la instalación requieren una prueba real en Windows antes de considerar una versión estable. No se distribuye todavía un instalador binario probado dentro del repositorio.

## Funciones presentes en el código
- Interfaz de estudio más limpia: el editor de guion ocupa el espacio principal al iniciar; la biblioteca de proyectos y la configuración de historia se abren solo cuando se necesitan.
- Barra principal reducida a Nuevo, Ajustes, Generar guion, Guardar, Aprobar guion, Vista previa y Exportar MP4. Las herramientas secundarias están agrupadas en el menú **Más**.
- El monitor de trabajo y el resumen de timeline ya no duplican el contenido de la pantalla principal; el monitor completo está en **Vista previa** y la línea de tiempo de edición en **Montaje**.
- Configuración separada por áreas: datos narrativos en Ajustes; estilo de ilustración, resolución y FPS en **Visual / salida**; recursos por escena en **Escenas**; narración, música y subtítulos en **Audio**.
- La interfaz utiliza espacios más compactos, etiquetas más breves y paneles secundarios plegables para dedicar más espacio al guion y a las escenas.
- Pestañas **Guion**, **Escenas**, **Visual / salida**, **Montaje**, **Vista previa** y **Audio**.
- Timeline multipista visual con clips por escena, pistas de narración/música, bloques de subtítulos aproximados, cabezal navegable, zoom y selección sincronizada con la lista de escenas.
- Edición básica de montaje: mover el clip seleccionado una posición a izquierda/derecha, editar la duración de cada escena (5–3600 segundos) y conservar duraciones e imágenes asignadas en los recursos del proyecto. Estos cambios invalidan la aprobación del guion y requieren volver a aprobar antes de exportar.
- El monitor permite reproducir un MP4 dentro de MARC mediante el motor VLC cuando VLC Media Player está instalado. Incluye reproducción, pausa, detención y búsqueda; si el motor local no está disponible, ofrece abrir el MP4 en el reproductor externo. La miniatura/storyboard sigue visible en la pestaña Vista previa.
- **Vista previa MP4 antes de exportar:** renderiza el montaje actual en un archivo temporal de revisión (720p, hasta 24 FPS) y lo abre dentro de MARC; no exige haber aprobado el guion. La vista previa registra los ajustes y recursos usados y avisa si después cambias el montaje. La exportación final sigue siendo una operación separada y exige aprobación.
- **Generar imágenes faltantes:** permite generar en secuencia una ilustración local por cada escena que todavía no tenga recurso visual. Primero exige guardar y aprobar la versión actual del guion/dirección visual; así se evita generar imágenes de un borrador no revisado. Al iniciarla desde la vista previa, puede continuar automáticamente al render de revisión cuando termine el lote. Requiere ComfyUI abierto y un checkpoint seleccionado.
- Género, premisa, protagonistas, conflicto, tono, narrador, desenlace, plataforma, duración, estilo de dibujo y animación.
- Modos de producción **Corto (2 minutos)** y **Novela / Serie**. El modo corto fija un objetivo de 2 minutos y ajusta la cantidad de texto; la duración real depende de la voz, las pausas y el ritmo.
- Perfil de salida por proyecto: **720p HD, 1080p Full HD o 2K/1440p**, formatos horizontal 16:9, vertical 9:16 y cuadrado 1:1, y 24/25/30/60 FPS. La aplicación muestra una advertencia para perfiles exigentes y no reduce silenciosamente la resolución elegida.
- Biblia narrativa y continuidad por proyecto: personajes, relaciones, escenarios, canon, estado del episodio y tramas pendientes se guardan en SQLite. La acción **Continuar historia** crea un episodio vinculado que reutiliza la biblia y el estado más reciente. En **Visual / salida → Biblia de la historia y continuidad** se pueden revisar y corregir manualmente el canon y el cierre del episodio.
- Guiones con gancho dramático y etiquetas de hablante como `[NARRADOR]:` y `[JUAN]:`; el texto se organiza por escena para permitir voces distintas sin convertir cada línea hablada en un clip visual independiente.
- Asignación de voces por personaje a las voces SAPI que estén instaladas en Windows. Si hay varias voces disponibles, MARC intenta asignar voces alternativas a los personajes etiquetados y mantener la voz principal para el narrador, respetando las asignaciones manuales existentes. Para diferenciar voces el guion debe incluir etiquetas como `[NARRADOR]:`, `[LUCÍA]:` y `[MARIO]:`, y Windows debe tener al menos dos voces instaladas; con una sola voz disponible no puede crear timbres distintos.
- Revisión narrativa preventiva antes de aprobar: avisa de algunos posibles inicios genéricos o borradores cortos. Son heurísticas y no sustituyen una revisión humana ni prueban por sí solas la ausencia de contradicciones.
- Generación de historias en capítulos de aproximadamente 5 minutos con Ollama/Qwen 2.5 3B local, en segundo plano y con cancelación entre solicitudes. Los proyectos admiten de 1 a 120 minutos; los guiones largos se dividen en partes para reducir solicitudes enormes.
- Detección del equipo y estimación inicial de tiempos.
- Persistencia local en SQLite con migraciones para bases existentes.
- Tabla de escenas con título, palabras, duración asignada y recurso visual.
- Asignación de imágenes propias a las escenas.
- Integración con ComfyUI local para generar una imagen fija por escena. MARC detecta el puerto predeterminado y varios puertos alternativos, muestra la URL conectada y diferencia un servicio apagado de la ausencia de checkpoints. El botón **Iniciar / instalar** intenta abrir una instalación portable conocida o lleva a la guía oficial de ComfyUI para Windows. Ollama/Qwen se usa para texto; no genera imágenes por sí solo. El endpoint se puede fijar con `MARC_COMFYUI_URL` y la carpeta portable con `MARC_COMFYUI_DIR`.
- Render MP4 en segundo plano, con barra de progreso y cancelación. Las escenas terminadas se guardan como puntos de recuperación y se reutilizan si el contenido, la duración, la imagen o la resolución no han cambiado. El progreso informa de bloques aproximados de 5 minutos. Los perfiles exigentes pueden tardar considerablemente en equipos antiguos; MARC avisa antes de exportar y respeta la resolución elegida. Imágenes asignadas reciben movimiento sencillo de cámara; las escenas sin imágenes se renderizan como tarjetas de texto.
- Pestaña de audio con pistas separadas de narración y música; generación de voz offline con Windows System.Speech, mezcla de ambas pistas con volumen de música reducido y repetición opcional de la música. Incluye la acción «Añadir audio al último vídeo» para aplicar narración y/o música a un MP4 ya exportado sin volver a renderizar las escenas.
- Aprobación humana obligatoria antes de exportar; modificar el guion invalida la aprobación.
- Búsqueda y selección manual de FFmpeg.
- Script local de instalación de dependencias y constructor de app/instalador.

## Requisitos
- Vídeos de 1 a 120 minutos por proyecto, generados por capítulos de aproximadamente 5 minutos. El tiempo total depende del hardware; la generación de imágenes locales puede ser especialmente lenta en GPU antiguas.
- Windows 10/11 de 64 bits. Para la reproducción de MP4 integrada, instalar VLC Media Player de 64 bits; si no está instalado, MARC permite abrir el vídeo en el reproductor del sistema.
- Python 3.11+ para ejecución desde el código fuente.
- Ollama y el modelo local `qwen2.5:3b` para generar guiones.
- FFmpeg para exportar MP4.
- Opcional: ComfyUI local y un checkpoint compatible para generación de imágenes.

### Diagnóstico de imágenes
1. Abre ComfyUI y espera a que su interfaz/API esté lista. El puerto habitual es `8188`; MARC también comprueba algunos puertos alternativos.
2. En **Escenas**, pulsa **Detectar ComfyUI** y selecciona un checkpoint disponible.
3. Si MARC indica que Ollama responde pero no encuentra ComfyUI, la generación de guiones está operativa, pero falta iniciar/configurar el motor de imágenes. Instala o inicia ComfyUI y coloca un checkpoint compatible en su carpeta de modelos antes de volver a detectar.
4. Para una instancia en otra dirección, define `MARC_COMFYUI_URL` (por ejemplo `http://127.0.0.1:8189`) en el entorno desde el que abres MARC.

La detección de servicios no instala ComfyUI ni descarga checkpoints automáticamente; esos componentes requieren instalación y espacio/recursos locales.
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
3. Revisa el guion y las escenas; importa imágenes, o selecciona un checkpoint en ComfyUI y usa **Generar imágenes faltantes**.
4. Configura las voces: asegúrate de tener varias voces de Windows instaladas y etiquetas de hablante en el guion para distinguir personajes. Opcionalmente, añade música de fondo.
5. Pulsa **Vista previa MP4** para crear y reproducir el montaje dentro de MARC antes de exportar. Corrige el guion, imágenes, duraciones o asignaciones de voz si hace falta; vuelve a generar la vista previa tras cualquier cambio.
6. Exporta subtítulos SRT si los necesitas y revisa su sincronización.
7. Aprueba el guion y pulsa **Exportar MP4** para producir el archivo final.

## Límites importantes
- La integración de ComfyUI genera **imágenes fijas**, no vídeo neuronal completo. Los prompts de ilustración incluyen referencias de la biblia narrativa para ayudar a mantener la apariencia y los escenarios; el modelo local no puede garantizar identidad visual perfecta. El render aplica movimiento de cámara sencillo a imágenes y tarjetas tipográficas donde no haya recursos. La vista previa permite comprobar este montaje antes de la exportación definitiva, pero no convierte por sí sola imágenes fijas en animación completa de personajes.
- La voz local usa las voces SAPI que tenga Windows instaladas; puede necesitar que instales una voz española desde la configuración de idioma/voz. No es una voz neuronal de alta calidad y el resultado varía según la voz disponible. Las voces por personaje requieren que el guion tenga etiquetas de hablante y que estén instaladas las voces elegidas. La música de fondo se mezcla a menor volumen que la narración; revisa el balance auditivo antes de publicar.
- La biblia narrativa es memoria estructurada basada en el contenido generado y guardado; no garantiza continuidad perfecta. La IA puede cometer errores, así que revisa nombres, cronología y hechos antes de aprobar cada episodio.
- El perfil 2K/1440p a 60 FPS puede ser lento en equipos antiguos. Seleccionar 2K no mejora las imágenes de origen, no genera ilustraciones por sí solo y no convierte imágenes fijas en vídeo neuronal.
- La estimación de tiempo es orientativa; ComfyUI depende mucho del checkpoint y del hardware y puede tardar mucho o no funcionar en GPUs antiguas.
- La reproducción integrada utiliza VLC Media Player instalado en el equipo junto con el envoltorio `python-vlc` incluido en el paquete. Si libVLC no está disponible, MARC ofrece abrir el MP4 en el reproductor externo del sistema. La vista de storyboard sigue siendo distinta del reproductor de vídeo.
- La validación de CI no sustituye las pruebas del programa gráfico, generación local y exportación sobre el PC real.
