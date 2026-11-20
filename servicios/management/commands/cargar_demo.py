import json
from datetime import date
from pathlib import Path
from secrets import token_urlsafe
from tempfile import NamedTemporaryFile

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import transaction

from servicios.models import (
    Accion, Cliente, ContactoCliente, ContratoAbono, DocumentoCliente, Equipo, Planta, Ticket,
)
from servicios.permisos import ROLES_SERVICIOS, Rol


CUENTAS = {
    "oficina.demo": ("Inés", Rol.ADMINISTRACION),
    "responsable.demo": ("Julia", Rol.RESPONSABLE),
    "comercial.demo": ("Lucas", Rol.COMERCIAL),
    "coordinacion.demo": ("Camila", Rol.COORDINACION),
    "tecnica1.demo": ("Sofía", Rol.RESPONSABLE_TECNICO),
    "tecnica2.demo": ("Julián", Rol.RESPONSABLE_TECNICO),
    "campo.demo": ("Bruno", Rol.CAMPO),
    "campo2.demo": ("Nicolás", Rol.CAMPO),
    "campo3.demo": ("Vera", Rol.CAMPO),
    "campo4.demo": ("Mateo", Rol.CAMPO),
}


def preparar_claves(ruta):
    ruta.parent.mkdir(mode=0o700, exist_ok=True)
    claves = json.loads(ruta.read_text()) if ruta.exists() else {}
    faltantes = CUENTAS.keys() - claves.keys()
    if faltantes:
        claves.update({usuario: token_urlsafe(18) for usuario in sorted(faltantes)})
        with NamedTemporaryFile(mode="w", dir=ruta.parent, delete=False) as temporal:
            json.dump(claves, temporal, indent=2)
            temporal.write("\n")
        Path(temporal.name).replace(ruta)
    return claves


class Command(BaseCommand):
    help = "Inicializa las cuentas ficticias por función y datos de ejemplo."

    @transaction.atomic
    def handle(self, *args, **options):
        ruta = settings.BASE_DIR / ".aercom-demo" / "cuentas.json"
        claves = preparar_claves(ruta)
        personas = {}
        nuevas = set()
        for usuario, (nombre, rol) in CUENTAS.items():
            persona, nueva = User.objects.get_or_create(
                username=usuario, defaults={"first_name": nombre, "last_name": "Demo"},
            )
            if not persona.check_password(claves[usuario]):
                persona.set_password(claves[usuario])
                persona.save(update_fields=["password"])
            grupo, _ = Group.objects.get_or_create(name=rol)
            anteriores = persona.groups.filter(name__in=ROLES_SERVICIOS).exclude(pk=grupo.pk)
            persona.groups.remove(*anteriores)
            persona.groups.add(grupo)
            personas[usuario] = persona
            if nueva:
                nuevas.add(usuario)
        ines, bruno = personas["oficina.demo"], personas["campo.demo"]
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
        ContactoCliente.objects.get_or_create(
            cliente=abonado, nombre="Elena Ejemplo",
            defaults={"planta": planta, "cargo": "Contacto de mantenimiento", "correo": "elena@example.com"},
        )
        DocumentoCliente.objects.get_or_create(
            cliente=abonado, tipo="Llamada SAP", referencia="DEMO-NS-001",
            defaults={"descripcion": "Referencia ficticia de mantenimiento"},
        )
        ContratoAbono.objects.get_or_create(
            cliente=abonado, referencia="AB-DEMO-01", vigente_desde=date(2025, 1, 1),
            defaults={
                "vigente_hasta": date(2025, 12, 31), "alcance": "Visitas preventivas de ejemplo.",
                "frecuencia": "Mensual", "cobertura_general": True, "valor": "100000.00", "moneda": "ARS",
            },
        )
        contrato, nuevo_contrato = ContratoAbono.objects.get_or_create(
            cliente=abonado, referencia="AB-DEMO-01", vigente_desde=date(2026, 1, 1),
            defaults={
                "alcance": "Mantenimiento preventivo y lavado del generador en Planta Norte.",
                "frecuencia": "Mensual", "valor": "125000.00", "moneda": "ARS", "requiere_oc": True,
            },
        )
        if nuevo_contrato:
            contrato.plantas.add(planta)
            contrato.equipos.add(equipo)
        if {"oficina.demo", "campo.demo"} <= nuevas:
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
