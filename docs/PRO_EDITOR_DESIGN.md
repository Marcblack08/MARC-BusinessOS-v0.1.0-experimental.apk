# MARC Studio — editor profesional

## Decisiones visuales
- Cine oscuro con azul eléctrico, superficies diferenciadas y texto de alto contraste.
- Barra superior de estado para Ollama y FFmpeg.
- Biblioteca de proyectos en panel lateral redimensionable.
- Panel principal con dos zonas de altura ajustable: parámetros de historia y zona de producción/guion.
- Cuadrícula de cuatro columnas para evitar que el formulario sea excesivamente alto.
- Barra de progreso determinista y controles de producción en la zona inferior.
- Editor de guion con barra de desplazamiento vertical.
- Ventana de 1440x900 por defecto, con mínimo 1080x680. Los divisores se pueden arrastrar; usar maximizar si la pantalla es más pequeña.

## Alcance de esta iteración
La rama `ui/pro-editor` cambia la organización de Tkinter hacia paneles redimensionables (`PanedWindow`) y hace más compacta la configuración de historia. Mantiene la generación local con Ollama, los proyectos y la aprobación humana antes de exportar.

Los estilos de dibujo y animación son metadatos/instrucciones de dirección visual para esta versión. No representan todavía un generador de ilustraciones o animación real.

## Instalación
El script de instalación valida el intérprete antes de continuar y comprueba que `.venv\\Scripts\\python.exe` exista. El empaquetado con PyInstaller e Inno Setup debe construirse y probarse en Windows. Este commit no incluye un instalador binario probado.
