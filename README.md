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
- **Puntos de recuperación de producción:** MARC guarda un registro JSON por proyecto con el estado del guion, aprobación, storyboard, imágenes, narración, audio, montaje, control de calidad y exportación. En **Más → Estado / reanudar producción** se puede consultar el estado y reintentar la primera etapa fallida compatible; las etapas previas completadas se conservan y el render sigue aprovechando la caché.\n- **Control de calidad del MP4:** tras renderizar, MARC intenta inspeccionar las pistas, resolución, FPS, duración y presencia de audio esperada mediante `ffprobe`, con alternativa de lectura de FFmpeg cuando no está disponible. Genera también un archivo SRT junto al MP4 y comprueba numeración, marcas de tiempo, orden y texto de sus subtítulos. Si una comprobación falla, el archivo se conserva pero la exportación queda marcada con alertas; revisa el resultado antes de publicarlo. La comprobación no mide inteligibilidad de voz ni sincronía fonética exacta; el SRT usa tiempos aproximados por escena.\n- **Generar imágenes faltantes:** permite generar en secuencia una ilustración local por cada escena que todavía no tenga recurso visual. Primero exige guardar y aprobar la versión actual del guion/dirección visual; así se evita generar imágenes de un borrador no revisado. Al iniciarla desde la vista previa, puede continuar automáticamente al render de revisión cuando termine el lote. Requiere ComfyUI abierto y un checkpoint seleccionado.
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
- **Importar paquete de producción en un solo flujo:** ahora hay un botón principal **Importar guion + imágenes**, además del botón dentro de Escenas. Selecciona una carpeta que contenga `guion.md/txt`, `direcciones.json/txt/md`, `imagenes/` y opcionalmente `audio/narracion.wav` y `audio/musica.mp3`. MARC copia los recursos al proyecto sin modificar el paquete original.
- **Revisión visual por escena:** la pestaña Escenas tiene una vista en dos columnas: storyboard/lista a la izquierda e imagen seleccionada, instrucciones de movimiento y diálogo a la derecha. Las herramientas para generar imágenes con ComfyUI están plegadas por defecto; se muestran con **Generación IA opcional**.
- **Asignación de recursos conservando la escena de origen:** cuando el guion se divide en varios planos de hasta 5 segundos, MARC conserva la asociación de la imagen y la dirección con la escena original. Si la carpeta tiene una imagen por plano, las asigna en orden; si hay menos imágenes que planos, las distribuye por el montaje.
- Formato recomendado para la dirección: una indicación por línea o bloques con encabezados como ESCENA 1: zoom in, ESCENA 2: paneo de izquierda a derecha. También acepta JSON con un objeto scenes o claves numéricas. Las direcciones reconocidas controlan paneo/zoom del montaje de imágenes fijas. No crean movimiento corporal real; para eso se requiere un motor de vídeo generativo compatible y un modelo adecuado.
- El montaje usa las indicaciones por escena para elegir acercamiento, alejamiento, paneo horizontal o movimiento vertical; cuando no se proporcionan, utiliza movimientos automáticos variados.
- **Storyboards largos:** admite hasta 1.440 planos (hasta 120 minutos con un límite visual de 5 segundos por plano). El render usa bloques de transición y guarda los grafos FFmpeg en archivos, evitando que las líneas de comando de Windows crezcan demasiado. Los bloques intermedios conservan el tramo extra necesario para que el fundido entre bloques no se vuelva un corte a negro.
- Integración con ComfyUI local para generar una imagen fija por escena. Los lotes preparan prompts con solicitudes agrupadas de Ollama antes de generar imágenes, reduciendo llamadas secuenciales; si falla el modelo de texto, se usa una descripción de respaldo. MARC detecta el puerto predeterminado y varios puertos alternativos, muestra la URL conectada y diferencia un servicio apagado de la ausencia de checkpoints. El botón **Iniciar / instalar** intenta abrir una instalación portable conocida o lleva a la guía oficial de ComfyUI para Windows. Ollama/Qwen se usa para texto; no genera imágenes por sí solo. El endpoint se puede fijar con `MARC_COMFYUI_URL` y la carpeta portable con `MARC_COMFYUI_DIR`.
- Render MP4 en segundo plano, con barra de progreso y cancelación. Las escenas terminadas se guardan como puntos de recuperación y se reutilizan si el contenido, la duración, la imagen o la resolución no han cambiado. El progreso informa de bloques aproximados de 5 minutos. Los perfiles exigentes pueden tardar considerablemente en equipos antiguos; MARC avisa antes de exportar y respeta la resolución elegida. Imágenes asignadas reciben movimiento sencillo de cámara; las escenas sin imágenes se renderizan como tarjetas de texto.
- Pestaña de audio con pistas separadas de narración y música; generación de voz offline con Windows System.Speech, mezcla de ambas pistas con volumen de música reducido y repetición opcional de la música. Incluye la acción «Añadir audio al último vídeo» para aplicar narración y/o música a un MP4 ya exportado sin volver a renderizar las escenas.
- Aprobación humana obligatoria antes de exportar; modificar el guion invalida la aprobación.
- Búsqueda y selección manual de FFmpeg.
- Instalador de un solo paso para dependencias de Python, detección de Winget, intento de instalación automática de FFmpeg y Ollama, descarga del modelo gratuito Qwen 2.5 3B cuando Ollama queda disponible, comprobación de sintaxis y ejecución de pruebas unitarias. La instalación de modelos de imagen/vídeo pesados permanece opcional para no llenar el disco ni dejar sin memoria los equipos sin GPU.
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

