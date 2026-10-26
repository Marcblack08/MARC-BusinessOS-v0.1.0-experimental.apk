# Instalar MARC Video Studio AI en Windows

## Instalación desde el repositorio (recomendada para el código actual)

1. Abre el [repositorio MARC Video Studio AI](https://github.com/Marcblack08/MARC-BusinessOS-v0.1.0-experimental.apk).
2. Pulsa **Code → Download ZIP** y extrae la carpeta completa en una ubicación con permisos de escritura (por ejemplo, Documentos\MARC).
3. Ejecuta `install_windows.bat`. Si falta Python compatible, el script intenta instalar Python 3.12 de 64 bits con Winget. Después prepara el entorno virtual, instala dependencias, intenta instalar FFmpeg y Ollama, descarga Qwen 2.5 3B si Ollama queda disponible y ejecuta las validaciones/pruebas.
4. Al terminar, MARC se abre con `start_windows.bat`. Para iniciar el programa en las siguientes ocasiones, abre `start_windows.bat`.

La instalación guarda el perfil de hardware y el registro de pruebas en `%LOCALAPPDATA%\MARC Video Studio AI Desktop`. Si falla alguna prueba, el instalador muestra el error y conserva el registro para diagnosticarlo.

Si Winget no está disponible, Python, FFmpeg u Ollama podrían requerir su instalador oficial. Los enlaces se muestran en pantalla; el script no eleva permisos de administrador de forma silenciosa.

## Instalador empaquetado (alternativa)

1. En el repositorio, abre **Actions → Build Windows desktop installer**.
2. Descarga el artefacto `MARC-Video-Studio-Windows` de una ejecución exitosa.
3. Ejecuta `MARC-Video-Studio-Setup-0.2.0-x64.exe`.

El artefacto de Actions puede caducar; usa la ejecución más reciente. La aplicación empaquetada no incluye el modelo local ni los motores externos de IA.

## Qué queda preparado automáticamente

- **FFmpeg:** montaje, transiciones, movimiento 2D de cámara, subtítulos y exportación MP4.
- **Ollama + Qwen 2.5 3B:** guiones locales, si se pudo instalar y descargar el modelo.
- **Perfil de hardware:** informe de CPU, RAM y GPU para orientar el modo recomendado.
- **Modelos de imagen/vídeo:** no se descargan automáticamente porque ocupan muchos GB y algunos no son viables en equipos sin GPU. Si ya tienes las imágenes, no necesitas ComfyUI para importarlas ni para montar el vídeo.
- **Voz:** MARC usa las voces locales disponibles en Windows o acepta una pista de narración importada. La disponibilidad de voces españolas depende de las voces instaladas en el propio Windows.

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

En **Escenas → Importar paquete**, selecciona la carpeta `MiVideo`. MARC descubre y copia los recursos, distribuye las imágenes entre los planos y vincula automáticamente la narración/música si los archivos tienen nombres convencionales.

Usa `guion.md` con encabezados `ESCENA 1`, `ESCENA 2` y etiquetas de hablante `[NARRADOR]:`, `[LUCÍA]:`. En `direcciones.json`, indica movimientos de cámara en `camera_motion`. Las instrucciones actuales aplican zoom/paneo a imágenes fijas; no crean movimiento corporal neuronal por sí mismas.

## Límites transparentes

- **CPU sin GPU:** la importación, voz local, movimiento de cámara 2D, mezcla de pistas y montaje con FFmpeg pueden funcionar en CPU, aunque el render puede tardar bastante.
- **Animación generativa real de personajes:** necesita un motor y un modelo adicionales compatibles con el hardware. No se instala automáticamente ni se promete que funcione en una laptop sin GPU.
- **Pruebas:** el instalador ejecuta comprobaciones de sintaxis y pruebas unitarias. Antes de distribuir una compilación nueva, todavía hay que probar la GUI, voces, servicios externos y la exportación en Windows real.

## Diagnóstico rápido

- **No inicia:** revisa `%LOCALAPPDATA%\MARC Video Studio AI Desktop\installation-tests.log` y el mensaje de PowerShell.
- **No genera guion local:** comprueba que Ollama esté disponible y ejecuta `ollama list`.
- **No exporta MP4:** comprueba `ffmpeg -version` o usa el selector de FFmpeg de MARC.
- **No hay voz española:** selecciona una voz instalada o importa `audio/narracion.wav`.
