from collections import Counter
from datetime import datetime, timedelta

from django import forms
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q, Subquery
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from .facturacion_abonos import contratos_del_mes
from .models import (
    Accion, AvisoOperativo, Cliente, FacturacionMensualAbono, MovimientoTiempoAccion, PedidoServicio,
    Recordatorio, SolicitudFacturacionTrabajo, Ticket, Visita,
)
from .permisos import ROLES_FACTURACION, oficina_requerida, requiere_roles
from .recordatorios import avisos_disponibles
from .tiempos import puesto_de_usuario


gerencia_requerida = requiere_roles(ROLES_FACTURACION)


class DiaTableroForm(forms.Form):
    dia = forms.DateField(label="Día", input_formats=["%Y-%m-%d"], widget=forms.DateInput(
        format="%Y-%m-%d", attrs={"type": "date"},
    ))


def dia_y_form(request):
    hoy = timezone.localdate()
    datos = request.GET.copy()
    if "dia" not in datos:
        datos["dia"] = hoy.isoformat()
    form = DiaTableroForm(datos)
    return (form.cleaned_data["dia"] if form.is_valid() else hoy), form


def indicadores(dia):
    periodo = dia.replace(day=1)
    controles = FacturacionMensualAbono.objects.filter(cliente_id=OuterRef("pk"), periodo=periodo)
    contratos = contratos_del_mes(periodo).filter(cliente_id=OuterRef("pk"))
    abonos = Cliente.objects.filter(tipo=Cliente.Tipo.ABONADO).filter(
        Q(Exists(controles.filter(estado=FacturacionMensualAbono.Estado.PENDIENTE)))
        | (Q(Exists(contratos)) & ~Q(Exists(controles))),
    )
    return {
        "sin_asignar": (
            "Tickets sin acciones asignadas",
            Ticket.objects.filter(~Exists(Accion.objects.filter(ticket_id=OuterRef("pk"))))
            .select_related("cliente_ficha").order_by("-pk"),
        ),
        "sin_fecha": (
            "Pedidos de servicio enviados sin fecha",
            PedidoServicio.objects.filter(
                tipo=PedidoServicio.Tipo.SERVICIO,
                estado__in=(PedidoServicio.Estado.ENVIADO, PedidoServicio.Estado.PENDIENTE_AGENDAR),
                fecha_agendada__isnull=True,
            ).select_related("ticket__cliente_ficha"),
        ),
        "abonos": ("Abonos por facturar o revisar", abonos),
        "documentos_trabajos": (
            "Documentación faltante en trabajos",
            SolicitudFacturacionTrabajo.objects.exclude(documentacion_faltante="").select_related("ticket"),
        ),
        "documentos_abonos": (
            "Documentación faltante en abonos",
            FacturacionMensualAbono.objects.filter(periodo=periodo).exclude(estado=FacturacionMensualAbono.Estado.NO_CORRESPONDE)
            .filter(Q(requiere_oc=True, orden_compra="") | Q(requiere_hes=True, hes="")).select_related("cliente"),
        ),
    }


def visitas_del_dia(dia):
    return Visita.objects.filter(fecha=dia).select_related("cliente", "planta").prefetch_related("tecnicos")


def carga_por_tecnico(dia):
    carga = {}
    for visita in visitas_del_dia(dia):
        duracion = datetime.combine(dia, visita.hora_hasta) - datetime.combine(dia, visita.hora_desde)
        for tecnico in visita.tecnicos.all():
            total = carga.setdefault(tecnico.pk, {"tecnico": tecnico, "visitas": 0, "duracion": timedelta()})
            total["visitas"] += 1
            total["duracion"] += duracion
    return sorted(carga.values(), key=lambda item: item["tecnico"].username)


def demoras_por_puesto():
    hoy = timezone.localdate()
    recordatorios = Recordatorio.objects.filter(
        accion_id=OuterRef("pk"), tipo__in=(Recordatorio.Tipo.DEMORA, Recordatorio.Tipo.VENCIMIENTO),
        aviso__resuelto_el__isnull=True,
    ).filter(Q(fecha__lt=hoy) | Q(visita__fecha__lt=hoy))
    acciones = Accion.objects.filter(realizada_el__isnull=True).filter(
        Exists(recordatorios),
    ).select_related("responsable", "ticket").prefetch_related("responsable__groups").order_by("asignada_el", "pk")
    movimientos = MovimientoTiempoAccion.objects.filter(accion_id=OuterRef("pk")).order_by("-ocurrio_el", "-pk")
    acciones = acciones.annotate(puesto_registrado=Subquery(movimientos.values("puesto")[:1]))
    return [(accion.puesto_registrado or puesto_de_usuario(accion.responsable), accion) for accion in acciones]