## Instalación en un PC Windows nuevo

Consulta [docs/INSTALACION_WINDOWS.md](docs/INSTALACION_WINDOWS.md) para requisitos, enlaces oficiales, Ollama/Qwen, FFmpeg, ComfyUI opcional y una prueba completa del primer vídeo. El instalador de MARC no incluye esos motores externos.

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

## Interfaz minimalista: crea un vídeo en tres pasos

Al abrir MARC aparece primero **Creador fácil**. El editor avanzado sigue disponible desde **Editor avanzado**.

1. **Proyecto:** escribe el nombre del vídeo, pega el guion completo y selecciona tus imágenes (o importa una carpeta).
2. **Animación y voces:** elige **Básico** para zoom/paneo, **Movimiento IA** para animación corporal cuando el motor local sea compatible, o **Cinemático IA** para el mismo motor de movimiento con un montaje más marcado. Abre **Catálogo de voces** para ver las voces locales de Windows y Kokoro, escuchar una muestra, seleccionar una voz o abrir las opciones de instalación.
3. **Crear vídeo:** MARC analiza el equipo, prepara solo los motores que hacen falta, genera los clips si es viable, crea o reutiliza el audio y monta el MP4.

El creador alinea las escenas visuales con el número de imágenes. La pista de voz se sintetiza a partir del guion original, sin reemplazar sus diálogos por los encabezados de escena creados para el montaje. Si no hay un modelo de vídeo compatible, MARC ofrece el modo Básico de forma explícita; no lo presenta como animación corporal real. El catálogo muestra las voces que realmente están instaladas o conectadas: **no descarga voces desconocidas de forma silenciosa**.

## Producción automática: guion + imágenes → clips animados → MP4

La pestaña **Escenas** añade tres acciones: **Preparar IA / Diagnóstico**, **Producción automática** y **Animar imagen a vídeo IA**. El nuevo modo de producción usa los recursos que ya tengas y evita obligarte a configurar manualmente cada motor.

