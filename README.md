# Aercom Gestión de Servicios

Piloto privado con datos ficticios. El entorno de GitHub Codespaces ejecuta Django y PostgreSQL mediante Docker Compose.

1. Abrí la rama de desarrollo en GitHub y creá el Codespace desde esa rama. Si ya lo tenés abierto con la configuración anterior, actualizá la rama y ejecutá **Codespaces: Rebuild Container**.
2. En **Ports**, abrí el puerto **8000 · Aercom · Piloto** con el ícono del globo. Mantené el puerto privado.
3. Ingresá como `oficina.demo`. Buscá el ticket de lavado y revisión.
4. Salí con el botón **Salir**, ingresá como `campo.demo` y marcá el lavado como realizado.
5. Volvé a entrar como oficina y abrí el ticket. La revisión sigue pendiente y el lavado muestra quién lo hizo y cuándo.

La clave compartida de las cuentas ficticias es `Aercom-Demo-2026`. Usá estas cuentas únicamente en el entorno privado de demostración. La aplicación permite abrir tickets, agregar acciones y asignarlas. El resultado de cada acción se registra por separado.

La vista de campo muestra tareas asignadas. Las visitas programadas, las integraciones y el cierre administrativo corresponden a etapas posteriores.