def documentos_pendientes(control):
    return [
        etiqueta for campo, valor, etiqueta in (
            (control.requiere_oc, control.orden_compra, "OC pendiente"),
            (control.requiere_hes, control.hes, "HES pendiente"),
        ) if campo and not valor
    ]


@gerencia_requerida
def inicio(request):
    dia, form = dia_y_form(request)
    return render(request, "servicios/tablero_gerencia.html", {
        "dia": dia, "form": form,
        "indicadores": [(clave, titulo, registros.count()) for clave, (titulo, registros) in indicadores(dia).items()],
        "carga": carga_por_tecnico(dia),
        "demoras": sorted(Counter(puesto for puesto, _ in demoras_por_puesto()).items()),
    })


def fila(indicador, registro, dia):
    if indicador == "sin_asignar":
        return (reverse("ticket", args=[registro.pk]), f"T-{registro.pk} · {registro.asunto}", registro.cliente_nombre)
    if indicador == "sin_fecha":
        return (
            reverse("pedido_servicio", args=[registro.pk]), f"PS-{registro.pk} · {registro.referencia or registro.ticket.asunto}",
            registro.ticket.cliente_nombre,
        )
    if indicador == "abonos":
        return (reverse("facturacion_abono_mes", args=[dia.strftime("%Y-%m"), registro.pk]), registro.nombre, registro.codigo)
    if indicador == "documentos_trabajos":
        return (
            reverse("facturacion_trabajo", args=[registro.pk]), f"SF-{registro.pk} · {registro.ticket.asunto}",
            registro.documentacion_faltante,
        )
    if indicador == "documentos_abonos":
        return (
            reverse("facturacion_abono_mes", args=[dia.strftime("%Y-%m"), registro.cliente_id]), registro.cliente.nombre,
            ", ".join(documentos_pendientes(registro)),
        )
    if indicador == "carga":
        return (
            reverse("visita", args=[registro.pk]), f"V-{registro.pk} · {registro.cliente.nombre}",
            f"{registro.hora_desde:%H:%M} a {registro.hora_hasta:%H:%M}",
        )
    return (
        f"{reverse('ticket', args=[registro.ticket_id])}#accion-{registro.pk}",
        f"T-{registro.ticket_id} · {registro.titulo}", registro.responsable.get_full_name() or registro.responsable.username,
    )


@gerencia_requerida
def casos(request, indicador):
    dia, _ = dia_y_form(request)
    if indicador == "carga":
        tecnico = request.GET.get("tecnico", "")
        if not tecnico.isascii() or not tecnico.isdecimal() or len(tecnico) > 18:
            raise Http404
        titulo = "Visitas que componen la carga del técnico"
        registros = visitas_del_dia(dia).filter(tecnicos__pk=int(tecnico))
    elif indicador == "demoras":
        puesto = request.GET.get("puesto")
        titulo = f"Trabajos demorados · {puesto}" if puesto else "Trabajos demorados"
        registros = [accion for rol, accion in demoras_por_puesto() if not puesto or puesto == rol]
    else:
        datos = indicadores(dia).get(indicador)
        if datos is None:
            raise Http404
        titulo, registros = datos
    pagina = Paginator(registros, 30).get_page(request.GET.get("page"))
    filtros = request.GET.copy()
    filtros.pop("page", None)
    return render(request, "servicios/tablero_casos.html", {
        "titulo": titulo, "dia": dia, "pagina": pagina, "filas": [fila(indicador, item, dia) for item in pagina],
        "filtros_pagina": filtros.urlencode(),
    })


@oficina_requerida
def pantalla(request):
    hoy = timezone.localdate()
    avisos = AvisoOperativo.objects.filter(avisos_disponibles(), resuelto_el__isnull=True).select_related(
        "recordatorio__visita", "alerta_campo__autor", "atendido_por",
    )
    return render(request, "servicios/pantalla_oficina.html", {
        "hoy": hoy, "visitas": visitas_del_dia(hoy).prefetch_related("trabajos", "pedidos__ticket"),
        "avisos": avisos,
    })
