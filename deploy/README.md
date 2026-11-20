# Alojamiento de Aercom Servicios

Este entorno ejecuta Django con Gunicorn, PostgreSQL 16 y Caddy para HTTPS. Solo el proxy publica puertos. El sistema exige inicio de sesión individual y las cuentas conservan los permisos por función. Los volúmenes de PostgreSQL y Caddy persisten al actualizar el código.

## Requisitos del alojamiento

- Un servidor autorizado con Docker Compose, almacenamiento persistente para PostgreSQL y respaldo con restauración probada.
- Un nombre DNS estable y un certificado HTTPS confiable desde los navegadores del equipo. Caddy puede emitir el certificado automáticamente si el DNS y la validación ACME están disponibles. En una red privada, usá un proxy o certificado corporativo ya confiable en las notebooks y configurá el ingreso de acuerdo con esa red.
- Una interfaz de escucha y reglas de red aprobadas para el acceso previsto. Las cuentas de la aplicación controlan los permisos de sus módulos. La red o el proxy controlan quién puede llegar al inicio de sesión.

## Arranque en un alojamiento autorizado

Guardá los parámetros fuera de Git en un archivo protegido que Docker Compose pueda leer. Usá valores distintos para `DJANGO_SECRET_KEY` y `POSTGRES_PASSWORD`. Conservá ambos al actualizar. Si cambia la contraseña de PostgreSQL, rotala también en la base. Cambiar solo el archivo de configuración no actualiza un volumen existente.

| Parámetro | Uso |
|---|---|
| `AERCOM_HOST` | Nombre DNS de la aplicación, sin esquema, ruta ni puerto. |
| `AERCOM_BIND_IP` | IP autorizada del servidor para escuchar HTTP y HTTPS. |
| `DJANGO_SECRET_KEY` | Clave aleatoria para Django. |
| `POSTGRES_PASSWORD` | Clave de la base de datos. |
| `AERCOM_HTTP_PORT` y `AERCOM_HTTPS_PORT` | Opcionales. Por defecto se usan 80 y 443. |

Desde la raíz del repositorio, reemplazá `/ruta/protegida/aercom.env` por la ruta del archivo del servidor:

```bash
docker compose --env-file /ruta/protegida/aercom.env -f deploy/compose.yml build app
docker compose --env-file /ruta/protegida/aercom.env -f deploy/compose.yml run --rm app python manage.py migrate --noinput
docker compose --env-file /ruta/protegida/aercom.env -f deploy/compose.yml run --rm app python manage.py collectstatic --noinput
docker compose --env-file /ruta/protegida/aercom.env -f deploy/compose.yml up -d --no-build
```

Para dar de alta una cuenta individual, ejecutá el comando siguiente en una terminal del servidor. El comando pide la clave de forma interactiva y la guarda como hash. Los roles disponibles se muestran con `crear_cuenta --help`.

```bash
docker compose --env-file /ruta/protegida/aercom.env -f deploy/compose.yml exec app python manage.py crear_cuenta usuario --rol "Administración de Servicios"
```

Esta configuración omite la carga ficticia de Codespaces. Para validar el alojamiento antes de habilitarlo, comprobá desde un navegador autorizado el certificado, el inicio de sesión, el menú de cada rol y el rechazo de acceso directo a una tarea ajena. Verificá también el respaldo y la restauración de PostgreSQL antes de incorporar datos reales.

## Verificación realizada

En un entorno de prueba con PostgreSQL 16 se aplicaron las migraciones, se publicaron los estilos en el volumen del proxy y se comprobó por HTTPS el alta interactiva de una cuenta, el acceso al menú y la protección del inicio de sesión. Se usó un certificado local y se verificó su cadena de confianza en el cliente de prueba. Pasaron las 14 pruebas existentes. Django emitió dos avisos de HSTS sobre subdominios y precarga. Se mantiene HSTS para el host de la aplicación. Esas opciones globales se revisan con el dominio aprobado.

La prueba se ejecutó en la interfaz local. Quedan pendientes la aprobación de la infraestructura y la comprobación desde la red y los navegadores de Aercom.
