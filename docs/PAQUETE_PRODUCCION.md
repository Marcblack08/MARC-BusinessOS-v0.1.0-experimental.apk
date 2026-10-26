# Paquete de producción: guion + dirección + imágenes

MARC puede importar una producción preparada en una sola carpeta. Así no tienes que escoger el guion, las direcciones y cada imagen en ventanas separadas.

## Estructura recomendada

Crea una carpeta para cada vídeo, por ejemplo `MiVideo`:

```text
MiVideo/
├── guion.md
├── direcciones.json
├── imagenes/
│   ├── 001_inicio.png
│   ├── 002_pasillo.png
│   └── 003_primer_plano.png
└── audio/
    ├── narracion.wav       (opcional, si ya tienes la voz grabada)
    └── musica.mp3          (opcional)
```

No necesitas incluir una pista de voz: puedes generarla desde MARC con las voces locales disponibles en Windows. La música también es opcional. Si se incluyen archivos con los nombres habituales, MARC los copia al proyecto y asigna las pistas automáticamente.

## Guion

Usa encabezados de escena para que MARC pueda dividir la historia. Pon cada parlamento en una línea con el nombre del hablante:

```text
ESCENA 1 — La casa
[NARRADOR]: La lluvia golpeaba las ventanas de la vieja casa.
[LUCÍA]: [EMOCION=miedo] ¿Has escuchado eso?

ESCENA 2 — El pasillo
[MATEO]: [EMOCION=susurro] Quédate detrás de mí.
```

Mantén en el guion el diálogo que quieres oír. Las etiquetas de hablante ayudan a distinguir personajes; la emoción es una indicación para motores de voz compatibles.

## Dirección de cámara por escena

El formato JSON es el más claro:

```json
{
  "scenes": [
    {
      "scene": 1,
      "camera_motion": "Acercamiento lento hacia la ventana"
    },
    {
      "scene": 2,
      "camera_motion": "Paneo de izquierda a derecha por el pasillo"
    }
  ]
}
```

También puedes usar `direcciones.txt`, con una indicación por línea, o bloques encabezados `ESCENA 1: ...`. Nombra las imágenes con números al principio (`001_`, `002_`, `003_`) para mantener el orden narrativo.

Las indicaciones controlan el movimiento de cámara del montaje (zoom y paneo) sobre imágenes fijas. No son un sistema de animación corporal neuronal: eso requeriría un modelo generativo adicional y puede resultar demasiado lento en un PC sin GPU.

## Importar

1. Abre MARC y usa el nuevo botón principal **Importar guion + imágenes** (también sigue disponible en **Escenas**).
2. Selecciona la carpeta `MiVideo`. MARC descubre el guion, las direcciones, las imágenes y el audio opcional; copia los archivos al proyecto sin modificar los originales.
3. En **Escenas**, selecciona las filas para revisar la imagen, el diálogo y la dirección de cámara en el panel visual.
4. Si hay una imagen por escena original, se conserva esa asociación aunque el guion se divida en varios planos cortos. Si la cantidad de imágenes es menor que el número de planos, las imágenes se distribuyen por el recorrido; si hay una por plano, se asignan en orden.
5. Revisa el storyboard y aprueba el guion. Si no importaste narración, MARC intenta generarla con las voces SAPI instaladas en Windows. Importa una pista de música si la tienes, revisa la vista previa y exporta el MP4.

**Nota sobre la animación:** el modo de trabajo con imágenes importadas aplica movimiento de cámara (zoom/paneo), transiciones, montaje, narración local y mezcla de audio. No crea movimiento corporal real de los personajes. Esa función necesita un modelo de animación por vídeo separado y puede no ser viable en CPU con equipos de memoria limitada.

La importación no modifica los archivos originales de la carpeta de origen. Si la carpeta contiene varios guiones, renombra el principal a `guion.md` o `guion.txt` para que la selección sea inequívoca.

## Instalación sin modelos pesados

Ejecuta `install_windows.bat` desde el repositorio en Windows. El instalador prepara Python, las dependencias de MARC, FFmpeg y Ollama/Qwen cuando sea posible. La comprobación del equipo detecta RAM, CPU y GPU. No descarga modelos visuales de muchos gigabytes automáticamente: si ya aportas las imágenes, no los necesitas y evitamos llenar el disco o agotar la memoria. ComfyUI queda como opción aparte para quienes sí necesiten generación de imágenes local.
