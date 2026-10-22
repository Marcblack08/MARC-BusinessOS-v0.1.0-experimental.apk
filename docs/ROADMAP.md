# Hoja de ruta de MARC Video Studio AI Desktop

## Fase 1 — MVP local
- [x] Esqueleto de aplicación Windows en Python/Tkinter.
- [x] Base local SQLite para proyectos.
- [x] Borrador de guion por plantillas, sin red ni API.
- [x] Puerta de aprobación humana antes de exportar.
- [x] Exportación local MP4 con FFmpeg y escenas tipográficas.
- [ ] Validar ejecución completa en Windows 10/11.
- [ ] Probar FFmpeg y corregir diferencias de ruta/fuentes entre equipos.

## Fase 2 — Contenido mejorado
- [ ] Integración opcional con modelo local vía Ollama, desactivada por defecto.
- [ ] Editor de escenas y duración individual.
- [ ] Importar imágenes y videos propios con selector de archivos.
- [ ] Generación de voz local opcional, con selección de voz y revisión.
- [ ] Subtítulos SRT/VTT y corrección manual.

## Fase 3 — Empaquetado
- [ ] Compilar instalador Windows.
- [ ] Probar instalación limpia en equipo de especificaciones objetivo.
- [ ] Verificar uso de RAM/CPU y compatibilidad con GTX 750.
- [ ] Firmar y publicar versión solo después de pruebas.

## Restricciones de diseño
- Sin claves API obligatorias.
- No subir contenido a la nube.
- No publicar automáticamente en redes sociales.
- El usuario revisa y aprueba el guion antes de renderizar.
- Toda función que use un modelo local debe declarar el espacio en disco y la memoria que requiere.
