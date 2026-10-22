# MARC Video Studio AI Desktop

Aplicación de escritorio para Windows enfocada en crear borradores de videos para YouTube, TikTok y Facebook con aprobación humana obligatoria antes de renderizar el video final.

## Estado
**MVP inicial en desarrollo.** Este repositorio contiene el código fuente; todavía no es un instalador EXE compilado ni una versión probada en Windows.

## Principios del proyecto
- Funcionamiento local y sin claves API.
- Sin servicios de IA de pago ni tokens.
- Aprobación humana explícita del guion antes de renderizar.
- Proyectos y guiones guardados localmente en SQLite.
- Perfiles vertical (TikTok/Reels/Shorts) y horizontal (YouTube).
- Renderizado local con FFmpeg.
- Equipo objetivo: Intel Core i5 de 4.ª generación, 16 GB RAM y NVIDIA GTX 750.

## Requisitos
- Windows 10/11 de 64 bits.
- Python 3.11+ para ejecutar desde código.
- FFmpeg instalado y disponible en PATH para exportar MP4.
- Opcional: Ollama instalado localmente y un modelo pequeño compatible, si se desea generar borradores con un LLM local. El modo básico no requiere IA externa.

## Ejecutar desde el código
1. Instala Python 3.11 o posterior.
2. Instala FFmpeg y confirma que `ffmpeg -version` funciona en CMD.
3. Ejecuta `install_windows.bat`.
4. Ejecuta `start_windows.bat`.

## Flujo seguro
1. Crear proyecto y definir tema, plataforma, duración y estilo.
2. Generar un guion preliminar local.
3. Revisar y editar el guion.
4. Marcar explícitamente **Aprobar guion**.
5. Solo entonces habilitar la exportación de video.

La aprobación no publica automáticamente nada en redes sociales. La publicación queda fuera del MVP.

## Limitaciones del MVP
- La generación básica de guiones usa plantillas locales; no se presenta como un modelo generativo avanzado.
- El render inicial usa escenas tipográficas y fondos de color. No incluye todavía generación local de imágenes ni montaje inteligente de material externo.
- No se ha compilado ni probado un instalador EXE en Windows.