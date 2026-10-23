# Auditoría y hoja de ruta de MARC Video Studio AI Desktop

## Implementado en el código de main (pendiente de prueba integral en Windows)
- [x] Interfaz azul tecnológico con biblioteca de proyectos y tarjetas de configuración.
- [x] Campos narrativos independientes: género, protagonista, conflicto, tono, narrador y desenlace.
- [x] Ollama/Qwen local para biblia de continuidad y capítulos secuenciales.
- [x] Generación en segundo plano, mensajes de progreso y cancelación entre capítulos.
- [x] SQLite con migración compatible para los nuevos campos narrativos.
- [x] La aprobación humana es obligatoria para exportar.
- [x] Si cambian el guion o sus parámetros, la aprobación anterior se invalida.
- [x] Búsqueda automática de FFmpeg y selección manual del ejecutable.
- [x] Agrupación de texto para aproximar la duración solicitada en el render de tarjetas.
- [x] Ejecutar comprobación sintáctica con GitHub Actions (`py_compile` correcto en el commit auditado).
- [ ] Probar instalación limpia, escritura multicapítulo y render MP4 real en Windows.
- [ ] Revisar escalado y legibilidad de la interfaz en diferentes resoluciones.

## Siguiente fase: calidad de contenido
- [ ] Esquema estructurado de escenas (narración, diálogo, visual y duración).
- [ ] Resumen de continuidad actualizado entre capítulos para mejorar coherencia en historias muy largas.
- [ ] Reintentos controlados para errores temporales de Ollama.
- [ ] Revisión de duración a partir del recuento real de palabras.
- [ ] Editor de escenas y reordenamiento manual.
- [ ] Importar imágenes y clips propios.

## Siguiente fase: producción audiovisual
- [ ] Voz sintética local opcional, con revisión y elección de voz.
- [ ] Subtítulos SRT/VTT.
- [ ] Render con imágenes, clips, transiciones y pista de audio.
- [ ] Vista previa de escenas y controles de calidad.
- [ ] Empaquetar EXE/instalador y probarlo en una instalación limpia.

## Principios
- Sin claves API obligatorias ni servicios de IA externos.
- Contenido y proyectos guardados localmente.
- No publicación automática.
- Ningún video final se exporta sin aprobación humana explícita.
- Comunicar al usuario cuándo la salida es texto básico y no un montaje audiovisual completo.
