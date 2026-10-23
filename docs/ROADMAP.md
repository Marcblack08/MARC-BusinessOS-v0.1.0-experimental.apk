# Auditoría y hoja de ruta de MARC Video Studio AI Desktop

## En el código (pendiente de prueba integral en el PC objetivo)
- [x] Interfaz cine oscuro/azul eléctrico con paneles redimensionables.
- [x] Pestañas Guion, Escenas y Vista previa.
- [x] Campos narrativos y estilos de dibujo/animación.
- [x] Guiones con Ollama/Qwen por capítulos en segundo plano.
- [x] SQLite con migraciones compatibles y aprobación humana obligatoria.
- [x] Estimación del equipo, duración y progreso por capítulos/escenas.
- [x] Parser de guion a escenas con título, palabras, duración y estado del recurso visual.
- [x] Importación/almacenamiento local de imágenes por escena.
- [x] Integración opcional con ComfyUI local para generar imágenes fijas.
- [x] Exportación MP4 en segundo plano con progreso, cancelación y logs FFmpeg.
- [x] Movimiento sencillo de cámara para imágenes fijas y tratamiento pixel/stop-motion básico.
- [x] Pistas separadas de narración y música, mezcla con música atenuada y opción de repetir música corta dentro del MP4.
- [x] Generación offline de narración con Windows System.Speech/SAPI y selección de voces instaladas.
- [x] Exportación de subtítulos SRT por escena con tiempos orientativos y tests unitarios.
- [x] Pruebas de integración FFmpeg en Windows para mezcla de narración+música y pista de voz individual.
- [x] Instalador de dependencias y constructor PyInstaller/Inno Setup.
- [x] Flujo de GitHub Actions para construir instalador y carpeta portable manualmente.
- [x] Pruebas unitarias del parser/tiempos/escape de rutas en CI.
- [ ] Probar la GUI en Windows con escalas/resoluciones distintas.
- [ ] Probar Ollama con Qwen 2.5 3B y ComfyUI con un checkpoint concreto.
- [ ] Probar exportación MP4 corta con imagen + narración y música, incluidos caracteres y rutas con espacios, en el PC objetivo.
- [ ] Ejecutar el artefacto de instalador sobre Windows limpio; confirmar instalar/desinstalar y persistencia de datos.

## Siguientes fases de producción
- [ ] Evaluar un motor neuronal de voz local opcional para mejorar la calidad respecto a Windows SAPI.
- [ ] Subtítulos SRT/VTT sincronizados con el guion.
- [ ] Vista previa de fotogramas y reproductor integrado.
- [ ] Edición manual/reordenamiento de escenas y edición de duración por escena.
- [ ] Generación por lotes de ilustraciones con aprobación de cada imagen.
- [ ] Mejorar continuidad de personajes entre imágenes (referencia de personaje/seed).
- [ ] Transiciones y pistas de audio separadas con mezcla/volumen/fades.
- [ ] Estimación de tiempo calibrada con mediciones de cada PC, no solo heurística.

## Principios
- Sin claves API obligatorias ni publicación automática.
- Trabajar localmente cuando los motores estén instalados.
- Aprobación humana antes de exportar.
- Comunicar claramente si una imagen o escena aún no está generada.
