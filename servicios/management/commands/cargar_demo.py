import json
from secrets import token_urlsafe

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import transaction

from servicios.models import Accion, Cliente, Equipo, Planta, Ticket


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
        abonado, _ = Cliente.objects.get_or_create(
            codigo="DEMO-AB-01", defaults={"nombre": "Industrias Horizonte (demo)", "tipo": Cliente.Tipo.ABONADO},
        )
        tercero, _ = Cliente.objects.get_or_create(
            codigo="DEMO-TE-01", defaults={"nombre": "Taller del Sur (demo)", "tipo": Cliente.Tipo.TERCERO},
        )
        planta, _ = Planta.objects.get_or_create(
            cliente=abonado, codigo="DEMO-NORTE", defaults={"nombre": "Planta Norte (demo)"},
        )
        deposito, _ = Planta.objects.get_or_create(
            cliente=abonado, codigo="DEMO-DEPOSITO", defaults={"nombre": "Depósito (demo)"},
        )
        equipo, _ = Equipo.objects.get_or_create(
            cliente=abonado, codigo="DEMO-GE-01", defaults={"nombre": "Generador GE-01", "planta": planta},
        )
        Equipo.objects.get_or_create(
            cliente=abonado, codigo="DEMO-CO-02", defaults={"nombre": "Compresor CO-02", "planta": deposito},
        )
        Equipo.objects.get_or_create(
            cliente=tercero, codigo="DEMO-GE-02", defaults={"nombre": "Generador GE-02"},
        )
        if all(nuevas):
            ticket = Ticket.objects.create(
                asunto="Lavado y revisión de vibración", cliente_ficha=abonado,
                planta_ficha=planta, equipo_ficha=equipo, origen="Visita programada", creado_por=ines,
            )
            Accion.objects.bulk_create([
                Accion(ticket=ticket, titulo="Lavado incluido en el abono", responsable=bruno,
                       asignada_por=ines, facturacion=Accion.Facturacion.ABONO,
                       detalle="Lavar el exterior durante la próxima visita."),
                Accion(ticket=ticket, titulo="Revisar vibración", responsable=ines,
                       asignada_por=ines, detalle="Revisar el reporte y definir si corresponde cotizar."),
            ])
        self.stdout.write("Cuentas ficticias preparadas. Consultá .aercom-demo/cuentas.json en privado.")
