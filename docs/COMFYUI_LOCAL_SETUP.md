# Generación local de ilustraciones con ComfyUI

MARC puede crear una ilustración para una escena usando ComfyUI instalado en el mismo PC. No envía el prompt a un servicio remoto y no usa una API key. ComfyUI y sus modelos no se incluyen dentro del instalador de MARC; deben instalarse por separado.

## 1. Instalar ComfyUI
- Descarga ComfyUI desde su repositorio oficial: https://github.com/Comfy-Org/ComfyUI
- En Windows, usa la compilación portable que corresponda a la tarjeta gráfica. La documentación oficial distingue las builds modernas de NVIDIA de las builds basadas en CUDA 12.6 para GPUs más antiguas. Para una GTX 750, comprueba primero la compatibilidad del paquete y ten en cuenta que su memoria de vídeo es limitada; la generación puede fallar, ir muy lenta o requerir CPU/ajustes de poca memoria.
- Extrae la carpeta y ejecuta el archivo de arranque recomendado por esa build. Espera a que indique que el servidor está disponible en `http://127.0.0.1:8188`.

Documentación y descargas oficiales:
- Guía de instalación: https://docs.comfy.org/installation/desktop/windows
- Versiones/releases: https://github.com/Comfy-Org/ComfyUI/releases

## 2. Instalar un checkpoint local
ComfyUI necesita por lo menos un checkpoint compatible. La descarga del modelo puede ocupar varios GB.
- Descarga desde un repositorio de modelos que confíes, revisando licencia y requisitos de memoria.
- Copia el archivo de checkpoint compatible en `ComfyUI/models/checkpoints` (o en la ubicación indicada por la build).
- Reinicia o actualiza ComfyUI si el modelo nuevo no aparece.

MARC no descarga modelos automáticamente: tú eliges los archivos que instalarás en tu equipo.

## 3. Generar desde MARC
1. Abre MARC y crea o carga un proyecto.
2. Genera el guion y abre la pestaña **ESCENAS**.
3. Selecciona la escena que quieres ilustrar.
4. Pulsa **Detectar ComfyUI** y espera a que aparezca la lista de checkpoints.
5. Selecciona un modelo y pulsa **Generar ilustración IA**.
6. La imagen se guarda en los recursos locales del proyecto y aparece en la columna **RECURSO VISUAL**.
7. Repite para las escenas que quieras ilustrar. Las escenas sin imagen usarán tarjetas tipográficas.
8. Revisa y aprueba el guion; después exporta el MP4.

## 4. Qué genera actualmente
- ComfyUI produce una imagen fija por cada petición, con una dirección visual guiada por el estilo seleccionado.
- En el montaje, MARC añade movimiento de cámara suave a la imagen (o un tratamiento sencillo según el estilo) y una leyenda breve; no genera todavía secuencias de vídeo neuronal completas.
- Si no hay una imagen para una escena, se usa una tarjeta de texto sobre fondo oscuro.
- Puedes importar tus propias imágenes con **Añadir imagen propia**. Las imágenes se copian a la carpeta de recursos del proyecto.

## Diagnóstico básico
- **ComfyUI no detectado:** abre ComfyUI y confirma que el servidor escucha en el puerto 8188; después pulsa **Detectar ComfyUI**.
- **No aparecen modelos:** confirma que hay un checkpoint compatible en la carpeta de modelos.
- **Out of memory / CUDA error:** utiliza un modelo más pequeño, baja resolución y pasos, elige una build adecuada para GPU antigua o utiliza CPU sabiendo que puede tardar mucho.
- **La imagen genera pero no aparece en MARC:** vuelve a pulsar Detectar ComfyUI y revisa la consola del servidor. MARC conserva los errores en su estado y no debe marcar una escena como ilustrada si no recibió una imagen.

## Privacidad y límites
MARC se comunica con ComfyUI por localhost. La generación requiere que ComfyUI y el checkpoint estén instalados localmente. La primera descarga de ComfyUI/modelos necesita Internet; la inferencia posterior puede ejecutarse localmente. Verifica la licencia de cada modelo antes de usar el resultado comercialmente.
