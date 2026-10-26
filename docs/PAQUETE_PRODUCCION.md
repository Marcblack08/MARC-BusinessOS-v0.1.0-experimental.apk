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

1. Abre MARC y crea o abre el proyecto que quieres usar.
2. En **Escenas**, pulsa **Importar paquete (guion + dirección + imágenes)**.
3. Selecciona la carpeta `MiVideo`. MARC descubre los archivos, copia los recursos dentro del proyecto, los distribuye por los planos y carga automáticamente narración/música si existen.
4. Revisa el storyboard y aprueba el guion. Después genera la voz si no importaste una pista, revisa el montaje y exporta MP4.

La importación no modifica los archivos originales de la carpeta de origen. Si la carpeta contiene varios guiones, renombra el principal a `guion.md` o `guion.txt` para que la selección sea inequívoca.

## Instalación sin modelos pesados

Ejecuta `install_windows.bat` desde el repositorio en Windows. El instalador prepara Python, las dependencias de MARC, FFmpeg y Ollama/Qwen cuando sea posible. La comprobación del equipo detecta RAM, CPU y GPU. No descarga modelos visuales de muchos gigabytes automáticamente: si ya aportas las imágenes, no los necesitas y evitamos llenar el disco o agotar la memoria. ComfyUI queda como opción aparte para quienes sí necesiten generación de imágenes local.
