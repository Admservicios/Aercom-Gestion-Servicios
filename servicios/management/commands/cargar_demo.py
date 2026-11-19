import os

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from servicios.models import Accion, Ticket


class Command(BaseCommand):
    help = "Crea dos cuentas y un ticket ficticio para una base de demostración."

    @transaction.atomic
    def handle(self, *args, **options):
        clave = os.environ.get("AERCOM_DEMO_PASSWORD")
        if not clave:
            raise CommandError("Definí AERCOM_DEMO_PASSWORD para cargar la demo.")
        oficina, _ = Group.objects.get_or_create(name="Oficina")
        ines, nueva_ines = User.objects.get_or_create(
            username="oficina.demo", defaults={"first_name": "Inés", "last_name": "Demo"},
        )
        bruno, nuevo_bruno = User.objects.get_or_create(
            username="campo.demo", defaults={"first_name": "Bruno", "last_name": "Demo"},
        )
        if nueva_ines:
            ines.set_password(clave)
            ines.save(update_fields=["password"])
            ines.groups.add(oficina)
        if nuevo_bruno:
            bruno.set_password(clave)
            bruno.save(update_fields=["password"])
        if nueva_ines and nuevo_bruno:
            ticket = Ticket.objects.create(
                asunto="Lavado y revisión de vibración", cliente="Industrias Horizonte (demo)",
                equipo="Generador GE-01", creado_por=ines,
            )
            Accion.objects.bulk_create([
                Accion(ticket=ticket, titulo="Lavado incluido en el abono", responsable=bruno,
                       detalle="Lavar el exterior durante la próxima visita."),
                Accion(ticket=ticket, titulo="Revisión técnica", responsable=ines,
                       detalle="Revisar el reporte y definir si corresponde cotizar."),
            ])
