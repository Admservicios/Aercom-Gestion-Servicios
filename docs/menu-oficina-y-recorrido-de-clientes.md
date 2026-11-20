# Menú de Oficina y recorrido de clientes

La aplicación lleva a Oficina a un menú de módulos después del ingreso. Desde **Clientes** se puede buscar en todo el catálogo o elegir **Abonados** y **Terceros**. Se reutilizan las fichas existentes de clientes, plantas y equipos. Cada ficha permite iniciar un ticket con los vínculos correspondientes ya seleccionados. El servidor conserva la validación de cliente, planta y equipo y la clasificación se toma de la ficha.

Campo ingresa a **Mis tareas** con los mismos permisos. Las rutas de fichas y tickets existentes siguen vigentes y los filtros antiguos de Tickets en la ruta de inicio redirigen al listado de Tickets. Esta entrega no requiere una migración nueva.

Pasaron 15 pruebas con PostgreSQL 16. En Chromium se completó el recorrido de Oficina desde el ingreso hasta encontrar en la ficha del cliente el ticket creado desde un equipo. También se verificaron Terceros, la búsqueda de equipos y el acceso de Campo a sus asignaciones en tamaño móvil. El reinicio se probó en una copia activa, reemplazando el proceso anterior sin recrear la base ni cambiar las claves locales. GitHub devolvió 403 a la consulta del Codespace del usuario. El README documenta el comando para actualizar desde su terminal. El siguiente subpaso sigue siendo **3.2 · Contratos de abono**, cuando Matías indique avanzar.
