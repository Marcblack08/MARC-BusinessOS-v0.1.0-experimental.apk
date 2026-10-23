# Auditoría y hoja de ruta de MARC Video Studio AI Desktop

## Implementado en el código (requiere pruebas de funcionamiento en Windows)
- [x] Interfaz azul tecnológico con biblioteca y paneles.
- [x] Parámetros narrativos y controles de estilo de dibujo/animación.
- [x] Progreso de guion con porcentaje y capítulos completados.
- [x] Generación local por capítulos con Ollama/Qwen en segundo plano.
- [x] Persistencia SQLite con migraciones.
- [x] Aprobación manual obligatoria antes de exportar.
- [x] Búsqueda y selección manual de FFmpeg.
- [x] Validación sintáctica automática de Python en GitHub Actions.
- [x] Scripts de instalación/arranque mejorados y script para construir una carpeta portable con PyInstaller.
- [ ] Prueba integral de la generación de un guion en Windows.
- [ ] Prueba de exportación MP4 real y medición de recursos.
- [ ] Prueba de la carpeta portable en una instalación limpia.

## Fase visual y audiovisual siguiente
- [ ] Generar imágenes locales para cada escena.
- [ ] Convertir las imágenes en secuencias animadas reales según el estilo elegido.
- [ ] Editor visual de escenas con vista previa y reordenamiento.
- [ ] Voz sintética local y selección de voz.
- [ ] Música, efectos y mezcla de audio.
- [ ] Subtítulos SRT/VTT.
- [ ] Instalador Windows real (MSI/EXE) con acceso directo, desinstalación y ubicación de datos segura.

## Principios
- Sin claves API obligatorias.
- Proyectos locales; no publicar automáticamente.
- Aprobación humana antes de exportar.
- No presentar tarjetas de texto como animación cinematográfica real.
