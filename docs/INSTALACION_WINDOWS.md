# Instalar MARC Video Studio AI en Windows

## Instalación desde el repositorio (recomendada para el código actual)

1. Abre el [repositorio MARC Video Studio AI](https://github.com/Marcblack08/MARC-BusinessOS-v0.1.0-experimental.apk).
2. Pulsa **Code → Download ZIP** y extrae la carpeta completa en una ubicación con permisos de escritura (por ejemplo, Documentos\MARC).
3. Ejecuta `install_windows.bat`. Si falta Python compatible, el script intenta instalar Python 3.12 de 64 bits con Winget. Después prepara el entorno virtual, instala dependencias, intenta instalar FFmpeg y Ollama, descarga Qwen 2.5 3B y un modelo visual (si hay espacio), comprueba los recursos del equipo y prepara ComfyUI + LTX-Video solo si la GPU, RAM y disco cumplen los requisitos; finalmente ejecuta las validaciones/pruebas.
4. Al terminar, MARC se abre con `start_windows.bat`. Para iniciar el programa en las siguientes ocasiones, abre `start_windows.bat`.

La instalación guarda el perfil de hardware y el registro de pruebas en `%LOCALAPPDATA%\MARC Video Studio AI Desktop`. Si falla alguna prueba, el instalador muestra el error y conserva el registro para diagnosticarlo.

Si Winget no está disponible, Python, FFmpeg u Ollama podrían requerir su instalador oficial. Los enlaces se muestran en pantalla; el script no eleva permisos de administrador de forma silenciosa.

## Instalador empaquetado (alternativa)

1. En el repositorio, abre **Actions → Build Windows desktop installer**.
2. Descarga el artefacto `MARC-Video-Studio-Windows` de una ejecución exitosa.
3. Ejecuta `MARC-Video-Studio-Setup-0.4.0-x64.exe`.

El artefacto de Actions puede caducar; usa la ejecución más reciente. La aplicación empaquetada no incluye el modelo local ni los motores externos de IA.

## Qué queda preparado automáticamente

- **FFmpeg:** se instala cuando falta; permite montar, mezclar audio y exportar MP4.
- **Ollama + Qwen 2.5 3B:** modelo de guion local, si falta y se puede descargar.
- **Modelo visual Ollama:** se instala cuando falta y hay espacio; se usa para analizar la imagen en modo AUTO.
- **ComfyUI + LTX-Video:** el instalador examina el hardware. Solo instala el motor de vídeo y aproximadamente 15 GB de pesos si detecta Windows, GPU NVIDIA compatible con al menos 8 GB VRAM, 24 GB RAM y 30 GB de espacio libre. No descarga modelos de vídeo grandes en un equipo CPU-only o con recursos insuficientes.
- **Música ambiental local:** si el paquete no contiene música, MARC crea una pista instrumental ambiental sencilla sin usar una API. Si proporcionas tu propia música, conserva esa pista.
- **Voz:** usa síntesis local de Windows cuando no hay narración importada; también acepta una pista WAV existente.
- **Diagnóstico:** queda en %LOCALAPPDATA%/MARC Video Studio AI Desktop/setup_report.json. El registro de las pruebas de la instalación desde código está en installation-tests.log.

La aplicación empaquetada también ejecuta un diagnóstico de primera apertura si no encuentra un informe de instalación anterior. Puedes repetirlo desde **Escenas → Preparar IA / Diagnóstico**.

## Preparar una producción en una carpeta

Consulta [Paquete de producción](PAQUETE_PRODUCCION.md). La estructura recomendada es:

```text
MiVideo/
├── guion.md
├── direcciones.json
├── imagenes/
│   ├── 001_inicio.png
│   └── 002_pasillo.png
└── audio/
    ├── narracion.wav    (opcional)
    └── musica.mp3       (opcional)
```

En **Escenas → Producción automática**, selecciona la carpeta `MiVideo`. MARC copia los recursos y revisa la configuración del motor. Si la IA de vídeo local está disponible, analiza cada imagen, genera clips breves de movimiento corporal y los conecta a las escenas; después prepara voz, música, subtítulos y MP4 sin pedirte que configures cada motor por separado. El archivo final se guarda en `projects/<id>/exports/`, y los clips intermedios en `projects/<id>/generated_video/`. Si el hardware no es compatible, MARC te ofrece explícitamente continuar con el montaje convencional de imagen fija (zoom/paneo), sin presentarlo como animación corporal real.

Usa `guion.md` con encabezados `ESCENA 1`, `ESCENA 2` y etiquetas de hablante `[NARRADOR]:`, `[LUCÍA]:`. En `direcciones.json`, indica movimientos de cámara en `camera_motion`. Las instrucciones actuales aplican zoom/paneo a imágenes fijas; no crean movimiento corporal neuronal por sí mismas.

## Límites transparentes

- **CPU sin GPU:** la importación, voz local, movimiento de cámara 2D, mezcla de pistas y montaje con FFmpeg pueden funcionar en CPU, aunque el render puede tardar bastante.
- **Animación generativa real de personajes:** se instala automáticamente solo cuando el perfil conservador de GPU/RAM/disco es apto. En CPU-only o equipos insuficientes, MARC evita descargar pesos pesados y ofrece el montaje convencional como alternativa. No promete que la generación local sea viable en una laptop sin GPU.
- **Pruebas:** el instalador ejecuta comprobaciones de sintaxis y pruebas unitarias. Antes de distribuir una compilación nueva, todavía hay que probar la GUI, voces, servicios externos y la exportación en Windows real.

## Diagnóstico rápido

- **No inicia:** revisa `%LOCALAPPDATA%\MARC Video Studio AI Desktop\installation-tests.log` y el mensaje de PowerShell.
- **No genera guion local:** comprueba que Ollama esté disponible y ejecuta `ollama list`.
- **No exporta MP4:** comprueba `ffmpeg -version` o usa el selector de FFmpeg de MARC.
- **No hay voz española:** selecciona una voz instalada o importa `audio/narracion.wav`.
