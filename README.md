# MARC Video Studio AI Desktop

Aplicación de escritorio local para crear guiones narrativos con Ollama/Qwen, revisarlos y exportar un MP4 de escenas tipográficas mediante FFmpeg.

## Estado real del proyecto
El código fuente está en desarrollo. La sintaxis de Python se valida mediante GitHub Actions. La ejecución completa, el render en Windows y el empaquetado deben probarse en el PC objetivo antes de considerar una versión estable. El empaquetado de Windows usa PyInstaller y puede generar un instalador con asistente mediante Inno Setup 6. No es un MSI firmado; el instalador debe probarse en Windows antes de distribuirlo.

## Mejoras actuales
- Interfaz azul tecnológico con biblioteca de proyectos y paneles.
- Configuración narrativa independiente.
- Estilos seleccionables de dibujo y animación para orientar la dirección visual del guion.
- Barra de progreso con porcentaje, capítulos completados y estimación de palabras.
- Generación por capítulos con Ollama/Qwen 2.5 3B en segundo plano.
- Guardado local SQLite con migraciones compatibles.
- Aprobación humana obligatoria antes de exportar; editar invalida la aprobación.
- Búsqueda automática y selección manual de FFmpeg.

## Requisitos
- Windows 10/11 de 64 bits.
- Python 3.11+ con Tcl/Tk para ejecutar desde código.
- Ollama instalado y modelo local `qwen2.5:3b` descargado.
- FFmpeg para exportar MP4.
- Equipo objetivo: Intel Core i5 de 4.ª generación, 16 GB de RAM, SSD y NVIDIA GTX 750. La generación larga puede tardar por CPU.

## Instalación y ejecución
1. Instala Python 3.11+.
2. Instala Ollama y descarga una vez el modelo con `ollama run qwen2.5:3b`.
3. Descarga FFmpeg Essentials; puedes dejarlo fuera de PATH y elegir `ffmpeg.exe` desde MARC.
4. Ejecuta `install_windows.bat`.
5. Abre MARC con `start_windows.bat`.

Para crear la aplicación de escritorio y, opcionalmente, el instalador con asistente:
1. Instala Inno Setup 6 desde https://jrsoftware.org/isinfo.php.
2. Ejecuta `build_windows.bat`.
3. La carpeta de la aplicación se genera en `dist`; el instalador Setup.exe se genera en `dist-installer` si Inno Setup se encuentra instalado.
4. Prueba la instalación y la desinstalación en Windows antes de distribuirla. Los proyectos y la base de datos de la aplicación empaquetada se guardan en `%LOCALAPPDATA%\\MARC Video Studio AI Desktop`.

Ollama/Qwen y FFmpeg no quedan integrados en el instalador: deben instalarse por separado para las funciones de IA local y exportación.

## Flujo de producción
1. Completa premisa y parámetros.
2. MARC propone un plan y genera capítulos.
3. Revisa y edita el guion.
4. Pulsa **Aprobar guion**.
5. Exporta el MP4.

## Limitaciones importantes
- Los estilos de dibujo/animación se guardan y orientan el diseño narrativo, pero el motor actual no genera imágenes ni animación real automáticamente.
- La exportación actual utiliza escenas de texto con fondos. No incorpora voz, música, imágenes generadas ni montaje de clips.
- La duración real depende del texto final y del ritmo de narración; el cálculo mostrado es orientativo.
- Cancelar la IA actúa después de que termine la solicitud de Ollama que esté en curso.