### Flujo de un clic
1. Organiza una carpeta con **guion.md**, imágenes numeradas en **imagenes/** y, opcionalmente, **direcciones.json**, **audio/narracion.wav** y **audio/musica.mp3**.
2. Pulsa **Producción automática** y selecciona esa carpeta.
3. MARC revisa los componentes instalados, detecta CPU/RAM/GPU/espacio en disco e instala o inicia las dependencias que falten.
4. Si el equipo reúne los requisitos y el motor de vídeo queda listo, MARC analiza cada imagen con un modelo visual local de Ollama, utiliza el contexto de la escena para definir el movimiento y genera clips con LTX-Video a través de ComfyUI.
5. MARC conecta los clips generados con las escenas, sintetiza la narración con las voces locales de Windows cuando no hayas importado voz, incorpora música importada o crea una pista ambiental instrumental local, monta el MP4 con FFmpeg y guarda la exportación en **projects/<id>/exports/**.
6. Los clips por imagen se conservan en **projects/<id>/generated_video/**. El montaje final se guarda en las exportaciones del proyecto.

### Qué instala y qué no
- **FFmpeg**: montaje, transiciones, mezcla de sonido, subtítulos y MP4.
- **Ollama + Qwen 2.5 3B**: guiones locales, si faltan y se pueden descargar.
- **Ollama + moondream**: análisis visual automático local, si faltan y hay espacio de disco.
- **ComfyUI Portable + LTX-Video + codificador T5**: solo se descargan automáticamente cuando la máquina cumple el perfil conservador: Windows, GPU NVIDIA compatible con al menos 8 GB de VRAM, 24 GB de RAM y 30 GB libres. La descarga de modelos de vídeo puede sumar unos 15 GB, además de ComfyUI.
- La preparación no solicita elevación de administrador silenciosa, no borra proyectos y guarda el diagnóstico en %LOCALAPPDATA%/MARC Video Studio AI Desktop/setup_report.json.

### Limitación importante en equipos sin GPU
Si el equipo no cumple el perfil, MARC no descarga varios gigabytes de modelos que probablemente no podrá ejecutar. Ofrece continuar con el montaje convencional usando movimiento de cámara, voz y música, pero lo identifica como modo alternativo, **no como movimiento corporal real**. Para la animación neuronal local se necesita un equipo compatible o elegir, por separado, un servicio de vídeo externo; los servicios alojados pueden requerir cuenta, créditos o pago.

### Flujo manual de una imagen
**Animar imagen a vídeo IA** permite elegir una imagen y describir el movimiento, o escribir **AUTO** para el análisis visual. La plantilla LTX oficial se prepara automáticamente; no tienes que exportar un workflow API manualmente. La generación puede tardar y produce clips cortos, que el montaje adapta a la duración de cada plano.

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


## Acceso remoto desde el teléfono

La versión con panel remoto inicia un pequeño servidor web dentro de MARC, ligado únicamente a `127.0.0.1:8765`. En el menú **Más → Acceso remoto desde el teléfono**, MARC muestra el código privado y las instrucciones para conectar el navegador del teléfono.

1. Abre MARC en la computadora y deja la aplicación en ejecución.
2. En CMD o PowerShell de Windows, ejecuta `tailscale serve --bg 8765`. Usa **Serve**, no Funnel: el panel debe permanecer privado dentro de tu red Tailscale.
3. Copia la dirección HTTPS que Tailscale muestre y ábrela en el navegador del teléfono, con Tailscale conectado.
4. Introduce el código que MARC muestra en **Acceso remoto desde el teléfono**.

El panel permite crear guiones en Ollama local, revisar y guardar guiones, aprobarlos, solicitar lotes de imágenes mediante ComfyUI, exportar MP4, cancelar trabajos, subir recursos al proyecto y descargar archivos. Los MP4 solicitados desde el teléfono se guardan en la carpeta `projects/<id>/exports` para que el panel los ofrezca como descarga.

**Requisitos y seguridad:** la computadora debe permanecer encendida, conectada a Internet y con MARC abierto; Ollama y ComfyUI se ejecutan en la computadora. El servidor no se publica directamente en la LAN ni en Internet; Tailscale Serve lo expone solo dentro del tailnet. No ejecutes `tailscale funnel` ni compartas el código de acceso. Los archivos subidos se guardan en `projects/<id>/uploads`; para asignar una imagen a una escena, abre el proyecto en MARC y selecciónala desde los controles de escenas. La carga y descarga remotas deben probarse con el instalador de Windows antes de utilizar el flujo en producción.

## Paquete de producción en una carpeta (nueva ruta recomendada)

Puedes entregar al editor una carpeta con el guion, las indicaciones por escena, las imágenes y, si ya existen, una pista de narración y una pista musical. En MARC, ve a **Escenas → Importar paquete (guion + dirección + imágenes)** y selecciona la carpeta completa. El programa detecta los recursos, los copia al proyecto y conecta narración/música con nombres convencionales.

Ejemplo: `MiVideo/guion.md`, `MiVideo/direcciones.json`, `MiVideo/imagenes/001.png`, y opcionalmente `MiVideo/audio/narracion.wav` y `MiVideo/audio/musica.mp3`. Consulta [la guía del paquete de producción](docs/PAQUETE_PRODUCCION.md) y la [plantilla de ejemplo](templates/paquete-produccion/).

El instalador desde el código ahora intenta instalar Python 3.12 automáticamente con Winget si no hay una versión compatible, conserva el entorno virtual anterior si detecta que se creó con una versión incompatible, registra el hardware en `%LOCALAPPDATA%\MARC Video Studio AI Desktop\hardware-profile.json` y guarda las pruebas de instalación en `installation-tests.log`. No descarga modelos visuales grandes por defecto: si importas tus propias imágenes, el montaje funciona sin ComfyUI; los modelos de imagen/vídeo son opcionales y dependen del hardware.


El flujo de paquete admite ahora un inicio de producción de un solo clic adicional: tras elegir la carpeta con guion, direcciones e imágenes, puedes autorizar el montaje final. MARC utilizará la voz local de Windows si no importaste narración y guardará el MP4 automáticamente en las exportaciones del proyecto; si quieres revisar primero el guion, elige no iniciar todavía.
