# Aercom Gestión de Servicios

Piloto privado con datos ficticios. GitHub Codespaces prepara Django y PostgreSQL mediante Docker Compose.

1. En GitHub, seleccioná la rama `desarrollo/piloto-demo` y creá un Codespace desde **Code → Codespaces**. Usá un Codespace nuevo para esta demo si el anterior tenía un volumen de PostgreSQL configurado con la clave anterior. Conservá ese volumen si necesitás sus datos.
2. Esperá la inicialización. En la terminal del Codespace, ejecutá `cat .aercom-demo/cuentas.json` para consultar las claves individuales. Guardalas en privado. Si usás un entorno con las cuentas anteriores, la carga inicial actualiza ambas claves y conserva los tickets existentes.
3. En **Ports**, buscá **8000 · Aercom · Piloto**, mantenelo privado y abrilo en Chrome con el ícono del globo. Si Chrome devuelve 401, iniciá sesión en GitHub con la cuenta propietaria del Codespace y volvé a abrir el puerto desde **Ports**.
4. Entrá como `oficina.demo`. Usá **Nuevo ticket**, cargá un generador ficticio y agregá dos acciones. Asigná «Lavado incluido en el abono» a Bruno Demo con facturación «Incluida en el abono». Asigná «Revisar vibración» a Inés Demo.
5. Salí, entrá como `campo.demo` y completá el lavado en **Mis tareas**. Volvé a entrar como oficina, buscá el generador y comprobá que el ticket sigue abierto, el lavado tiene autor y hora, y la revisión sigue asignada a Inés.

También hay un ticket de ejemplo. La modalidad de abono se muestra en cada acción y esta entrega no emite facturas. Las fichas de análisis técnico, las visitas programadas, la facturación y el cierre administrativo quedan para las próximas etapas.

Para repetir las pruebas en el Codespace:

```bash
DJANGO_SECRET_KEY="$(cat .aercom-demo/django.key)" python manage.py test
```
