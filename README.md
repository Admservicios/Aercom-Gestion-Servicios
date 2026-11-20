# Aercom Gestión de Servicios

Piloto privado con datos ficticios. GitHub Codespaces prepara Django y PostgreSQL mediante Docker Compose, con la imagen oficial de Python 3.12 de Docker Hub y PostgreSQL 16.

1. En GitHub, seleccioná la rama `desarrollo/piloto-demo` y creá un Codespace desde **Code → Codespaces**. Si ya tenés un Codespace en esa rama, actualizalo y ejecutá **Codespaces: Rebuild Container**. Si ese entorno tiene un volumen de PostgreSQL que se creó con la clave fija del piloto anterior, conservá ese volumen y usá un entorno de demo nuevo.
2. Esperá la inicialización. En la terminal del Codespace, ejecutá `cat .aercom-demo/cuentas.json` para consultar las claves individuales. Guardalas en privado. Si ya tenés las cuentas anteriores, la carga conserva sus claves locales y agrega las que falten.
3. En **Ports**, buscá **8000 · Aercom · Piloto**, mantenelo privado y abrilo en Chrome con el ícono del globo. La URL privada de Codespaces abre el formulario **Ingresar a Servicios**. Si Chrome devuelve 401, iniciá sesión en GitHub con la cuenta propietaria del Codespace y volvé a abrir el puerto desde **Ports**.
4. Entrá como `oficina.demo`. Usá **Nuevo ticket**, cargá un generador ficticio y agregá dos acciones. Asigná «Lavado incluido en el abono» a Bruno Demo con facturación «Incluida en el abono». Asigná «Revisar vibración» a Inés Demo.
5. Salí, entrá como `campo.demo` y completá el lavado en **Mis tareas**. Volvé a entrar como oficina, buscá el generador y comprobá que el ticket sigue abierto, el lavado tiene autor y hora, y la revisión sigue asignada a Inés.

También hay un ticket de ejemplo. La modalidad de abono se muestra en cada acción y esta entrega no emite facturas. Las fichas de análisis técnico, las visitas programadas, la facturación y el cierre administrativo quedan para las próximas etapas.

Para probar los permisos, `oficina.demo` (Administración de Servicios) puede dar de alta fichas y `comercial.demo` puede consultarlas y crear tickets. Las seis cuentas de oficina también pueden consultar **Alertas de campo**. Desde `campo.demo`, abrí **Mis tareas** o **Reportar alerta**. La alerta queda registrada en el sistema. Las demás cuentas de campo son `campo2.demo`, `campo3.demo` y `campo4.demo`.

Para repetir las pruebas en el Codespace:

```bash
DJANGO_SECRET_KEY="$(cat .aercom-demo/django.key)" python manage.py test
```
