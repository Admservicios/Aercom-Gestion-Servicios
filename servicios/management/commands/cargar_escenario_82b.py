from datetime import date, time

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from servicios.agenda import registrar_movimiento as registrar_programacion
from servicios.facturacion_abonos import datos_del_contrato
from servicios.models import Accion, Cliente, MovimientoTiempoAccion, PedidoServicio, SolicitudFacturacionTrabajo
from servicios.permisos import roles
from servicios.tiempos import registrar_movimiento

from .cargar_demo import CUENTAS


CODIGO = "FICT-82B"
CLIENTE = "Metalúrgica Aurora (ficticia)"
INICIO_VIGENCIA = date(2026, 1, 1)
PASO_CORRECTIVO = "Medir la vibración con carga para preparar la cotización."


def trabajo(cliente, planta, equipo, asunto, titulo, responsable, oficina, **detalles):
    ticket, _ = cliente.tickets.get_or_create(
        asunto=asunto, defaults={
            "creado_por": oficina, "planta_ficha": planta, "equipo_ficha": equipo,
            "origen": "Prueba funcional 8.2B", "detalle": detalles.get("detalle", ""),
        },
    )
    accion, creada = ticket.acciones.get_or_create(
        titulo=titulo, defaults={"responsable": responsable, "asignada_por": oficina, **detalles},
    )
    if creada:
        registrar_movimiento(accion, MovimientoTiempoAccion.Tipo.ASIGNACION, oficina)
    return accion


class Command(BaseCommand):
    help = "Prepara el escenario ficticio 8.2B de Aercom. Conserva el avance cuando se vuelve a ejecutar."

    def add_arguments(self, parser):
        parser.add_argument("--fecha", type=date.fromisoformat, help="Fecha de la práctica (AAAA-MM-DD).")

    @transaction.atomic
    def handle(self, *args, **options):
        dia = options["fecha"] or timezone.localdate()
        if dia < INICIO_VIGENCIA:
            raise CommandError(f"Usá una fecha a partir de {INICIO_VIGENCIA:%d/%m/%Y}.")
        cuentas = {}
        for nombre in ("oficina.demo", "responsable.demo", "coordinacion.demo", "campo.demo", "campo3.demo"):
            usuario = User.objects.filter(username=nombre, is_active=True).first()
            if usuario is None or CUENTAS[nombre][1] not in roles(usuario):
                raise CommandError(f"Falta la cuenta ficticia {nombre} con su rol. Ejecutá cargar_demo en el entorno de prueba.")
            cuentas[nombre] = usuario
        admin = cuentas["oficina.demo"]
        oficina = cuentas["responsable.demo"]
        coordinacion = cuentas["coordinacion.demo"]
        bruno = cuentas["campo.demo"]
        vera = cuentas["campo3.demo"]

        cliente, _ = Cliente.objects.select_for_update(no_key=True).get_or_create(
            codigo=CODIGO, defaults={"nombre": CLIENTE, "tipo": Cliente.Tipo.ABONADO},
        )
        if cliente.nombre != CLIENTE or cliente.tipo != Cliente.Tipo.ABONADO:
            raise CommandError(f"El código {CODIGO} corresponde a otro cliente.")
        planta, _ = cliente.plantas.get_or_create(codigo="PL-82B", defaults={"nombre": "Planta Aurora"})
        generador, _ = cliente.equipos.get_or_create(
            codigo="GE-82B", defaults={"nombre": "Generador Aurora GE-82B", "planta": planta},
        )
        compresor, _ = cliente.equipos.get_or_create(
            codigo="CO-82B", defaults={"nombre": "Compresor Aurora CO-82B", "planta": planta},
        )
        contrato, creado = cliente.contratos_abono.get_or_create(
            referencia="AB-82B", vigente_desde=INICIO_VIGENCIA, defaults={
                "alcance": "Mantenimiento preventivo y limpieza exterior. Las reparaciones correctivas se cotizan aparte.",
                "frecuencia": "Mensual", "valor": 125000, "moneda": "ARS",
            },
        )
        if creado:
            contrato.plantas.add(planta)
            contrato.equipos.add(generador, compresor)
        periodo = dia.replace(day=1)
        mensual, _ = cliente.facturacion_mensual.get_or_create(
            periodo=periodo, defaults={
                "contrato": contrato, "actualizado_por": admin, "fecha_prevista": dia, **datos_del_contrato(contrato),
            },
        )

        fecha = dia.isoformat()
        chequeo = trabajo(
            cliente, planta, generador, f"Termografía de tablero · {fecha}", "Tomar imágenes térmicas",
            vera, oficina, detalle="Servicio adicional con facturación previa, a cargo de Vera.",
        )
        visita_previa = chequeo.visitas_agendadas.first()
        if visita_previa is None:
            visita_previa = cliente.visitas.create(
                planta=planta, fecha=dia, hora_desde=time(8), hora_hasta=time(9),
                referencia_excel=f"Agenda ficticia 8.2B · {fecha}",
            )
            visita_previa.tecnicos.add(vera)
            visita_previa.trabajos.add(chequeo)
            registrar_programacion(visita_previa, coordinacion)

        factura, creada = chequeo.ticket.solicitudes_facturacion.get_or_create(
            modalidad=SolicitudFacturacionTrabajo.Modalidad.PREVIA, defaults={
                "solicitante": admin, "moneda": "ARS", "correo_envio": "aurora@example.com",
                "observaciones": "Solicitud ficticia de anticipo por termografía.",
            },
        )
        if creada:
            factura.trabajos.add(chequeo)
            factura.movimientos.create(autor=admin, estado=factura.estado)

        correctivo = trabajo(
            cliente, planta, compresor, f"Correctivo por vibración · {fecha}", "Medir vibración del compresor",
            bruno, oficina, tipo=Accion.Tipo.ANALISIS, proximo_paso=PASO_CORRECTIVO,
            detalle="Diagnóstico para cotizar la reparación. La reparación queda fuera del abono.",
        )
        lavado = trabajo(
            cliente, planta, generador, f"Limpieza incluida en el abono · {fecha}", "Limpiar exterior del generador",
            bruno, oficina, facturacion=Accion.Facturacion.ABONO, detalle="Limpieza exterior prevista en AB-82B.",
        )
        pedido, creado = lavado.ticket.pedidos_servicio.get_or_create(
            referencia=f"PED-82B-{fecha}", defaults={
                "contrato": contrato, "alcance": "Limpieza exterior del generador incluida en el abono.",
                "indicaciones": "En esta práctica se puede sumar la medición para cotizar. La reparación no está autorizada.",
                "estado": PedidoServicio.Estado.PENDIENTE_AGENDAR,
            },
        )
        if creado:
            pedido.equipos.add(generador)
            pedido.cambios.create(
                autor=coordinacion, estado=pedido.estado, referencia="Preparación de la práctica ficticia 8.2B",
            )

        self.stdout.write(self.style.SUCCESS(f"{CODIGO} · {fecha} · {CLIENTE}"))
        self.stdout.write(f"Pedido {pedido.referencia}: {pedido.get_estado_display()}")
        self.stdout.write(f"Correctivo T-{correctivo.ticket_id}: {correctivo.get_estado_display()}")
        self.stdout.write(f"Visita de Vera V-{visita_previa.pk} · Solicitud SF-{factura.pk}: {factura.get_estado_display()}")
        self.stdout.write(f"Abono {periodo:%Y-%m}: {mensual.get_estado_display()}")
