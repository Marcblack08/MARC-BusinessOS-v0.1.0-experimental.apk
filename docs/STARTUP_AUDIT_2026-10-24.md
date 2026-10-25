# Auditoría de fallo de arranque de MARC Video Studio AI

**Fecha:** 24–25 de octubre de 2026  
**Alcance:** apertura de la aplicación de escritorio Windows, composición de la barra compacta y empaquetado del instalador.  
**Estado:** causas reproducidas en código y corregidas; smoke test de inicio de Tkinter pasado en CI; compilación de instalador de la revisión más reciente pendiente de finalización al redactar esta nota.

## Resumen ejecutivo

El programa fallaba antes de mostrar su ventana principal por defectos en `App._apply_compact_workspace()`, ejecutada durante `App.__init__()`. No era un problema de Ollama, ComfyUI, la base de datos de proyectos ni del sistema de seguridad remoto.

## Hallazgos

### P0 — Uso mezclado de administradores geométricos en Tkinter

La primera captura mostró:

`TclError: cannot use geometry manager pack inside ... which already has slaves managed by grid`

La función compacta trataba de ocultar y volver a colocar controles mediante `pack()` aun cuando su contenedor ya organizaba controles mediante `grid()`. Tkinter no permite administrar hijos del mismo contenedor con `pack` y `grid` simultáneamente. Al ocurrir durante `_build()`, la excepción abortaba la creación de la ventana.

**Corrección:** los controles que pertenecen a `primary_actions` se mantienen con `grid()`; las acciones secundarias permanecen en su contenedor original y se exponen desde el menú «Más», sin intentar reparentar widgets existentes.

### P0 — Referencia de contenedor no inicializada

La segunda captura mostró:

`AttributeError: '_tkinter.tkapp' object has no attribute 'primary_actions'`

La función compacta usaba `self.primary_actions`, pero el marco se había creado como variable local `primary_actions`. El artefacto probado no contenía la asignación que exponía ese marco como atributo de la instancia.

**Corrección:** `self.primary_actions = primary_actions` se asigna al crear el contenedor. También se conserva `self.secondary_actions` para poder ocultar el panel secundario de forma segura.

### P1 — No existía una prueba automatizada del arranque real de la interfaz

Antes de la corrección, la CI compilaba archivos Python y ejecutaba pruebas de lógica, pero la comprobación de interfaz solo importaba `tkinter`; no instanciaba `App`. Por eso las pruebas verdes no detectaban errores de creación de widgets ocurridos al abrir el programa.

**Corrección:** se añadió `tests/test_app_startup.py`. En Windows CI crea una instancia real de `App`, ejecuta `update_idletasks()` para forzar el cálculo de geometría, verifica los padres de los controles y cierra la aplicación. La prueba se incorpora a los dos flujos de validación.

## Evidencia de validación

En el flujo de validación para el commit `b5e25d28300e5c3e014a87346ff92c28bb462564`, el resultado de la prueba fue:

- `test_app_constructs_and_compact_toolbar_uses_correct_parents ... ok`
- 69 pruebas totales ejecutadas.
- Resultado: `OK`.

Ejecución: https://github.com/Marcblack08/MARC-BusinessOS-v0.1.0-experimental.apk/actions/runs/40151911825

La compilación de instalador de ese commit se ejecuta aquí:  
https://github.com/Marcblack08/MARC-BusinessOS-v0.1.0-experimental.apk/actions/runs/40151911789

## Por qué se seguía viendo el error

El archivo de la captura tiene fecha de modificación **25/10/2026 a las 01:36**. Esa hora corresponde a un artefacto anterior, compilado desde el commit `809d3783ad66553e881d92f63e991d966d336c6a`. La asignación de `primary_actions` se corrigió después; más tarde se corrigió también la propiedad de los widgets y se añadió la prueba de arranque. Por tanto, los cambios posteriores en `main` no podían reparar un instalador que ya estaba descargado.

## Riesgos residuales y límites

- El smoke test valida la creación y geometría inicial de la ventana en el runner de Windows; no equivale a una prueba interactiva completa en el PC del usuario.
- Esta auditoría no certifica la generación de guiones, la descarga de modelos, la producción de imágenes ni el renderizado MP4.
- La comprobación final de esta reparación requiere que termine correctamente la compilación del instalador correspondiente al código que contiene el smoke test y probar ese artefacto, no uno anterior.

## Commits de referencia

- Asignación del marco principal: https://github.com/Marcblack08/MARC-BusinessOS-v0.1.0-experimental.apk/commit/9122d3497c8bfe417c6682121dad28460aa4bfe4
- Corrección de propiedad y distribución de controles: https://github.com/Marcblack08/MARC-BusinessOS-v0.1.0-experimental.apk/commit/27fc2c56a8a33993c09ab8af0f75bea9e6d339b0
- Prueba de inicio y validación: https://github.com/Marcblack08/MARC-BusinessOS-v0.1.0-experimental.apk/commit/b5e25d28300e5c3e014a87346ff92c28bb462564
