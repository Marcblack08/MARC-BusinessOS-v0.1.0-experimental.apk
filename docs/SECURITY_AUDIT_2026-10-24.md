# Auditoría de seguridad — M.A.R.C. Video Studio AI

**Fecha:** 24 de octubre de 2026  
**Alcance:** revisión estática del repositorio, con foco en `remote_server.py`, el despacho de comandos en `app.py`, pruebas del servidor remoto y configuración de compilación.  
**Estado:** endurecimiento inicial aplicado en `main`; la validación automatizada del commit final debe completarse. No es una prueba de penetración ni una certificación de seguridad.

## Contexto del incidente de PHP de octubre de 2026

Las noticias de esta semana se refieren a vulnerabilidades críticas en PHP, una tecnología usada por una gran proporción de sitios web (aproximadamente 70 % según los reportes), no a un compromiso confirmado del 70 % de los dispositivos electrónicos del mundo. El riesgo que sirve de ejemplo es que una falla en un componente compartido pueda permitir ejecución de código remoto en sistemas que no han sido parcheados.

M.A.R.C. es una aplicación de escritorio Python/Tkinter y no debe considerarse afectada por una vulnerabilidad de PHP solo por ese incidente. La respuesta adecuada es revisar sus propias superficies de ataque, sus dependencias y sus procesos de actualización.

## Hallazgos y cambios aplicados

### 1. Control remoto y autenticación

- **Controles existentes observados:** el servidor se configura para escuchar en `127.0.0.1`; la API exige un token aleatorio persistente; la comparación del token utiliza `hmac.compare_digest`; las rutas de archivos comprueban que el resultado resuelto permanezca dentro del directorio del proyecto.
- **Endurecimiento aplicado:** límites de concurrencia del servidor HTTP (máximo 16 solicitudes simultáneas), cola de solicitudes de tamaño limitado (64 comandos), timeout de socket de 30 segundos y respuesta `503` cuando el servidor o la cola están ocupados.
- **Riesgo residual:** el acceso remoto depende de que se publique el servidor únicamente a través de un túnel privado autenticado. No configurar Tailscale Funnel ni reenviar el puerto 8765 desde el router. No se ha implementado todavía un mecanismo de rotación de token desde la interfaz.

### 2. Cargas de archivos no confiables

- **Problema identificado:** la validación anterior dependía principalmente de la extensión del nombre del archivo. Una extensión permitida no demuestra que el contenido sea realmente una imagen, vídeo o audio de ese tipo.
- **Endurecimiento aplicado:** se comprueban firmas binarias básicas para PNG, JPEG, GIF, WebP, MP4/MOV/M4V/M4A, WebM y WAV, además de cabeceras plausibles para MP3/AAC; los archivos TXT/SRT deben parecer texto UTF-8. Los archivos que no coinciden se rechazan.
- **Límite:** las firmas son una comprobación preliminar, no un análisis antivirus ni una validación completa del formato. Los parsers de imagen/audio/vídeo y FFmpeg deben mantenerse actualizados. El límite de carga sigue siendo 512 MB.

### 3. Endurecimiento HTTP y errores

- **Endurecimiento aplicado:** se añaden cabeceras de protección contra MIME sniffing, framing y aislamiento entre orígenes; la política CSP añade `form-action 'self'`. Se evita devolver al cliente detalles internos de errores de sistema de archivos o base de datos.
- **Riesgo residual:** el panel contiene JavaScript y CSS inline, por lo que la CSP conserva `unsafe-inline`. Una futura mejora debería moverlos a archivos propios o usar nonces/hash CSP, y añadir una política de intentos fallidos de autenticación sin permitir que un tercero bloquee a usuarios legítimos.

### 4. Despacho de comandos

- Los comandos remotos se restringen a una lista permitida y se encolan para procesarse desde el hilo de la interfaz.
- Se limita el tamaño de JSON y se comprueban tipos y rangos en el procesamiento de comandos de la aplicación.
- La cola ahora está limitada y devuelve una respuesta de servicio ocupado en vez de aceptar un número ilimitado de comandos.

### 5. Ejecución local y cadena de suministro

- En la revisión estática de `app.py` no se encontraron usos explícitos de `shell=True`, `os.system`, `eval` o `exec`. Esto no prueba que toda invocación de herramientas externas sea segura: cada argumento de FFmpeg, PowerShell y herramientas locales debe seguir tratándose como entrada sensible.
- `requirements.txt` contiene rangos de versiones y no un lockfile con hashes. Conviene fijar versiones probadas, generar un inventario de dependencias y revisar actualizaciones de seguridad antes de cada publicación.
- Las acciones CI verifican sintaxis/pruebas y construyen el instalador, pero una compilación correcta no equivale a un análisis SAST, escaneo de dependencias o prueba de penetración.

## Prioridades pendientes

1. **Alta:** verificar que el puerto 8765 solo escucha en loopback en todos los paquetes instalados y documentar una configuración de Tailscale Serve privada; nunca exponerlo directamente a Internet.
2. **Alta:** probar archivos malformados y muy grandes contra los parsers reales de medios, en especial FFmpeg/Pillow, con límites de recursos.
3. **Media:** añadir rotación/revocación de token y límites de intentos de autenticación.
4. **Media:** fijar dependencias y automatizar un escaneo de vulnerabilidades de dependencias en CI.
5. **Media:** añadir pruebas de rutas codificadas, symlinks, JSON excesivo, carga interrumpida, firma incorrecta, cola llena y límite de concurrencia.
6. **Antes de distribuir:** probar el instalador en Windows limpio, revisar permisos ACL del directorio de datos y confirmar que el token no se imprime en logs ni se incluye en los artefactos.

## Resultado

Se aplicaron controles defensivos al servidor remoto y se ampliaron las pruebas de regresión. El estado correcto es **“endurecimiento inicial implementado; verificación pendiente”**, no “sistema invulnerable”. Tras finalizar CI, debe hacerse una prueba manual del instalador y un análisis dinámico autorizado antes de declarar cerrada la auditoría.
