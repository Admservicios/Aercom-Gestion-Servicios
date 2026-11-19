import json
from secrets import token_urlsafe

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import transaction

from servicios.models import Accion, Ticket


class Command(BaseCommand):
    help = "Inicializa dos cuentas ficticias y un ticket de ejemplo."

    @transaction.atomic
    def handle(self, *args, **options):
        ruta = settings.BASE_DIR / ".aercom-demo" / "cuentas.json"
        ruta.parent.mkdir(mode=0o700, exist_ok=True)
        cuentas = {"oficina.demo": "Inés", "campo.demo": "Bruno"}
        if not ruta.exists():
            ruta.touch(mode=0o600, exist_ok=False)
            ruta.write_text(json.dumps({usuario: token_urlsafe(18) for usuario in cuentas}, indent=2) + "\n")
        claves = json.loads(ruta.read_text())
        oficina, _ = Group.objects.get_or_create(name="Oficina")
        personas = {}
        nuevas = []
        for usuario, nombre in cuentas.items():
            persona, nueva = User.objects.get_or_create(
                username=usuario, defaults={"first_name": nombre, "last_name": "Demo"},
            )
            if not persona.check_password(claves[usuario]):
                persona.set_password(claves[usuario])
                persona.save(update_fields=["password"])
            personas[usuario] = persona
            nuevas.append(nueva)
        ines, bruno = personas["oficina.demo"], personas["campo.demo"]
        ines.groups.add(oficina)
        bruno.groups.remove(oficina)
        if all(nuevas):
            ticket = Ticket.objects.create(
                asunto="Lavado y revisión de vibración", cliente="Industrias Horizonte (demo)",
                equipo="Generador GE-01", origen="Visita programada", creado_por=ines,
            )
            Accion.objects.bulk_create([
                Accion(ticket=ticket, titulo="Lavado incluido en el abono", responsable=bruno,
                       asignada_por=ines, facturacion=Accion.Facturacion.ABONO,
                       detalle="Lavar el exterior durante la próxima visita."),
                Accion(ticket=ticket, titulo="Revisar vibración", responsable=ines,
                       asignada_por=ines, detalle="Revisar el reporte y definir si corresponde cotizar."),
            ])
        self.stdout.write("Cuentas ficticias preparadas. Consultá .aercom-demo/cuentas.json en privado.")
